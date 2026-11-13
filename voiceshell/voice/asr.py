"""Speech in: push-to-talk capture with energy endpointing + faster-whisper, CLI-vocabulary biased."""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 16000
CLI_PROMPT = ("VoiceShell, voice commands for a computer shell. List the files. Show the biggest files. Delete the log files. "
              "Move the PDFs into the reports folder. Read the file notes.txt. Make a folder called project-alpha. "
              "How much disk space is free? Undo that. Yes. No. Proceed.")


@dataclass
class Heard:
    text: str
    confidence: float
    audio_s: float
    asr_ms: float
    intent_confidence: float = 1.0   # lowest confidence among the words that grant authority (delete, move…)


class ASR:
    def __init__(self, model: str = "small.en"):
        from faster_whisper import WhisperModel
        # Offline by default: load from the local cache without contacting the model hub.
        # Only if the model was never downloaded do we fetch it once (and say so).
        try:
            self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=8, local_files_only=True)
        except Exception:  # noqa: BLE001 — not cached yet
            print(f"[voiceshell] speech model '{model}' not cached; downloading it once (needs internet)…")
            self.model = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=8)

    def transcribe(self, audio) -> Heard:
        """audio: path to a wav file, or float32 mono 16 kHz numpy array."""
        t0 = time.perf_counter()
        segs, info = self.model.transcribe(audio, language="en", beam_size=5, initial_prompt=CLI_PROMPT,
                                           vad_filter=True, condition_on_previous_text=False, word_timestamps=True)
        segs = list(segs)
        text = " ".join(s.text.strip() for s in segs).strip()
        # confidence = mean per-word probability (exp(avg_logprob) is ~0.6-0.8 even for perfect
        # transcripts, which would make the "no DELETE below 0.8" envelope rule fire on everything)
        words = [w.probability for s in segs for w in (s.words or [])]
        conf = sum(words) / len(words) if words else (
            math.exp(sum(s.avg_logprob for s in segs) / len(segs)) if segs else 0.0)
        # Confidence for the envelope's "no DELETE when unsure" rule: the mean over the REQUEST's words, leaving
        # out the two kinds of word Whisper always scores low even when heard perfectly: the wake word, and
        # file names (rare tokens). File names are verified separately: they must match a real file, and the
        # measured preview reads them back before an explicit yes. (A single word's score is too noisy to
        # use alone: the first word of a sentence often scores 0.3 when it was heard correctly.)
        ws = [(w.word.strip(), w.probability) for s in segs for w in (s.words or [])]

        def skip(i: int) -> bool:
            w, nxt = ws[i][0], (ws[i + 1][0] if i + 1 < len(ws) else "")
            alpha = "".join(ch for ch in w.lower() if ch.isalpha())
            wake = i < 3 and alpha in {"voiceshell", "voice", "shell", "hey", "ok", "okay"}
            name = w.startswith(".") or nxt.startswith(".") or bool(re.search(r"\w\.\w{1,5}\W*$", w))
            return wake or name
        kept = [p for i, (_, p) in enumerate(ws) if not skip(i)]
        intent_conf = sum(kept) / len(kept) if kept else conf
        return Heard(text, round(conf, 3), round(info.duration, 2), (time.perf_counter() - t0) * 1000,
                     round(intent_conf, 3))


def record_until_silence(max_s: float = 12.0, silence_s: float = 0.8, no_speech_s: float = 5.0,
                         on_level=None) -> np.ndarray:
    """Endpointing: calibrate noise for 0.3 s, start on speech, stop after `silence_s` of quiet."""
    import sounddevice as sd
    block = int(SR * 0.03)
    frames: list[np.ndarray] = []
    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=block) as stream:
        noise = []
        for _ in range(10):
            b, _ = stream.read(block)
            noise.append(float(np.sqrt(np.mean(b ** 2))))
        thresh = max(0.003, 4.0 * float(np.median(noise)))   # adaptive: this laptop mic records speech at ~0.01 RMS
        started, quiet, t = False, 0.0, 0.0
        while t < max_s:
            b, _ = stream.read(block)
            rms = float(np.sqrt(np.mean(b ** 2)))
            t += 0.03
            if on_level:
                on_level(rms, thresh)
            if rms > thresh:
                started, quiet = True, 0.0
            elif started:
                quiet += 0.03
            if started:
                frames.append(b[:, 0].copy())
                if quiet >= silence_s:
                    break
            elif t > no_speech_s:
                break
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)
