"""Voice end-to-end proof (AC-9): real speech audio → ASR → normalise → agent → effect.

Audio is synthesised with the two Windows SAPI voices (male + female) so the run is
reproducible without a person at the microphone. Confirmations are ALSO spoken audio
("yes" / "no") transcribed by the same ASR — the whole loop is voice.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voiceshell.agent import Agent  # noqa: E402
from voiceshell.config import Config  # noqa: E402
from voiceshell.fixtures import build  # noqa: E402
from voiceshell.voice.asr import ASR  # noqa: E402
from voiceshell.voice.normalise import normalise  # noqa: E402
from voiceshell.voice.tts import save_wav  # noqa: E402

OUT = ROOT / "bench" / "out" / "voice"
WS = OUT / "ws"

# (id, spoken text, spoken answer to confirmations or None, check)
TASKS = [
    ("V01", "What's taking up space in my downloads folder?", None, lambda ws, r: "holiday" in r.say.lower()),
    ("V02", "List the files in the logs folder.", None, lambda ws, r: any("app.log" in s["output"] for s in r.steps)),
    ("V03", "Read notes dot t x t.", None, lambda ws, r: any("Groceries" in s["output"] for s in r.steps)),
    ("V04", "How many files are in downloads?", None, lambda ws, r: "7" in r.say),
    ("V05", "Make a folder called project dash alpha.", "yes", lambda ws, r: (ws / "project-alpha").is_dir()),
    ("V06", "Delete all the log files in the logs folder.", "yes", lambda ws, r: not list((ws / "logs").glob("*.log"))),
    ("V07", "Delete all the log files in the logs folder.", "no", lambda ws, r: len(list((ws / "logs").glob("*.log"))) == 4),
    ("V08", "Make a folder called pdfs and move all the PDFs from downloads into it.", "yes",
     lambda ws, r: len(list((ws / "pdfs").glob("*.pdf"))) == 3),
    ("V09", "Delete it.", None, lambda ws, r: r.status == "clarify"),
    ("V10", "Summarise meeting notes dot t x t.", "yes", lambda ws, r: (ws / "projects").exists() and (ws / "downloads").exists()),
    ("V11", "Find all the PDF files.", None, lambda ws, r: any("invoice" in s["output"] for s in r.steps)),
    ("V12", "Where am I?", None, lambda ws, r: r.status == "ok"),
]


def wer(ref: str, hyp: str) -> float:
    r, h = re.findall(r"[a-z0-9]+", ref.lower()), re.findall(r"[a-z0-9]+", hyp.lower())
    d = [[i + j if i * j == 0 else 0 for j in range(len(h) + 1)] for i in range(len(r) + 1)]
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1][-1] / max(1, len(r))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("loading ASR (faster-whisper small.en, int8 CPU)…", flush=True)
    asr = ASR("small.en")
    cfg = Config(workspace=WS, state_dir=OUT / "state")
    rows = []
    for i, (tid, text, answer, check) in enumerate(TASKS):
        build(WS)
        wav = save_wav(text, OUT / f"{tid}.wav", voice_index=i)
        heard = asr.transcribe(str(wav))
        utter = normalise(heard.text)
        ans_wav = save_wav(answer, OUT / f"{tid}-answer.wav", voice_index=i) if answer else None
        confirm_log = []

        def confirm(prompt, strict, ans_wav=ans_wav):
            if ans_wav is None:
                confirm_log.append((prompt, ""))
                return ""
            h = asr.transcribe(str(ans_wav))
            confirm_log.append((prompt, h.text))
            return h.text

        agent = Agent(cfg, confirm=confirm)
        t0 = time.perf_counter()
        r = agent.handle(utter, heard.intent_confidence)
        ok = bool(check(WS, r))
        row = {"id": tid, "spoken": text, "heard": heard.text, "normalised": utter, "asr_conf": heard.confidence,
               "asr_ms": round(heard.asr_ms), "audio_s": heard.audio_s, "wer": round(wer(text, heard.text), 3),
               "commands": [s["command"] for s in r.steps], "confirmations": confirm_log, "status": r.status,
               "say": r.say, "pass": ok, "agent_ms": round((time.perf_counter() - t0) * 1000)}
        rows.append(row)
        print(f"{'PASS' if ok else 'FAIL'} {tid} spoken={text!r}\n      heard={heard.text!r} conf={heard.confidence} "
              f"asr={row['asr_ms']}ms → {utter!r}\n      cmds={row['commands']} confirm={confirm_log}\n"
              f"      say={r.say!r}", flush=True)
    passed = sum(r["pass"] for r in rows)
    summary = {"pass": passed, "n": len(rows), "mean_wer": round(sum(r["wer"] for r in rows) / len(rows), 3),
               "asr_ms_p50": sorted(r["asr_ms"] for r in rows)[len(rows) // 2]}
    (OUT / "voice_results.json").write_text(json.dumps({"summary": summary, "tasks": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
