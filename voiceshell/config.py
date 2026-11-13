"""Static configuration for VoiceShell W1."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def find_git_bash() -> Path:
    """Locate Git Bash. Never C:\\Windows\\System32\\bash.exe (that is the WSL launcher)."""
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Git" / "bin" / "bash.exe",
    ]
    git = shutil.which("git")
    if git:
        candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError("Git Bash not found. Install Git for Windows.")


@dataclass
class Config:
    workspace: Path = PROJECT_ROOT / "workspace"
    state_dir: Path = PROJECT_ROOT / ".voiceshell"
    # Deck slide 6: "Llama 3 local". Override with VOICESHELL_MODEL (e.g. qwen2.5-coder:3b).
    model: str = os.environ.get("VOICESHELL_MODEL", "llama3.2:3b")
    ollama_url: str = "http://127.0.0.1:11434"
    asr_model: str = "small.en"
    # Deck slide 8, L4 "LLM function calling". "json" = schema-constrained replies instead.
    planner_mode: str = os.environ.get("VOICESHELL_PLANNER", "tools")
    max_steps: int = 5
    max_retries: int = 2
    exec_timeout_s: float = 20.0
    output_cap_bytes: int = 1_000_000
    context_chars: int = 2000
    shadow_max_bytes: int = 200 * 1024 * 1024
    shadow_max_files: int = 5000
    speak: bool = False
    trash_hours: float = 24.0
    # Deck L6 "PTY (openpty)". Built and tested ("pty" = Windows ConPTY), but NOT the default on Windows:
    # measured 4.3 s per command (vs 0.1 s) and ConPTY re-renders a screen, so it LOST 40% of a 30,000-line
    # output. Linux openpty has neither problem. Default here: plain pipes (byte-exact output).
    exec_mode: str = os.environ.get("VOICESHELL_EXEC", "pipes")
    job_memory_mb: int = 1024        # per-process memory cap for executed commands (Job Object)
    job_max_processes: int = 64      # how many processes one command may run at once
    wake_phrase: str = "voice shell"
    # ── memory management: every durable store is bounded so nothing grows without limit ──
    memory_max_rows: int = 2000      # MemoryBank: keep at most this many past turns (oldest evicted)
    history_max_lines: int = 2000    # shell-history store line cap
    trash_max_mb: int = 500          # total trash size cap; oldest batches purged past it
    audit_max_mb: int = 50           # audit log size at which a size-rotation is recommended
    untrusted_cap_bytes: int = 200_000  # hard cap on untrusted output admitted per step (security.hard_cap)
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace).resolve()
        self.state_dir = Path(self.state_dir).resolve()

    @property
    def audit_path(self) -> Path:
        return self.state_dir / "audit.jsonl"

    @property
    def trash_dir(self) -> Path:
        return self.state_dir / "trash"
