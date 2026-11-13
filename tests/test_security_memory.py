"""Security hardening (secret redaction) and memory management (bounded stores)."""
import tempfile
from pathlib import Path

import pytest

from voiceshell.agent import Agent
from voiceshell.config import Config
from voiceshell.context import CommandHistory, MemoryBank
from voiceshell.sanitise import sanitise
from voiceshell.security import hard_cap, redact


# ── security: secret redaction ──
@pytest.mark.parametrize("text,kind", [
    ("key AKIAIOSFODNN7EXAMPLE here", "aws-key"),
    ("ghp_1234567890abcdefghij1234567890abcdef", "github-token"),
    ("sk-proj-abcdefghij1234567890ABCDEF’", "openai-key"),
    ("password = hunter2secret", "password-assignment"),
    ("postgres://user:pass1234@db:5432/x", "connection-string"),
    ("4111 1111 1111 1111", "credit-card"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r", "jwt"),
    ("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----", "private-key"),
])
def test_redaction_masks_secrets(text, kind):
    r = redact(text)
    assert r.count >= 1 and kind in r.kinds
    # the original secret characters must be gone
    for secret in ("AKIAIOSFODNN7EXAMPLE", "ghp_1234567890", "hunter2secret", "pass1234", "4111 1111"):
        if secret in text:
            assert secret not in r.text


def test_non_card_long_number_is_not_redacted():
    r = redact("order id 1234567890123 and tracking 9999999999")
    assert r.count == 0 and "1234567890123" in r.text


def test_sanitise_redacts_before_model_reply_and_audit():
    s = sanitise("config: aws_secret_access_key=wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY123")
    assert s.redacted >= 1
    assert "wJalrXUtnFEMIK7" not in s.text and "wJalrXUtnFEMIK7" not in s.fenced


def test_secret_in_a_file_is_never_spoken_or_logged(cfg):
    import json
    (cfg.workspace / "creds.txt").write_text("aws key AKIAIOSFODNN7EXAMPLE and password=topsecret9\n")
    a = Agent(cfg, use_llm=False)
    r = a.handle("read creds.txt")
    # not in the spoken reply, not in the on-screen step output, not in the audit log
    assert "AKIAIOSFODNN7EXAMPLE" not in r.say
    assert all("AKIAIOSFODNN7EXAMPLE" not in s["output"] for s in r.steps)
    assert "AKIAIOSFODNN7EXAMPLE" not in cfg.audit_path.read_text(encoding="utf-8")
    assert "topsecret9" not in cfg.audit_path.read_text(encoding="utf-8")
    assert any(json.loads(l)["kind"] == "secret_redacted" for l in cfg.audit_path.read_text(encoding="utf-8").splitlines())


def test_hard_cap_bounds_untrusted_output():
    text, cut = hard_cap("A" * 1_000_000, 100_000)
    assert cut and len(text.encode()) < 110_000


# ── memory management: bounded stores ──
def test_memorybank_is_bounded(tmp_path):
    m = MemoryBank(tmp_path / "m.db", max_rows=50)
    for i in range(300):
        m.add("turn", f"request {i}", [f"cmd{i}"], f"did {i}")
    assert m.count() <= 50 + 50          # bounded in-session (cap + eviction interval)
    assert m.evict() == 0 or m.count() == 50
    assert m.count() == 50               # explicit enforce → exact cap


def test_memorybank_keeps_the_most_recent(tmp_path):
    m = MemoryBank(tmp_path / "m.db", max_rows=20)
    for i in range(100):
        m.add("turn", f"zebra{i} request", [f"cmd{i}"], f"did {i}")
    m.evict()
    assert m.count() == 20                            # bounded to the cap
    assert m.search("zebra99") and "99" in m.search("zebra99")[0]["utterance"]   # newest retained
    assert not m.search("zebra0")                     # a term unique to an evicted old row is gone


def test_history_is_bounded(tmp_path):
    h = CommandHistory(tmp_path / "h.jsonl", keep=30)
    for i in range(300):
        h.add("~", f"ls {i}", 0)
    assert h.trim() >= 0
    assert len((tmp_path / "h.jsonl").read_text().splitlines()) == 30


def test_trash_size_cap(tmp_path):
    from voiceshell.executor import Executor
    cfg = Config(workspace=tmp_path / "ws", state_dir=tmp_path / "st", trash_max_mb=1)
    cfg.workspace.mkdir(parents=True)
    ex = Executor(cfg)
    # three 0.5 MB batches → 1.5 MB, cap 1 MB → oldest purged
    import time
    for b in range(3):
        f = cfg.workspace / f"big{b}.bin"
        f.write_bytes(b"x" * (512 * 1024))
        ex.trash([f"big{b}.bin"], f"batch{b}")
        time.sleep(0.01)
    ex.purge_expired()
    assert ex.trash_size_mb() <= 1.2      # kept within the cap (+ manifest overhead)


def test_resources_report_runs(cfg):
    from voiceshell.runtime import enforce_limits, resources
    Agent(cfg, use_llm=False).handle("list the files")
    enforce_limits(cfg)
    rows = resources(cfg)
    names = {r[0] for r in rows}
    assert {"MemoryBank", "Command history", "Trash (undo store)", "Audit log"} <= names
    assert all(isinstance(r[2], bool) for r in rows)
