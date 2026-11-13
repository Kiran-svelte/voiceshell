"""Runtime housekeeping: start the local model server if needed, and the `doctor` self-check."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .config import Config


def _ollama_exe() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return p if p.is_file() else None


def ollama_up(cfg: Config) -> bool:
    try:
        return httpx.get(f"{cfg.ollama_url}/api/tags", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def model_present(cfg: Config) -> bool:
    try:
        tags = httpx.get(f"{cfg.ollama_url}/api/tags", timeout=3).json().get("models", [])
        return any(m["name"] == cfg.model or m["name"].startswith(cfg.model + ":") for m in tags)
    except (httpx.HTTPError, ValueError):
        return False


def ensure_ollama(cfg: Config, wait_s: float = 30.0) -> tuple[bool, str]:
    """Start `ollama serve` in the background (no window) if it isn't running. Local only: 127.0.0.1."""
    if ollama_up(cfg):
        return True, "local model server already running"
    exe = _ollama_exe()
    if exe is None:
        return False, "Ollama is not installed (https://ollama.com), so only built-in commands will work"
    flags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        flags |= getattr(subprocess, name, 0)
    log = cfg.state_dir / "ollama.log"
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as out:
        subprocess.Popen([str(exe), "serve"], stdout=out, stderr=out, stdin=subprocess.DEVNULL,
                         creationflags=flags, env={**os.environ, "OLLAMA_HOST": "127.0.0.1:11434"},
                         close_fds=True)
    t0 = time.time()
    while time.time() - t0 < wait_s:
        if ollama_up(cfg):
            return True, f"started the local model server ({time.time() - t0:.0f}s)"
        time.sleep(0.5)
    return False, f"tried to start the local model server but it did not answer within {wait_s:.0f}s (see {log})"


def resources(cfg: Config) -> list[tuple[str, str, bool]]:
    """Memory-management report: each durable store and the live process, with its cap. (name, detail, within_cap)."""
    import sqlite3

    rows: list[tuple[str, str, bool]] = []

    def mb(path: Path) -> float:
        return round(path.stat().st_size / 2**20, 2) if path.exists() else 0.0

    # live process + model server
    try:
        import psutil
        me = psutil.Process().memory_info().rss / 2**30
        ol = sum(p.memory_info().rss for p in psutil.process_iter(["name"])
                 if "ollama" in (p.info["name"] or "").lower()) / 2**30
        rows.append(("Process memory", f"VoiceShell {me:.2f} GB · Ollama {ol:.2f} GB (of {psutil.virtual_memory().total/2**30:.1f} GB)", True))
    except Exception:  # noqa: BLE001
        pass
    # MemoryBank
    mdb = cfg.state_dir / "memory.db"
    n = 0
    if mdb.exists():
        try:
            c = sqlite3.connect(str(mdb))
            n = c.execute("SELECT COUNT(*) FROM mem").fetchone()[0]
            c.close()
        except sqlite3.Error:
            pass
    rows.append(("MemoryBank", f"{n} / {cfg.memory_max_rows} turns ({mb(mdb)} MB)", n <= cfg.memory_max_rows))
    # command history
    hist = cfg.state_dir / "history.jsonl"
    hl = len(hist.read_text(encoding="utf-8").splitlines()) if hist.exists() else 0
    rows.append(("Command history", f"{hl} / {cfg.history_max_lines} lines", hl <= cfg.history_max_lines))
    # trash
    tsz = sum(f.stat().st_size for f in cfg.trash_dir.rglob("*") if f.is_file()) / 2**20 if cfg.trash_dir.exists() else 0
    rows.append(("Trash (undo store)", f"{tsz:.1f} / {cfg.trash_max_mb} MB · {cfg.trash_hours:g} h retention",
                 tsz <= cfg.trash_max_mb))
    # audit log
    asz = mb(cfg.audit_path)
    rows.append(("Audit log", f"{asz} / {cfg.audit_max_mb} MB" + ("  (rotate soon)" if asz > cfg.audit_max_mb else ""),
                 asz <= cfg.audit_max_mb))
    # per-step caps
    rows.append(("Per-step output cap", f"{cfg.untrusted_cap_bytes//1000} KB to model · {cfg.output_cap_bytes//1000} KB from shell", True))
    rows.append(("Per-command limits", f"{cfg.job_memory_mb} MB RAM · {cfg.job_max_processes} processes · {cfg.exec_timeout_s:g}s timeout (Job Object)", True))
    return rows


def enforce_limits(cfg: Config) -> dict:
    """Actively trim every bounded store to its cap. Returns what was freed."""
    from .context import CommandHistory, MemoryBank
    from .executor import Executor
    freed = {}
    mdb = cfg.state_dir / "memory.db"
    if mdb.exists():
        freed["memory_turns_evicted"] = MemoryBank(mdb, cfg.memory_max_rows).evict()
    hist = cfg.state_dir / "history.jsonl"
    if hist.exists():
        freed["history_lines_trimmed"] = CommandHistory(hist, cfg.history_max_lines).trim()
    if cfg.trash_dir.exists():
        freed["trash_batches_purged"] = Executor(cfg).purge_expired()
    return freed


def doctor(cfg: Config) -> list[tuple[str, bool, str]]:
    """Every check a user needs before a live session. (name, ok, detail-or-fix)."""
    rows: list[tuple[str, bool, str]] = []

    def add(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        rows.append((name, ok, detail))

    def bash():
        from .config import find_git_bash
        return True, str(find_git_bash())

    def gate():
        from .gate.gate import verify_integrity
        return True, f"safety rules sealed ({verify_integrity()[:12]})"

    def audit():
        from .audit import verify
        ok, n, bad = verify(cfg.audit_path)
        return ok, (f"{n} records, chain valid" if ok else
                    f"chain broken at record {bad}. Fix: python -m voiceshell rotate-log --reason \"...\"")

    def server():
        ok, msg = ensure_ollama(cfg)
        return ok, msg

    def model():
        ok = model_present(cfg)
        return ok, (cfg.model if ok else f"missing. Fix: ollama pull {cfg.model}")

    def whisper():
        from faster_whisper import WhisperModel
        WhisperModel(cfg.asr_model, device="cpu", compute_type="int8", local_files_only=True)
        return True, f"{cfg.asr_model} loads from the local cache (no internet needed)"

    def mic():
        import sounddevice as sd
        d = sd.query_devices(kind="input")
        return True, d["name"]

    def tts():
        import pyttsx3
        e = pyttsx3.init()
        voices = e.getProperty("voices")
        e.stop()
        return bool(voices), f"{len(voices)} Windows voice(s)"

    def workspace():
        ok = cfg.workspace.is_dir()
        return ok, (str(cfg.workspace) if ok else "missing. Fix: python -m voiceshell demo-setup")

    for name, fn in (("Git Bash", bash), ("Safety rules", gate), ("Audit log", audit), ("Model server", server),
                     ("Planner model", model), ("Speech model", whisper), ("Microphone", mic),
                     ("Speech output", tts), ("Workspace", workspace)):
        add(name, fn)
    return rows
