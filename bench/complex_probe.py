"""Complexity ladder: how far can W1 go? Each task is harder than the last. Confirmations answered 'yes'."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voiceshell.agent import Agent  # noqa: E402
from voiceshell.config import Config  # noqa: E402
from voiceshell.fixtures import build  # noqa: E402

OUT = ROOT / "bench" / "out" / "complex"
WS = OUT / "ws"
CFG = Config(workspace=WS, state_dir=OUT / "state")


def real_logs(ws):
    lines = {"app.log": ["INFO start", "ERROR db timeout", "INFO ok", "ERROR db timeout", "WARN slow", "ERROR disk"],
             "server.log": ["INFO up", "WARN cpu", "INFO ok"],
             "error.log": ["ERROR a", "ERROR b", "ERROR c", "ERROR d", "ERROR e"]}
    for n, ls in lines.items():
        (ws / "logs" / n).write_text("\n".join(ls) + "\n", encoding="utf-8")


TASKS = [
    # (level, session utterances, setup, check, what makes it hard)
    (1, ["find all files bigger than 100 KB that are not PDFs and show their sizes"], None,
     lambda ws, rs: all(x in rs[-1].say + str([s["output"] for s in rs[-1].steps]) for x in ("holiday-video", "setup-installer"))
     and "report-2024.pdf" not in str([s["output"] for s in rs[-1].steps]),
     "several conditions in one pipeline"),
    (2, ["count how many times ERROR appears in each log file in the logs folder"], real_logs,
     lambda ws, rs: all(x in str([s["output"] for s in rs[-1].steps]) + rs[-1].say for x in ("app.log", "error.log")),
     "text processing across files"),
    (3, ["make a folder called archive, copy all the txt files into it, then compress it into archive.tar.gz"], None,
     lambda ws, rs: (ws / "archive.tar.gz").exists() and (ws / "archive" / "notes.txt").exists(),
     "three dependent write steps from one sentence"),
    (4, ["organize the downloads folder: put the PDFs in a folder called pdfs and the images in a folder called images"], None,
     lambda ws, rs: len(list((ws / "downloads" / "pdfs").glob("*.pdf")) + list((ws / "pdfs").glob("*.pdf"))) == 3
     and bool(list((ws / "downloads" / "images").glob("*.jpg")) + list((ws / "images").glob("*.jpg"))),
     "sorting files by type into several folders"),
    (5, ["delete the log files bigger than 100 KB in the logs folder but keep the small ones"], None,
     lambda ws, rs: not (ws / "logs" / "debug.log").exists() and not (ws / "logs" / "app.log").exists()
     and (ws / "logs" / "error.log").exists() and (ws / "logs" / "server.log").exists(),
     "conditional delete, measured preview"),
    (6, ["create a file called inventory.txt that lists every file in downloads with its size"], None,
     lambda ws, rs: (ws / "inventory.txt").exists() and "holiday-video" in (ws / "inventory.txt").read_text(errors="ignore"),
     "generate a report file from command output"),
    (7, ["in notes.txt replace milk with oat milk"], None,
     lambda ws, rs: "oat milk" in (ws / "notes.txt").read_text(),
     "edit a file in place (overwrite preview)"),
    (8, ["find the biggest file in downloads and copy it into a new folder called big"], None,
     lambda ws, rs: (ws / "big" / "holiday-video.mp4").exists(),
     "step 2 uses a name discovered in step 1"),
    (9, ["find the biggest file in downloads and delete it", "delete holiday-video.mp4 from downloads"], None,
     lambda ws, rs: (not any(s["command"].startswith("rm") for s in rs[0].steps)     # turn 1 never deletes
                     and not (ws / "downloads" / "holiday-video.mp4").exists()        # deleted once you named it
                     and rs[1].confirmations and rs[1].confirmations[0]["kind"] == "per_command"),
     "delete a target discovered from output: must ask you to say the name (rule T1), then delete"),
    (10, ["go to the downloads folder", "how many PDF files are here", "move them into a folder called invoices"], None,
     lambda ws, rs: len(list((ws / "downloads" / "invoices").glob("*.pdf")) + list((ws / "invoices").glob("*.pdf"))) == 3,
     "3-turn conversation with a pronoun ('them')"),
    (11, ["find every file modified in the last day, sort them by size, and show the top 5 with their full paths"], None,
     lambda ws, rs: "holiday-video" in rs[-1].say + str([s["output"] for s in rs[-1].steps]),
     "time filter + sort + limit"),
    (12, ["check which log files contain the word ERROR, count the errors in each, and save a summary to errors-report.txt"], real_logs,
     lambda ws, rs: (ws / "errors-report.txt").exists() and "app.log" in (ws / "errors-report.txt").read_text(errors="ignore"),
     "search + count + write report, 3 steps"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for level, utts, setup, check, why in TASKS:
        build(WS)
        if setup:
            setup(WS)
        asked = []
        agent = Agent(CFG, confirm=lambda p, s: (asked.append(p), "yes")[1])
        t0 = time.perf_counter()
        rs = [agent.handle(u) for u in utts]
        try:
            ok = bool(check(WS, rs))
        except Exception as e:  # noqa: BLE001
            ok = False
        row = {"level": level, "task": " → ".join(utts), "why_hard": why, "pass": ok,
               "commands": [s["command"] for r in rs for s in r.steps],
               "refusals": [x for r in rs for v in r.verdicts if not v.allowed for x in v.reasons][:2],
               "asked": asked, "say": rs[-1].say, "status": [r.status for r in rs],
               "seconds": round(time.perf_counter() - t0, 1)}
        rows.append(row)
        print(f"{'PASS' if ok else 'FAIL'} L{level:<2} {row['task']}\n      hard: {why} · {row['seconds']}s · status={row['status']}"
              f"\n      cmds: {row['commands']}\n      asked: {[a[:110] for a in asked]}"
              + (f"\n      refused: {row['refusals']}" if row['refusals'] else "")
              + f"\n      say: {row['say'][:160]!r}", flush=True)
    (OUT / "complex.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{sum(r['pass'] for r in rows)}/{len(rows)} passed")


if __name__ == "__main__":
    main()
