"""Deck slide 9 — Policy framework.

P1 Identity & trust : speaker identity → trust level (Novice / Operator / Admin) caps what a request may do.
P2 Permission model : read = no confirmation · write = batch confirmation · destructive = per-command gate (gate.py).
P4 Governance       : user-configurable allow rules + a recorded policy review cycle.

Allow rules can only skip the question for plain WRITE commands (create/copy/move/archive) whose rehearsal shows
nothing deleted or overwritten. They can never skip a DESTRUCTIVE confirmation, never permit a FORBIDDEN command,
and never widen the capability envelope.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from .gate.parser import Unanalysable, parse
from .gate.rules import Op, Tier

TRUST = {
    "novice": {Op.READ},
    "operator": {Op.READ, Op.WRITE},
    "admin": {Op.READ, Op.WRITE, Op.DELETE},
}

DEFAULT = {
    "allow_rules": [],            # e.g. {"verbs": ["mkdir", "touch"], "note": "creating folders is fine"}
    "unknown_voice_trust": "novice",
    "review_every_days": 30,
    "last_review": None,
}

ALLOWABLE_VERBS = {"mkdir", "touch", "cp", "mv", "tar", "zip", "gzip", "tee"}


class Policy:
    def __init__(self, path: Path):
        self.path = path
        self.data = copy.deepcopy(DEFAULT)        # deep copy: never share the default rule list between policies
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text(encoding="utf-8")))
            except ValueError:
                pass                       # a broken policy file means: no allow rules (fail-safe)
        self.last_rule = ""

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def rules(self) -> list[dict]:
        out = []
        for r in self.data.get("allow_rules", []):
            verbs = {v for v in r.get("verbs", []) if v in ALLOWABLE_VERBS}   # anything else is ignored
            if verbs:
                out.append({**r, "verbs": sorted(verbs)})
        return out

    def auto_approves(self, command: str, verdict) -> bool:
        """True only for a WRITE (not destructive) command made solely of verbs an allow rule lists."""
        if verdict.tier != Tier.WRITE or Op.DELETE in verdict.ops:
            return False
        try:
            verbs = {c.verb for c in parse(command).commands}
        except Unanalysable:
            return False
        for r in self.rules():
            if verbs <= set(r["verbs"]):
                self.last_rule = r.get("note") or "allow " + ", ".join(r["verbs"])
                return True
        return False

    def add_rule(self, verbs: list[str], note: str = "") -> list[str]:
        ok = [v for v in verbs if v in ALLOWABLE_VERBS]
        if ok:
            self.data.setdefault("allow_rules", []).append({"verbs": ok, "note": note or "allow " + ", ".join(ok)})
            self.save()
        return ok

    def review_due(self) -> bool:
        last = self.data.get("last_review")
        return last is None or time.time() - last > self.data.get("review_every_days", 30) * 86400

    def mark_reviewed(self) -> None:
        self.data["last_review"] = time.time()
        self.save()
