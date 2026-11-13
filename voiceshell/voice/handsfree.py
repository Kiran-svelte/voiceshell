"""Hands-free mode (NFR-41): wake word + automatic listening for answers. No keyboard at any point.

    idle ──"VoiceShell, list the files"──▶ run the request
    idle ──"VoiceShell"──▶ "Yes?" ──next utterance (8 s)──▶ run the request
    any question VoiceShell asks ("Shall I proceed?") ──▶ listens for the answer (8 s); silence = no
    speech without the wake word ──▶ ignored (nothing runs)
    "VoiceShell, stop listening" ──▶ exit

The wake word is spotted by transcribing each speech segment with the same local Whisper model and
fuzzy-matching its first words, so no extra model or download is needed.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

from .normalise import normalise

SR = 16000
_FILLERS = {"hey", "hi", "ok", "okay", "oh", "a", "uh", "um", "hello", "yo"}
STOP = re.compile(r"^\W*(stop( listening)?|goodbye|bye|exit|quit|go to sleep)\b", re.I)


def match_wake(text: str, phrase: str = "voice shell") -> tuple[bool, str]:
    """Does the utterance start with the wake phrase? Returns (woke, the rest of the utterance)."""
    words = list(re.finditer(r"[A-Za-z0-9'-]+", text))
    i = 0
    while i < len(words) and words[i].group(0).lower() in _FILLERS:
        i += 1
    target = phrase.replace(" ", "").lower()
    best, best_span = 0.0, 0
    for span in (1, 2, 3):                              # pick the span that matches BEST (shortest on ties)
        chunk = words[i:i + span]
        if len(chunk) < span:
            continue
        cand = "".join(w.group(0) for w in chunk).lower().replace("-", "").replace("'", "")
        r = SequenceMatcher(None, cand, target).ratio()
        if r > best + 1e-9:
            best, best_span = r, span
    if best >= 0.8:
        rest = text[words[i + best_span - 1].end():].lstrip(" ,.!?:;-")
        return True, rest.strip()
    return False, ""


class MicSource:
    """Captures one speech segment at a time from the default microphone. Deck L1: Silero VAD decides what is
    speech (fans, clicks and hum are not), with a short pre-roll so the first syllable isn't lost; gentle noise
    suppression is applied before recognition. The stream is closed between segments, so VoiceShell never
    hears its own voice."""

    def __init__(self, silence_s: float = 0.8, max_s: float = 12.0, on_state: Callable[[str], None] | None = None):
        self.silence_s, self.max_s = silence_s, max_s
        self.on_state = on_state or (lambda s: None)
        self.vad = None

    def next_segment(self, timeout_s: float | None) -> np.ndarray | None:
        from collections import deque

        import sounddevice as sd

        from .vad import CHUNK, StreamingVAD, denoise
        if self.vad is None:
            self.vad = StreamingVAD()
        self.vad.reset()
        frames: list[np.ndarray] = []
        pre = deque(maxlen=8)                            # ~0.25 s of audio before speech was detected
        step = CHUNK / SR
        self.on_state("listening")
        with sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=CHUNK) as stream:
            started, quiet, t, spoken, run = False, 0.0, 0.0, 0.0, 0
            while True:
                b, _ = stream.read(CHUNK)
                x = b[:, 0].copy()
                t += step
                p = self.vad.prob(x)
                if not started:
                    pre.append(x)
                    run = run + 1 if p > 0.5 else 0
                    if run >= 2:                          # two speech chunks in a row = someone is talking
                        started = True
                        frames.extend(pre)
                        spoken = len(pre) * step
                    elif timeout_s is not None and t > timeout_s:
                        break
                    continue
                frames.append(x)
                spoken += step
                quiet = quiet + step if p < 0.35 else 0.0
                if quiet >= self.silence_s or spoken >= self.max_s:
                    break
        self.on_state("processing" if frames else "idle")
        if not frames or spoken < 0.3:
            return None
        return denoise(np.concatenate(frames))


class FileSource:
    """Replays recorded segments (wav paths; None = a stretch of silence). Used by the automated tests."""

    def __init__(self, items: Iterable[Path | None]):
        self.items = list(items)

    def next_segment(self, timeout_s: float | None):
        if not self.items:
            raise StopIteration
        return self.items.pop(0)


@dataclass
class HandsFree:
    asr: object
    source: object
    speak: Callable[[str], None]
    phrase: str = "voice shell"
    answer_timeout_s: float = 8.0
    on_event: Callable[[str, str], None] = lambda kind, text: None
    log: list[dict] = field(default_factory=list)
    identify: Callable | None = None       # P1 speaker identity: audio → Identity (None = not set up)
    _last_seg: object = None
    _speaker: object = None

    def hear(self, timeout_s: float | None):
        seg = self.source.next_segment(timeout_s)
        if seg is None:
            return None
        self._last_seg = seg
        h = self.asr.transcribe(seg if isinstance(seg, np.ndarray) else str(seg))
        return h if h.text.strip() else None

    def _who(self):
        return self.identify(self._last_seg) if self.identify and self._last_seg is not None else None

    def confirm(self, prompt: str, strict: bool) -> str:
        """Agent callback: speak the question, then listen for the answer. Silence = no. With speaker ID on, only
        the voice that made the request can approve it — a bystander's "yes" counts as no."""
        self.on_event("ask", prompt)
        self.speak(prompt)
        h = self.hear(self.answer_timeout_s)
        answer = h.text if h else ""
        _, rest = match_wake(answer, self.phrase)          # "VoiceShell, yes" also counts
        answer = rest or answer
        if answer and self.identify and self._speaker is not None:
            who = self._who()
            if who is None or who.name is None or who.name != self._speaker.name:
                self.on_event("info", f"That answer came from {who.describe() if who else 'an unknown voice'}, "
                                      f"not {self._speaker.describe()}: treated as no.")
                self.log.append({"kind": "answer", "prompt": prompt, "answer": "", "rejected_voice": True})
                return ""
        self.on_event("answer", answer or "(silence)")
        self.log.append({"kind": "answer", "prompt": prompt, "answer": answer})
        return answer

    def run(self, agent, max_turns: int | None = None) -> list[dict]:
        turns = 0
        follow_up = None          # an answer to a clarifying question: no wake word needed
        self.on_event("info", f"Say \"{self.phrase.title().replace(' ', '')}\" and then your request.")
        while max_turns is None or turns < max_turns:
            if follow_up is not None:
                h, follow_up = follow_up, None
                woke, rest = match_wake(h.text, self.phrase)
                rest = rest if woke else h.text
            else:
                try:
                    h = self.hear(None)
                except StopIteration:
                    break
                if h is None:
                    continue
                woke, rest = match_wake(h.text, self.phrase)
                if not woke:
                    self.on_event("ignored", "")       # never display or keep what bystanders said
                    self.log.append({"kind": "ignored"})               # no text: bystanders are not recorded
                    continue
                if not rest:                              # just the wake word: ask for the request
                    self.on_event("woke", "")
                    self.speak("Yes?")
                    try:
                        h = self.hear(self.answer_timeout_s)
                    except StopIteration:
                        break
                    if h is None:
                        self.log.append({"kind": "timeout"})
                        continue
                    rest = h.text
            if STOP.match(rest):
                self.speak("Goodbye.")
                self.log.append({"kind": "stop"})
                break
            request = normalise(rest)
            self.on_event("request", request)
            self._speaker = self._who()
            if self._speaker is not None:
                self.on_event("speaker", self._speaker.describe())
            r = agent.handle(request, getattr(h, "intent_confidence", h.confidence), speaker=self._speaker)
            self.speak(r.say)
            self.log.append({"kind": "turn", "heard": h.text, "request": request, "status": r.status, "say": r.say,
                             "commands": [s["command"] for s in r.steps]})
            turns += 1
            if r.status == "clarify":                     # it asked YOU something: listen for the answer
                try:
                    follow_up = self.hear(self.answer_timeout_s)
                except StopIteration:
                    break
                if follow_up is None:
                    self.log.append({"kind": "timeout"})
        return self.log
