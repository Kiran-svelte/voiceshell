"""L3 context assembly (deck slides 4, 6, 8): $CWD · shell history · /proc · env vars · live filesystem events ·
MemoryBank retrieval · sliding context window.

Windows equivalents: /proc → psutil (CPU, memory, disk, processes); inotify → watchdog (ReadDirectoryChangesW).
Everything derived from file names or past output is UNTRUSTED: it is fenced for the model and added to the turn's
untrusted outputs, so provenance rule T1 never lets it choose a delete target.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import threading
import time
from collections import Counter, deque
from pathlib import Path

from .config import Config

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "my", "me", "is", "it", "all", "please", "what",
         "show", "can", "you", "files", "file", "folder", "voiceshell"}


def _terms(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


class CommandHistory:
    """Persistent shell-history store (deck: 'command history store'). Only commands that actually ran."""

    def __init__(self, path: Path, keep: int = 2000):
        self.path, self.keep = path, keep
        self._writes = 0

    def add(self, cwd: str, command: str, exit_code: int) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 1), "cwd": cwd, "command": command, "exit": exit_code}) + "\n")
        self._writes += 1
        if self._writes % 100 == 0:          # amortised trim: keep only the most recent `keep` lines
            self.trim()

    def trim(self) -> int:
        if not self.path.exists():
            return 0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self.keep:
            return 0
        kept = lines[-self.keep:]
        self.path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return len(lines) - len(kept)

    def recent(self, n: int = 6) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(l) for l in lines if l.strip()]


class MemoryBank:
    """Long-term memory of past turns with BM25 retrieval (deck: 'MemoryBank retrieval'). Stores the user's words,
    the commands that ran, the measured reply and Reflexion lessons. Never raw command output."""

    def __init__(self, path: Path, max_rows: int = 2000):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS mem (id INTEGER PRIMARY KEY, ts REAL, kind TEXT, "
                        "utterance TEXT, commands TEXT, say TEXT)")
        self.db.commit()
        self.lock = threading.Lock()
        self.max_rows = max_rows
        self._adds = 0

    def add(self, kind: str, utterance: str, commands: list[str], say: str) -> None:
        with self.lock:
            self.db.execute("INSERT INTO mem (ts, kind, utterance, commands, say) VALUES (?,?,?,?,?)",
                            (time.time(), kind, utterance, json.dumps(commands), say[:400]))
            self.db.commit()
            self._adds += 1
            if self._adds % 50 == 0:
                self._evict_locked()

    def evict(self) -> int:
        """Bounded memory: keep only the most recent `max_rows` turns; delete older ones."""
        with self.lock:
            return self._evict_locked()

    def _evict_locked(self) -> int:
        cur = self.db.execute("SELECT COUNT(*) FROM mem").fetchone()[0]
        if cur <= self.max_rows:
            return 0
        self.db.execute("DELETE FROM mem WHERE id NOT IN (SELECT id FROM mem ORDER BY id DESC LIMIT ?)",
                        (self.max_rows,))
        self.db.commit()
        self.db.execute("VACUUM")
        return cur - self.max_rows

    def count(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM mem").fetchone()[0]

    def search(self, query: str, k: int = 3) -> list[dict]:
        q = _terms(query)
        if not q:
            return []
        with self.lock:
            rows = self.db.execute("SELECT ts, kind, utterance, commands, say FROM mem ORDER BY id DESC LIMIT 500").fetchall()
        docs = [(r, _terms(r[2] + " " + " ".join(json.loads(r[3])))) for r in rows]
        if not docs:
            return []
        n = len(docs)
        avg = sum(len(t) for _, t in docs) / n or 1
        df = Counter(w for _, t in docs for w in set(t))
        scored = []
        for r, t in docs:
            tf = Counter(t)
            s = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * 2.2 / (tf[w] + 1.2 * (0.25 + 0.75 * len(t) / avg))
                    for w in q if w in tf)
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: -x[0])
        return [{"ts": r[0], "kind": r[1], "utterance": r[2], "commands": json.loads(r[3]), "say": r[4]}
                for _, r in scored[:k]]


class FileEvents:
    """Live filesystem events in the workspace (deck: 'inotify events'; Windows: ReadDirectoryChangesW)."""

    def __init__(self, root: Path, keep: int = 200):
        self.root, self.events = root, deque(maxlen=keep)
        self.observer = None
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer

            outer = self

            class _H(FileSystemEventHandler):
                def on_any_event(self, e):
                    if e.event_type in ("created", "deleted", "modified", "moved") and not e.is_directory:
                        try:
                            rel = Path(e.src_path).resolve().relative_to(outer.root).as_posix()
                        except ValueError:
                            return
                        outer.events.append((time.time(), e.event_type, rel))

            self.observer = Observer()
            self.observer.daemon = True
            self.observer.schedule(_H(), str(root), recursive=True)
            self.observer.start()
        except Exception:  # noqa: BLE001 — context is best-effort, never fatal
            self.observer = None

    def recent(self, window_s: float = 900, limit: int = 8) -> list[str]:
        now, seen, out = time.time(), set(), []
        for ts, kind, rel in reversed(self.events):
            if now - ts > window_s or (kind, rel) in seen:
                continue
            seen.add((kind, rel))
            out.append(f"{kind} {rel} ({int(now - ts)}s ago)")
            if len(out) >= limit:
                break
        return out

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()


_STATE_CACHE: dict = {"t": 0.0, "v": []}


def system_state(ws: Path, ttl_s: float = 60.0) -> list[str]:
    """/proc equivalent: CPU, memory, disk and the busiest processes (names only). Scanning every process
    takes ~1 s on Windows, so the reading is cached for a minute."""
    if time.time() - _STATE_CACHE["t"] < ttl_s and _STATE_CACHE["v"]:
        return _STATE_CACHE["v"]
    _STATE_CACHE["v"] = _system_state(ws)
    _STATE_CACHE["t"] = time.time()
    return _STATE_CACHE["v"]


def _system_state(ws: Path) -> list[str]:
    try:
        import psutil
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(ws))
        top = sorted(psutil.process_iter(["name", "memory_info"]),
                     key=lambda p: (p.info["memory_info"].rss if p.info["memory_info"] else 0), reverse=True)[:3]
        return [f"CPU {psutil.cpu_percent(interval=None):.0f}% · memory {mem.used / 2**30:.1f}/{mem.total / 2**30:.1f} GB",
                f"disk free {disk.free / 2**30:.0f} GB of {disk.total / 2**30:.0f} GB",
                "busiest processes: " + ", ".join(p.info["name"] or "?" for p in top)]
    except Exception:  # noqa: BLE001
        return []


ENV_ALLOW = ("OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS")


class ContextAssembler:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.history = CommandHistory(cfg.state_dir / "history.jsonl", keep=cfg.history_max_lines)
        self.memory = MemoryBank(cfg.state_dir / "memory.db", max_rows=cfg.memory_max_rows)
        self.events = FileEvents(cfg.workspace)

    def block(self, utterance: str, cwd_rel: str) -> tuple[str, str]:
        """Returns (trusted system context, untrusted context text). The caller fences the untrusted part."""
        env = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
        trusted = [f"$CWD = {cwd_rel} (workspace root is ~)", "shell: GNU bash (Git Bash) inside a Windows job sandbox",
                   "env: " + ", ".join(f"{k}={v}" for k, v in env.items())] + system_state(self.cfg.workspace)
        untrusted = []
        hist = self.history.recent(6)
        if hist:
            untrusted.append("recent shell history: " + " ; ".join(f"[{h['cwd']}] {h['command']} (exit {h['exit']})"
                                                                     for h in hist))
        ev = self.events.recent()
        if ev:
            untrusted.append("recent file changes: " + "; ".join(ev))
        mem = self.memory.search(utterance)
        for m in mem:
            age = int((time.time() - m["ts"]) / 60)
            untrusted.append(f"related earlier request ({age} min ago): \"{m['utterance']}\" → ran "
                             f"{m['commands'] or 'nothing'} → said \"{m['say'][:160]}\"" if m["kind"] == "turn"
                             else f"lesson from an earlier failure: {m['say'][:200]}")
        return "\n".join(trusted), "\n".join(untrusted)

    def close(self) -> None:
        self.events.stop()


def sliding_window(history: list[dict], keep: int = 4) -> list[dict]:
    """Deck: 'sliding context window'. The planner sees the last `keep` steps in full; older ones as one line."""
    if len(history) <= keep:
        return history
    older = history[:-keep]
    summary = {"command": "; ".join(h["command"] for h in older), "exit": 0,
               "fenced": f"({len(older)} earlier step(s), outputs omitted to save context)"}
    return [summary] + history[-keep:]
