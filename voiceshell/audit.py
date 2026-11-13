"""Hash-chained, append-only, fail-closed audit log (D8)."""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

GENESIS = "0" * 64


class AuditError(RuntimeError):
    pass


def _digest(prev: str, body: dict) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256((prev + canon).encode("utf-8")).hexdigest()


if os.name == "nt":
    import msvcrt

    def _lock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)      # retries for ~10 s, then raises OSError

    def _unlock(f) -> None:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock(f) -> None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class AuditLog:
    """Safe for several VoiceShell processes at once: every append takes an exclusive lock and chains
    onto the record that is ACTUALLY last on disk, not onto a value remembered in memory."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_suffix(".lock")
        ok, n, bad = verify(self.path)
        if not ok:
            raise AuditError(f"audit log failed verification at record {bad} — refusing to start "
                             f"(see `python -m voiceshell rotate-log`)")

    def append(self, kind: str, data: dict) -> str:
        try:
            with open(self.lock_path, "a+b") as lf:
                _lock(lf)
                try:
                    seq, prev = _tail(self.path)
                    body = {"seq": seq, "ts": round(time.time(), 3), "kind": kind, "data": data, "prev": prev}
                    h = _digest(prev, body)
                    line = json.dumps({**body, "hash": h}, ensure_ascii=False, default=str)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(line + "\n")
                        f.flush()
                        os.fsync(f.fileno())
                finally:
                    _unlock(lf)
        except OSError as e:          # fail-closed: the caller must not execute
            raise AuditError(f"audit write failed: {e}") from e
        return h


def _tail(path: Path) -> tuple[int, str]:
    """(next seq, hash of the last record). The last record's own hash is re-checked."""
    if not path.exists() or path.stat().st_size == 0:
        return 0, GENESIS
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - 65536))
        last = f.read().decode("utf-8").strip().splitlines()[-1]
    rec = json.loads(last)
    h = rec.pop("hash")
    if _digest(rec["prev"], rec) != h:
        raise AuditError("last audit record does not match its hash — refusing to append")
    return rec["seq"] + 1, h


def rotate(path: Path, reason: str) -> Path:
    """Operator action for a broken chain: keep the old log byte-for-byte as an archive and start a new
    chain whose FIRST record binds the archive by SHA-256, so the archive cannot be swapped later."""
    path = Path(path)
    ok, n, bad = verify(path)
    raw = path.read_bytes()
    archive = path.with_name(f"{path.stem}-archived-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    path.rename(archive)
    AuditLog(path).append("rotated", {"archived_file": archive.name, "archived_sha256": hashlib.sha256(raw).hexdigest(),
                                      "archived_lines": raw.count(b"\n"), "chain_ok": ok, "valid_records": n,
                                      "first_bad_record": bad, "reason": reason})
    return archive


def verify(path: Path) -> tuple[bool, int, int | None]:
    """Returns (ok, records_checked, first_bad_seq)."""
    path = Path(path)
    if not path.exists():
        return True, 0, None
    prev = GENESIS
    n = 0
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            h = rec.pop("hash")
        except (ValueError, KeyError):
            return False, n, i
        if rec.get("prev") != prev or rec.get("seq") != i or _digest(prev, rec) != h:
            return False, n, i
        prev = h
        n += 1
    return True, n, None


def export_csv(path: Path, out: Path) -> int:
    """FR-64: a reviewer-friendly export (one row per record)."""
    import csv
    rows = 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seq", "time", "kind", "turn", "detail", "hash"])
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            d = r["data"]
            detail = d.get("text") or d.get("command") or d.get("prompt") or d.get("say") or json.dumps(d)[:200]
            w.writerow([r["seq"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])), r["kind"],
                        d.get("turn", ""), detail, r["hash"][:16]])
            rows += 1
    return rows
