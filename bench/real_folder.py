"""Real-folder test: a large, messy, NON-personal folder (copy of Python's standard library + this
project's docs). Measures whether typical requests still work, and what scale costs (rehearsal copies)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voiceshell.agent import Agent  # noqa: E402
from voiceshell.config import Config  # noqa: E402

OUT = ROOT / "bench" / "out" / "real"
WS = OUT / "ws"
LIB = Path(sys.base_prefix) / "Lib"


def build():
    shutil.rmtree(OUT, ignore_errors=True)
    shutil.copytree(LIB, WS / "python-lib", ignore=shutil.ignore_patterns("site-packages"))
    shutil.copytree(ROOT / "docs", WS / "project docs", ignore=shutil.ignore_patterns("*.zip"))
    shutil.copy(ROOT / "VoiceShell_02 - final_to students.pptx", WS / "VoiceShell deck.pptx")
    files = sum(len(f) for _, _, f in os.walk(WS))
    size = sum((Path(d) / f).stat().st_size for d, _, fs in os.walk(WS) for f in fs)
    return files, size


TASKS = [
    ("what's taking up space in this folder", None, lambda ws, r: "python-lib" in r.say or "pptx" in r.say.lower()),
    ("how many python files are there in python-lib", None,
     lambda ws, r: str(len(list((ws / "python-lib").rglob("*.py")))) in r.say),
    ("find all the files with json in their name", None, lambda ws, r: "json" in str([s["output"] for s in r.steps]).lower()),
    ("search for the word deprecated in the python-lib/email folder and tell me which files mention it", None,
     lambda ws, r: ".py" in r.say or ".py" in str([s["output"] for s in r.steps])),
    ("how big is the asyncio folder in python-lib", None, lambda ws, r: any(u in r.say for u in ("K", "M", "kilo", "mega"))),
    ("make a folder called docs-backup and copy all the markdown files from project docs into it", "yes",
     lambda ws, r: len(list((ws / "docs-backup").glob("*.md"))) >= 7),
    ("delete all the pyc files in python-lib", "yes",
     lambda ws, r: not list((ws / "python-lib").rglob("*.pyc"))),
    ("undo that", None, lambda ws, r: bool(list((ws / "python-lib").rglob("*.pyc")))),
    ("rename the email folder in python-lib to mail", "yes",
     lambda ws, r: (ws / "python-lib" / "mail").is_dir() and not (ws / "python-lib" / "email").exists()),
]


def main():
    files, size = build()
    print(f"workspace: {files} files, {size / 2**20:.0f} MB")
    cfg = Config(workspace=WS, state_dir=OUT / "state")
    answers: list[str] = []
    asked: list[str] = []
    agent = Agent(cfg, confirm=lambda p, s: (asked.append(p), answers.pop(0) if answers else "")[1])
    agent.llm.warm()
    rows = []
    for utt, ans, check in TASKS:
        answers[:] = [ans] if ans else []
        asked.clear()
        t0 = time.perf_counter()
        r = agent.handle(utt)
        secs = time.perf_counter() - t0
        ok = bool(check(WS, r))
        rows.append({"task": utt, "pass": ok, "seconds": round(secs, 1), "commands": [s["command"] for s in r.steps],
                     "asked": list(asked), "say": r.say, "status": r.status})
        print(f"{'PASS' if ok else 'FAIL'} {utt}  ({secs:.1f}s)\n      cmds={rows[-1]['commands']}\n"
              f"      asked={[a[:120] for a in asked]}\n      say={r.say[:170]!r}", flush=True)
    (OUT.parent / "real_folder.json").write_text(json.dumps({"files": files, "mb": round(size / 2**20),
                                                             "tasks": rows}, indent=2), encoding="utf-8")
    print(f"\n{sum(r['pass'] for r in rows)}/{len(rows)} passed")


if __name__ == "__main__":
    main()
