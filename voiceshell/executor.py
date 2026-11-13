"""Jailed execution in Git Bash, shadow rehearsal, and reversible deletes.

W1 has no kernel sandbox (Windows). Confinement here is: workspace cwd, HOME = workspace,
minimal PATH and environment, no stdin, timeout, output cap — and above all the gate,
which never lets a command name a path outside the workspace or a network-capable verb.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, find_git_bash


def to_posix(p: Path) -> str:
    s = str(Path(p).resolve())
    m = re.match(r"^([A-Za-z]):[\\/]?(.*)$", s)
    if m:
        return "/" + m.group(1).lower() + "/" + m.group(2).replace("\\", "/")
    return s.replace("\\", "/")


class _Job:
    """Windows Job Object around every command (the deck's resource-limit layer, cgroups on Linux):
    per-process memory cap, a cap on how many processes the command may spawn, and the whole process
    tree dies together on timeout, Ctrl+C or when VoiceShell exits."""

    @staticmethod
    def available() -> bool:
        if os.name != "nt":
            return False
        try:
            import win32job  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self, cfg: Config):
        import win32job
        self.win32job = win32job
        self.handle = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] = (win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
                                                       win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY |
                                                       win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
        info["BasicLimitInformation"]["ActiveProcessLimit"] = cfg.job_max_processes
        info["ProcessMemoryLimit"] = cfg.job_memory_mb * 1024 * 1024
        win32job.SetInformationJobObject(self.handle, win32job.JobObjectExtendedLimitInformation, info)

    def adopt(self, proc: subprocess.Popen) -> None:
        import psutil
        self.win32job.AssignProcessToJobObject(self.handle, int(proc._handle))
        psutil.Process(proc.pid).resume()          # started suspended, so nothing ran outside the job

    def adopt_pid(self, pid: int) -> None:
        """For processes started by another library (ConPTY): join the job right after start."""
        import win32api
        import win32con
        h = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
        try:
            self.win32job.AssignProcessToJobObject(self.handle, h)
        finally:
            win32api.CloseHandle(h)

    def kill(self) -> None:
        self.win32job.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        try:
            self.handle.Close()
        except Exception:  # noqa: BLE001
            pass


@dataclass
class RunResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timed_out: bool = False
    via: str = "bash"           # bash | trash

    @property
    def output(self) -> str:
        return (self.stdout + ("\n" + self.stderr if self.stderr.strip() else "")).strip()


@dataclass
class ShadowResult:
    deleted: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    bytes_deleted: int = 0
    exit_code: int = 0
    measured: bool = True      # False = enumeration estimate (too large to rehearse)
    note: str = ""
    output: str = ""
    before: dict = field(default_factory=dict)   # rehearsal snapshots (relative path → size, mtime, is_dir)
    after: dict = field(default_factory=dict)

    @property
    def only_deletions(self) -> bool:
        return self.measured and self.exit_code == 0 and bool(self.deleted) and not self.created and not self.modified


from .sanitise import _ANSI as _TERMCODES  # noqa: E402  (same terminal-code pattern as the sanitiser)


def _visible(s: str) -> bool:
    """Is there any real text once terminal control codes are removed?"""
    return bool(_TERMCODES.sub("", s).strip())


def human_bytes(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class Executor:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.bash = find_git_bash()
        git_root = self.bash.parent.parent
        self.path_env = os.pathsep.join(str(git_root / d) for d in ("usr/bin", "mingw64/bin", "bin"))
        (cfg.state_dir / "tmp").mkdir(parents=True, exist_ok=True)
        cfg.trash_dir.mkdir(parents=True, exist_ok=True)
        self.purge_expired()

    def _env(self, home: Path) -> dict:
        keep = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "COMSPEC") if k in os.environ}
        tmp = str(self.cfg.state_dir / "tmp")
        return {**keep, "PATH": self.path_env, "HOME": to_posix(home), "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8", "TERM": "dumb", "TMP": tmp, "TEMP": tmp, "TMPDIR": to_posix(Path(tmp)),
                "MSYS": "winsymlinks:native", "CHERE_INVOKING": "1"}

    def run(self, command: str, cwd: Path, home: Path | None = None, read_only: bool = False) -> RunResult:
        home = home or self.cfg.workspace
        t0 = time.perf_counter()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        job = _Job(self.cfg) if _Job.available() else None
        if job:
            flags |= 0x00000004                     # CREATE_SUSPENDED: join the job before running anything
        proc = subprocess.Popen([str(self.bash), "--noprofile", "--norc", "-c", command], cwd=str(cwd),
                                env=self._env(home), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=flags)
        if job:
            job.adopt(proc)
        timed_out = False
        try:
            out, err = proc.communicate(timeout=self.cfg.exec_timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            job.kill() if job else subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            out, err = proc.communicate()
        except KeyboardInterrupt:          # user cancelled: stop the command too, don't leave it running
            job.kill() if job else subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
            raise
        finally:
            if job:
                job.close()
        cap = self.cfg.output_cap_bytes
        dec = lambda b: b[:cap].decode("utf-8", errors="replace")  # noqa: E731
        code = -1 if timed_out else proc.returncode
        if code == 0 and not out.strip() and err.strip() and read_only:
            # a pipeline like `find … | sort` exits 0 even when find failed: an error and no result is a failure
            code = 1
        return RunResult(command, code, dec(out), dec(err), (time.perf_counter() - t0) * 1000, timed_out)

    def run_pty(self, command: str, cwd: Path, home: Path | None = None, read_only: bool = False) -> RunResult:
        """Deck L6 'PTY (openpty) · GNU Bash 5.x · ANSI strip': the command runs attached to a pseudo-terminal
        (Windows ConPTY), inside the same Job Object limits. stdout is the terminal; stderr goes to a side file so
        failures can still be told apart. ANSI/terminal codes are stripped later by the sanitiser."""
        import threading

        from winpty import PtyProcess
        home = home or self.cfg.workspace
        t0 = time.perf_counter()
        fd, err_name = tempfile.mkstemp(prefix="vs-err-", dir=self.cfg.state_dir / "tmp")
        os.close(fd)
        err_file = Path(err_name)
        env = {**self._env(home), "TERM": "xterm", "VS_CMD": command, "VS_ERR": to_posix(err_file)}
        # the wrapper only routes stderr; VS_CMD is exactly the command the gate approved
        proc = PtyProcess.spawn([str(self.bash), "--noprofile", "--norc", "-c", 'exec 2>"$VS_ERR"; eval "$VS_CMD"'],
                                cwd=str(cwd), env=env, dimensions=(50, 250))
        job = _Job(self.cfg) if _Job.available() else None
        if job:
            job.adopt_pid(proc.pid)
        chunks: list[str] = []

        def reader():
            while True:
                try:
                    chunks.append(proc.read(65536))
                except (EOFError, OSError):
                    return
        th = threading.Thread(target=reader, daemon=True)
        th.start()
        timed_out = False
        deadline = time.perf_counter() + self.cfg.exec_timeout_s
        try:
            # ConPTY only reports end-of-output once the console is closed, so watch the PROCESS instead
            while proc.isalive() and time.perf_counter() < deadline:
                time.sleep(0.01)
            if proc.isalive():
                timed_out = True
                job.kill() if job else proc.terminate(force=True)
            else:                                   # let the reader drain what's left, then close the console
                last, quiet_since = len(chunks), time.perf_counter()
                while time.perf_counter() - quiet_since < 0.12 and time.perf_counter() < deadline + 1:
                    time.sleep(0.02)
                    if len(chunks) != last:
                        last, quiet_since = len(chunks), time.perf_counter()
            code = -1 if timed_out else (proc.exitstatus if proc.exitstatus is not None else 0)
            try:
                proc.close(force=True)
            except Exception:  # noqa: BLE001
                pass
            th.join(1)
        except KeyboardInterrupt:
            job.kill() if job else proc.terminate(force=True)
            raise
        finally:
            if job:
                job.close()
        cap = self.cfg.output_cap_bytes
        out = "".join(chunks).replace("\r\n", "\n")[:cap]
        err = err_file.read_text(encoding="utf-8", errors="replace")[:cap] if err_file.exists() else ""
        try:
            err_file.unlink(missing_ok=True)
        except OSError:
            pass
        if code == 0 and not _visible(out) and err.strip() and read_only:
            code = 1
        return RunResult(command, code, out, err, (time.perf_counter() - t0) * 1000, timed_out, via="pty")

    def execute(self, command: str, cwd: Path, read_only: bool = False) -> RunResult:
        """Real (non-rehearsal) execution: PTY by default (deck L6), plain pipes if ConPTY is unavailable."""
        if self.cfg.exec_mode == "pty" and os.name == "nt":
            try:
                import winpty  # noqa: F401
                return self.run_pty(command, cwd, read_only=read_only)
            except ImportError:
                pass
        return self.run(command, cwd, read_only=read_only)

    def snapshot(self) -> dict[str, tuple[int, int, bool]]:
        return self._snapshot(self.cfg.workspace)

    # ───────────── shadow execution (02X §8.2, copy instead of overlayfs) ─────────────
    def _snapshot(self, root: Path) -> dict[str, tuple[int, int, bool]]:
        snap = {}
        for dirpath, dirnames, filenames in os.walk(root):
            for d in dirnames:
                p = Path(dirpath) / d
                snap[p.relative_to(root).as_posix()] = (0, 0, True)
            for f in filenames:
                p = Path(dirpath) / f
                try:
                    st = p.lstat()
                    snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, False)
                except OSError:
                    pass
        return snap

    def _workspace_size(self) -> tuple[int, int]:
        total = count = 0
        for dirpath, _, files in os.walk(self.cfg.workspace):
            for f in files:
                count += 1
                try:
                    total += (Path(dirpath) / f).lstat().st_size
                except OSError:
                    pass
        return total, count

    def shadow(self, command: str, cwd: Path, delete_targets: list[str]) -> ShadowResult:
        ws = self.cfg.workspace
        ws_forms = {str(ws).lower(), to_posix(ws).lower(), str(ws).replace("\\", "/").lower()}
        size, count = self._workspace_size()
        too_big = size > self.cfg.shadow_max_bytes or count > self.cfg.shadow_max_files
        absolute = any(f in command.lower() for f in ws_forms)
        if too_big or absolute:
            return self._estimate(cwd, delete_targets,
                                  "too large for me to rehearse safely" if too_big else "it uses an absolute path")
        tmp = Path(tempfile.mkdtemp(prefix="vs-shadow-", dir=self.cfg.state_dir / "tmp"))
        try:
            copy = tmp / "ws"
            shutil.copytree(ws, copy, symlinks=True)
            before = self._snapshot(copy)
            res = self.run(command, copy / cwd.relative_to(ws), home=copy)
            after = self._snapshot(copy)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sr = ShadowResult(exit_code=res.exit_code, output=res.output, before=before, after=after)
        for k, v in before.items():
            if k not in after:
                sr.deleted.append(k)
                sr.bytes_deleted += v[0]
            elif not v[2] and after[k][:2] != v[:2]:
                sr.modified.append(k)
        sr.created = [k for k in after if k not in before]
        return sr

    def _estimate(self, cwd: Path, targets: list[str], why: str) -> ShadowResult:
        import glob
        sr = ShadowResult(measured=False, note=f"This is an estimate: {why}.")
        for t in targets:
            for m in glob.glob(str(cwd / t), recursive=True) or ([str(cwd / t)] if (cwd / t).exists() else []):
                p = Path(m)
                files = [p] if p.is_file() else [Path(d) / f for d, _, fs in os.walk(p) for f in fs]
                for f in files:
                    sr.deleted.append(f.relative_to(self.cfg.workspace).as_posix())
                    try:
                        sr.bytes_deleted += f.stat().st_size
                    except OSError:
                        pass
        return sr

    # ───────────── reversible delete (02X §8.3, D7) ─────────────
    def trash(self, deleted: list[str], turn_id: str) -> RunResult:
        t0 = time.perf_counter()
        ws = self.cfg.workspace
        tops = []
        for p in sorted(deleted, key=lambda s: s.count("/")):
            if not any(p == t or p.startswith(t + "/") for t in tops):
                tops.append(p)
        dest_root = self.cfg.trash_dir / turn_id
        moved = []
        for rel in tops:
            src = ws / rel
            if not src.exists() and not src.is_symlink():
                continue
            dst = dest_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(rel)
        (dest_root / ".manifest.json").write_text(json.dumps({"moved": moved, "ts": time.time(),
                                                              "workspace": str(ws)}))
        return RunResult(f"trash {len(moved)} item(s)", 0, "\n".join(f"moved to trash: {m}" for m in moved), "",
                         (time.perf_counter() - t0) * 1000, via="trash")

    def _batches(self) -> list[tuple[Path, dict]]:
        out = []
        for d in self.cfg.trash_dir.iterdir():
            m = d / ".manifest.json"
            if m.exists():
                try:
                    out.append((d, json.loads(m.read_text())))
                except ValueError:
                    continue
        return sorted(out, key=lambda x: x[1]["ts"])

    def purge_expired(self) -> int:
        """Design D7 + memory management: deleted items stay recoverable for `trash_hours`, then are removed;
        additionally, if the trash exceeds `trash_max_mb`, the OLDEST batches are purged until it fits, so the
        reversible store can never grow without bound."""
        cutoff = time.time() - self.cfg.trash_hours * 3600
        n = 0
        batches = self._batches()
        for d, m in batches:
            if m["ts"] < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                n += 1
        cap = self.cfg.trash_max_mb * 1024 * 1024

        def dir_size(p: Path) -> int:
            return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
        live = [(d, m) for d, m in self._batches()]
        total = sum(dir_size(d) for d, _ in live)
        for d, _ in sorted(live, key=lambda x: x[1]["ts"]):     # oldest first
            if total <= cap:
                break
            total -= dir_size(d)
            shutil.rmtree(d, ignore_errors=True)
            n += 1
        return n

    def trash_size_mb(self) -> float:
        total = sum(f.stat().st_size for f in self.cfg.trash_dir.rglob("*") if f.is_file())
        return round(total / 2**20, 1)

    def undo(self) -> tuple[bool, str]:
        self.purge_expired()
        batches = [d for d, m in self._batches()
                   if os.path.normcase(m.get("workspace", str(self.cfg.workspace))) == os.path.normcase(str(self.cfg.workspace))]
        if not batches:
            return False, f"There is nothing to undo from the last {self.cfg.trash_hours:g} hours."
        last = batches[-1]
        moved = json.loads((last / ".manifest.json").read_text())["moved"]
        restored, skipped = [], []
        for rel in moved:
            dst = self.cfg.workspace / rel
            if dst.exists():
                skipped.append(rel)
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(last / rel), str(dst))
            restored.append(rel)
        shutil.rmtree(last, ignore_errors=True)
        msg = f"Restored {len(restored)} item{'s' if len(restored) != 1 else ''}."
        if skipped:
            msg += f" Skipped {len(skipped)} because something with that name exists now."
        return True, msg
