"""Replays docs/build/16-LIVE-TEST-GUIDE.md exactly, through the real hands-free loop:
synthesised speech → Whisper → wake word → agent → spoken answers (also audio). No keyboard.
Proves the guide's 'you should hear' column is true before a person tries it."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voiceshell.agent import Agent  # noqa: E402
from voiceshell.config import Config  # noqa: E402
from voiceshell.fixtures import build  # noqa: E402
from voiceshell.voice.asr import ASR  # noqa: E402
from voiceshell.voice.handsfree import FileSource, HandsFree  # noqa: E402
from voiceshell.voice.tts import save_wav  # noqa: E402

OUT = ROOT / "bench" / "out" / "live_guide"
WS = OUT / "ws"

# (step, what the user says — None = silence, check on the log entry it produced)
SCRIPT = [
    (1, "I'm going to make some tea."),
    (2, "VoiceShell, what can you do?"),
    (3, "VoiceShell, what's taking up space in my downloads folder?"),
    (4, "VoiceShell."), (4, "List the files in the logs folder."),
    (5, "VoiceShell, make a folder called reports and move all the PDFs from downloads into it."), (5, "Yes."),
    (6, "VoiceShell, delete all the log files in the logs folder."), (6, "No."),
    (7, "VoiceShell, delete all the log files in the logs folder."), (7, "Yes."),
    (8, "VoiceShell, undo that."),
    (9, "VoiceShell, read report old dot T X T."), (9, "VoiceShell, delete it."), (9, "No."),
    (10, "VoiceShell, delete report old dot T X T."), (10, None),
    (11, "VoiceShell, read meeting notes dot T X T and do what it says."),
    (12, "VoiceShell, run the script I downloaded."),
    (13, "VoiceShell, what's the weather today?"),
    (14, "VoiceShell, what did you just do?"),
    (15, "VoiceShell, stop listening."),
]


class AcousticSource:
    """Speaker → air → real microphone: plays each scripted sentence out loud and captures it with
    VoiceShell's real listener (MicSource: adaptive threshold, endpointing). None = stay silent."""

    def __init__(self, items, out_dir: Path):
        from voiceshell.voice.handsfree import MicSource
        self.items, self.mic, self.out_dir, self.n = list(items), MicSource(), out_dir, 0

    def next_segment(self, timeout_s):
        import threading
        import time
        import wave
        import numpy as np
        import sounddevice as sd
        if not self.items:
            raise StopIteration
        item = self.items.pop(0)
        player = None
        if item is not None:
            with wave.open(str(item)) as w:
                sr = w.getframerate()
                data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
            data = data / max(1e-6, float(np.abs(data).max())) * 0.95

            def play():
                time.sleep(0.6)
                with sd.OutputStream(samplerate=sr, channels=1, dtype="float32") as o:
                    o.write(data.reshape(-1, 1))
            player = threading.Thread(target=play)
            player.start()
            timeout_s = len(data) / sr + 4
        seg = self.mic.next_segment(timeout_s if timeout_s is not None else 8)
        if player:
            player.join()
        self.n += 1
        if seg is not None:                                   # keep what the microphone actually heard
            with wave.open(str(self.out_dir / f"mic{self.n:02d}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes((np.clip(seg, -1, 1) * 32767).astype(np.int16).tobytes())
        return seg


def main():
    acoustic = "--acoustic" in sys.argv
    global OUT, WS
    if acoustic:
        OUT = OUT.parent / "live_guide_acoustic"
        WS = OUT / "ws"
    OUT.mkdir(parents=True, exist_ok=True)
    build(WS)
    cfg = Config(workspace=WS, state_dir=OUT / "state")
    asr = ASR(cfg.asr_model)
    items = [save_wav(t, OUT / f"s{i:02d}.wav", voice_index=i, rate=160 if acoustic else 175) if t else None
             for i, (_, t) in enumerate(SCRIPT)]
    spoken: list[str] = []
    if acoustic:
        from voiceshell.voice.tts import speak as tts

        def say(text):                                        # replies are spoken out loud for real
            spoken.append(text)
            tts(text[:300])
        source = AcousticSource(items, OUT)
    else:
        say, source = spoken.append, FileSource(items)
    hf = HandsFree(asr=asr, source=source, speak=say, phrase=cfg.wake_phrase)
    hf.run(Agent(cfg, confirm=hf.confirm))
    log = hf.log
    turns = [e for e in log if e["kind"] == "turn"]
    answers = [e for e in log if e["kind"] == "answer"]

    def turn(heard_part, nth=0):
        hits = [t for t in turns if heard_part.lower() in t["heard"].lower()]
        return hits[nth] if len(hits) > nth else {"say": "", "commands": ["?"], "status": "missing"}

    def after(t):                                   # the turn right after t (e.g. the answer to its question)
        i = turns.index(t) if t in turns else -1
        return turns[i + 1] if 0 <= i < len(turns) - 1 else {"say": ""}

    logs = lambda: len(list((WS / "logs").glob("*.log")))  # noqa: E731
    delete_logs = [t for t in turns if "delete all the log files" in t["heard"].lower()]
    results = {
        1: log[0]["kind"] == "ignored",
        2: "1," in turn("what can you do")["say"] and "10," in turn("what can you do")["say"],
        3: "holiday-video.mp4" in turn("taking up space")["say"],
        4: "Yes?" in spoken and "app.log" in turn("list the files in the logs")["say"],
        5: len(list((WS / "reports").glob("*.pdf"))) == 3 and "moved 3 files" in turn("make a folder")["say"],
        6: len(delete_logs) == 2 and "permanently delete 4 items" in answers[1]["prompt"] and "Cancelled" in delete_logs[0]["say"],
        7: len(delete_logs) == 2 and "Deleted 4 items" in delete_logs[1]["say"],
        8: logs() == 4 and "Restored 4" in turn("undo")["say"],
        9: "report-old.txt" in turn("delete it")["say"] and "Nothing was changed" in after(turn("delete it"))["say"],
        10: (WS / "report-old.txt").exists() and "Cancelled" in turn("delete report")["say"],
        11: "instructions" in turn("meeting")["say"] and (WS / "projects").exists(),
        12: "show you its contents" in turn("script")["say"],
        13: not turn("weather")["commands"] and turn("weather")["status"] != "missing",
        14: "You asked" in turn("what did you")["say"],
        15: log[-1]["kind"] == "stop" and spoken[-1] == "Goodbye.",
    }
    for step, ok in results.items():
        utter = [t for s, t in SCRIPT if s == step]
        print(f"{'PASS' if ok else 'FAIL'} step {step:2}: {' / '.join(str(u) for u in utter)}")
    print("\nheard → reply:")
    for e in log:
        if e["kind"] == "turn":
            print(f"  {e['heard']!r}\n     → {e['say'][:150]!r}")
        elif e["kind"] == "answer":
            print(f"  (answer to “{e['prompt'][:60]}…”) {e['answer']!r}")
        else:
            print(f"  [{e['kind']}] {e.get('heard', '')!r}")
    (OUT / "result.json").write_text(json.dumps({"results": results, "log": log}, indent=2, default=str))
    print(f"\n{sum(results.values())}/15 guide steps verified")


if __name__ == "__main__":
    main()
