"""One VoiceShell turn: utterance → envelope → plan → gate → confirm → audit → execute → sanitise → loop."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .audit import AuditLog
from .config import Config
from .context import ContextAssembler, sliding_window
from .policy import TRUST, Policy
from .envelope import Envelope, derive
from .executor import Executor, RunResult, human_bytes
from .gate.gate import Gate, Verdict
from .gate.rules import Op, Tier
from .planner import LLMPlanner, Plan, tier0
from .provenance import TurnContext
from .sanitise import sanitise
from .summary import describe_changes, is_generic, summarize

AFFIRM_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "proceed", "confirm", "confirmed",
                "approve", "approved", "correct", "right", "affirmative", "ya", "yah", "yup", "yess"}
AFFIRM_PHRASES = ("go ahead", "do it", "go for it", "sounds good", "yes please", "please do", "carry on",
                  "that's right", "thats right")
NEGATIVE_WORDS = {"no", "nope", "nah", "cancel", "stop", "dont", "don", "never", "negative", "abort",
                  "wait", "nevermind", "skip"}

PRONOUN_DELETE = re.compile(r"\b(delete|remove|erase|trash|get rid of)\s+(it|that|this|them|those|these)\b", re.I)
RECAP = re.compile(r"\b(what (did|have) you (just )?(do|done|did|find|found)|repeat (that|it|what)|say (that|it) again|"
                   r"tell me again|what was the (result|answer)|explain what you did)\b", re.I)
ACTION_CLAIM = re.compile(r"\b(deleted|removed|erased|wiped|moved|renamed|copied|created|installed|executed|"
                          r"overwrote|overwritten|modified|downloaded|uploaded)\b", re.I)
# The model echoing a context fence, or offering to run content it read. Must NOT match the gate's own
# refusal prose (which contains the word "untrusted"), so the fence words require the "<<" opener and are
# case-sensitive; only the "run this command" phrase is case-insensitive.
UNSAFE_SAY = re.compile(r"<<\s*(?:UNTRUSTED|END)\b|\bEND [0-9a-f]{8}\b|"
                        r"(?i:\b(?:execute|run) (?:this|that|the|these|those) "
                        r"(?:command|commands|script|instruction|instructions)\b)")
RUN_SCRIPT = re.compile(r"\b(run|execute|launch|start|open|install)\b.*\b(script|installer|program|\.sh|\.exe|\.bat|\.ps1|setup)\b", re.I)
HELP = re.compile(r"(what (else )?(can|could) you do|what are you (able|capable)|what (tasks|things|jobs) can you|"
                  r"(top|list|mention|name)( the)?( \d+| ten| some)? (tasks|things|features|commands|examples)|"
                  r"how (do|can) i use you|what can i (ask|say)|^\s*help\s*[.!?]?\s*$|your (features|capabilities))", re.I)
WRITE_OR_DELETE = re.compile(r"\b(delete|remove|erase|move|copy|rename|compress|create|make|clean)\b", re.I)
HELP_TEXT = ("I work with the files in your workspace folder, offline. Ten things you can ask me: "
             "1, what's taking up space in my downloads folder. "
             "2, list the files in a folder. "
             "3, read or summarise a file, like notes.txt. "
             "4, find files by type, like all the PDF files. "
             "5, count files, or lines in a file. "
             "6, make a folder, or create a file. "
             "7, move, copy or rename files. "
             "8, compress a folder into an archive. "
             "9, delete files: I'll rehearse it first, tell you exactly what will go, and ask. "
             "10, undo that, to bring deleted files back. "
             "You can also ask what I just did. I won't use the internet or run downloaded scripts.")
WHOLE_MACHINE = re.compile(r"\b(laptop|computer|pc|machine|whole (disk|drive|system)|c drive|my system)\b", re.I)
# a destination outside the workspace named as a real OS location (not the demo's own folders)
OUTSIDE_DEST = re.compile(r"\b(?:to|onto|into|in|on)\s+(?:the\s+|my\s+)?(?P<loc>desktop|documents|home folder|"
                          r"home directory|c drive|c:|recycle bin|my pc|onedrive|program files)\b", re.I)
# "find the biggest file and delete it": the referent is described in the same sentence. Let the turn run;
# provenance rule T1 then refuses the found name and asks the user to say it.
FIND_THEN_DELETE = re.compile(r"\b(find|locate|look for|search for|which|what)\b.+\b(and|then)\s+(?:also\s+)?"
                              r"(delete|remove|erase|trash|get rid of)\s+(it|them|that|those)\b", re.I)
UNDO = re.compile(r"^(please )?(undo|restore|bring back)( that| it| the last (delete|deletion|one)| what you (just )?deleted)?[.!]?$", re.I)


def is_yes(answer: str | None, strict: bool = False) -> bool:
    """Recognise a spoken affirmative robustly: 'Yes.', 'Yes yes', 'yeah go ahead', 'okay sure' all count;
    anything with a negative word ('no', 'cancel', 'wait', 'yes no') does not. Whether strict or batch, the
    real safety for a destructive command is the measured preview the user just heard, not word-counting."""
    if not answer:
        return False
    a = re.sub(r"[^a-z ]", " ", answer.lower())
    words = a.split()
    if not words:
        return False
    if any(w in NEGATIVE_WORDS for w in words):           # an explicit no anywhere cancels
        return False
    if any(p in a for p in AFFIRM_PHRASES):
        return True
    return any(w in AFFIRM_WORDS for w in words)


@dataclass
class Event:
    kind: str           # heard, envelope, plan, verdict, confirm, run, output, say, refuse, info
    text: str
    data: dict = field(default_factory=dict)


class _GraphState(TypedDict):
    t: Any
    route: str


@dataclass
class _Turn:
    """Everything one request carries through the LangGraph nodes."""
    utterance: str
    env: Envelope
    ctx: TurnContext
    res: "TurnResult"
    turn_id: str
    nonce: str
    t_start: float
    gate_note: str = ""
    resume_note: str = ""
    context_note: str = ""
    history: list = field(default_factory=list)
    reflections: list = field(default_factory=list)
    failed_cmds: dict = field(default_factory=dict)
    failures: int = 0
    gate_retries: int = 0
    step: int = 0
    cur: int = 0
    injected: bool = False
    changed: bool = False
    batch_approved: bool = False
    deterministic: str = ""
    redacted: int = 0
    final_say: str = ""
    ws_before: dict | None = None
    ws_after: dict | None = None
    plan: Any = None
    verdict: Any = None
    shadow: Any = None
    result: Any = None


@dataclass
class TurnResult:
    utterance: str
    say: str = ""
    status: str = "ok"          # ok | refused | cancelled | clarify | failed | abandoned
    steps: list[dict] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    confirmations: list[dict] = field(default_factory=list)
    envelope: str = ""
    tiers_used: list[int] = field(default_factory=list)
    first_effect_ms: float | None = None
    total_ms: float = 0.0
    events: list[Event] = field(default_factory=list)


class Agent:
    def __init__(self, cfg: Config, confirm: Callable[[str, bool], str] | None = None,
                 on_event: Callable[[Event], None] | None = None, use_llm: bool = True,
                 check_integrity: bool = True):
        self.cfg = cfg
        cfg.workspace.mkdir(parents=True, exist_ok=True)
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.gate = Gate(cfg.workspace, check_integrity=check_integrity)
        self.audit = AuditLog(cfg.audit_path)
        self.exec = Executor(cfg)
        self.llm = LLMPlanner(cfg.ollama_url, cfg.model, mode=cfg.planner_mode) if use_llm else None
        self.confirm = confirm or (lambda prompt, strict: "")      # default: silence = cancel
        self.on_event = on_event or (lambda e: None)
        self.cwd = cfg.workspace
        self.last_entities: list[str] = []
        self.last_turn: dict | None = None
        self.pending: dict | None = None     # a clarifying question waiting for the user's yes/no
        self.policy = Policy(cfg.state_dir / "policy.json")
        self.context = ContextAssembler(cfg) if use_llm else None
        self.speaker_note = ""
        self.graph = self._build_graph()

    def close(self) -> None:
        if self.context is not None:
            self.context.close()

    # ------------------------------------------------------------------
    def cwd_rel(self) -> str:
        rel = self.cwd.relative_to(self.cfg.workspace).as_posix()
        return "~" if rel == "." else "~/" + rel

    def _listing(self) -> tuple[set[str], str]:
        names = []
        try:
            for e in sorted(self.cwd.iterdir(), key=lambda p: p.name.lower())[:80]:
                names.append(e.name + ("/" if e.is_dir() else ""))
        except OSError:
            pass
        return {n.rstrip("/") for n in names}, "\n".join(names) or "(empty)"

    def _emit(self, res: TurnResult, kind: str, text: str, **data) -> None:
        ev = Event(kind, text, data)
        res.events.append(ev)
        self.on_event(ev)

    # ------------------------------------------------------------------
    def handle(self, utterance: str, asr_confidence: float = 1.0, speaker=None) -> TurnResult:
        """`speaker`: an Identity from voice.speaker (P1). None = typed by the logged-in user (no voice cap)."""
        t_start = time.perf_counter()
        res = TurnResult(utterance=utterance)
        turn_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        nonce = secrets.token_hex(4)
        self.speaker_note = speaker.describe() if speaker is not None else ""
        self._emit(res, "heard", utterance, confidence=asr_confidence, speaker=self.speaker_note)
        self.audit.append("utterance", {"turn": turn_id, "text": utterance, "asr_confidence": asr_confidence,
                                         "cwd": self.cwd_rel(), "speaker": self.speaker_note or "keyboard"})

        # A bare "yes" right after I asked a clarifying question continues THAT request. The user's own
        # earlier words (plus the referent they just confirmed) define the envelope; every gate check and
        # the measured per-command confirmation still apply.
        resume_note = ""
        pending, self.pending = self.pending, None
        if pending and is_yes(utterance, strict=False):
            self.audit.append("resume", {"turn": turn_id, "from": pending["utterance"], "as": pending["resolved"]})
            self._emit(res, "info", f"Continuing: {pending['resolved']}")
            utterance = res.utterance = pending["resolved"]
            resume_note = "The user answered yes to your clarifying question. Propose the command now."
        elif pending and re.fullmatch(r"\W*(no|nope|cancel|stop|never ?mind|don'?t)\b.*", utterance.strip(), re.I):
            return self._finish(res, "OK, I won't do that. Nothing was changed.", "cancelled", t_start)

        if RUN_SCRIPT.search(utterance):     # UC-6: forbidden class, no override path, safe alternative offered
            return self._finish(res, "I won't run a downloaded or unreviewed script or program. "
                                     "I can show you its contents first if you like: say 'read' and the file name.",
                                "refused", t_start)

        # A destination that names a real OS location outside the workspace (and is not a folder here):
        # say so plainly instead of quietly making a look-alike folder inside the workspace.
        md = OUTSIDE_DEST.search(utterance)
        if md and not (self.cwd / md.group("loc").split()[0]).exists():
            return self._finish(res, f"I can only work inside the workspace folder, so I can't reach your "
                                     f"{md.group('loc')}. Tell me a folder in the workspace instead.",
                                "refused", t_start)

        if HELP.search(utterance) and not WRITE_OR_DELETE.search(utterance):
            return self._finish(res, HELP_TEXT, "ok", t_start)

        if RECAP.search(utterance):
            return self._finish(res, self._recap(), "ok", t_start, remember=False)

        if UNDO.match(utterance.strip()):
            ok, msg = self.exec.undo()
            self.audit.append("undo", {"turn": turn_id, "ok": ok, "message": msg})
            return self._finish(res, msg, "ok" if ok else "failed", t_start)

        utterance = self._resolve_spoken_names(utterance, res)
        env: Envelope = derive(utterance, asr_confidence)
        if speaker is not None:                       # P1: the speaker's trust level caps the envelope
            env.shrink(TRUST.get(speaker.trust, TRUST["novice"]), f"trust level of {speaker.describe()}")
        res.envelope = env.describe()
        self._emit(res, "envelope", env.describe(), history=list(env.history))
        self.audit.append("envelope", {"turn": turn_id, "ops": sorted(env.ops), "scope": sorted(env.delete_scope)})

        # UC-5: an irreversible request whose object is only a pronoun → ask, never guess
        if PRONOUN_DELETE.search(utterance) and not re.search(r"[\w-]+\.\w{1,5}\b", utterance) \
                and not FIND_THEN_DELETE.search(utterance):
            pm = PRONOUN_DELETE.search(utterance)
            if self.last_entities:
                ent = self.last_entities[-1]
                self.pending = {"utterance": utterance, "resolved": f"{pm.group(1)} {ent}"}
                hint = f" Do you mean {ent}?"
            else:
                hint = " Please say the file name."
            return self._finish(res, f"I'm not sure what '{pm.group(2)}' refers to.{hint}", "clarify", t_start,
                                keep_pending=True)

        listing, _ = self._listing()
        ctx = TurnContext(utterance=utterance, listing=listing)
        t = _Turn(utterance=utterance, env=env, ctx=ctx, res=res, turn_id=turn_id, nonce=nonce, t_start=t_start,
                  gate_note=resume_note, resume_note=resume_note)
        # Deck L5: LangGraph state machine — plan → gate → confirm → execute → (reflect) → plan … → respond
        self.graph.invoke({"t": t, "route": ""}, config={"recursion_limit": 200})
        if self.context is not None:
            for lesson in t.reflections:
                self.context.memory.add("lesson", t.utterance, [], lesson)
        return t.result

    # ───────────────────────── LangGraph nodes (ReAct + Reflexion) ─────────────────────────
    def _build_graph(self):
        g = StateGraph(_GraphState)
        nodes = {"plan": self._n_plan, "gate": self._n_gate, "confirm": self._n_confirm,
                 "execute": self._n_execute, "reflect": self._n_reflect, "respond": self._n_respond}
        for name, fn in nodes.items():
            g.add_node(name, lambda s, fn=fn: {"route": fn(s["t"])})
        g.set_entry_point("plan")
        routes = {k: k for k in nodes} | {"end": END}
        for name in ("plan", "gate", "confirm", "execute", "reflect"):
            g.add_conditional_edges(name, lambda s: s["route"], routes)
        g.add_edge("respond", END)
        return g.compile()

    def _assemble_context(self, t: "_Turn") -> None:
        """Deck L3, once per request: $CWD, env, /proc-equivalent state, history, file events, MemoryBank."""
        if t.context_note or self.context is None:
            return
        trusted, untrusted = self.context.block(t.utterance, self.cwd_rel())
        if untrusted:
            t.ctx.outputs.append(untrusted)       # provenance: memory/history can never pick a delete target
        t.context_note = trusted + ("\n" + sanitise(untrusted, 1500, t.nonce, "UNTRUSTED_CONTEXT").fenced
                                    if untrusted else "")

    def _notes(self, t: "_Turn") -> str:
        notes = []
        if t.gate_note:
            notes.append(f"Safety gate: {t.gate_note}")
        if t.reflections:
            notes.append("Lessons from failed attempts in this request: " + " ".join(t.reflections))
        if t.context_note:
            notes.append(t.context_note)
        return "\n".join(notes)

    def _n_plan(self, t: "_Turn") -> str:
        res = t.res
        if t.step >= self.cfg.max_steps:
            t.env.shrink({Op.READ}, "step limit reached")
            t.result = self._finish(res, f"I stopped after {self.cfg.max_steps} steps without finishing. "
                                         "Please ask again in smaller pieces.", "abandoned", t.t_start)
            return "end"
        t.cur, t.step = t.step, t.step + 1
        plan: Plan | None = tier0(t.utterance, self.cwd, self.cfg.workspace) if t.cur == 0 else None
        if plan is None:
            if self.llm is None:
                t.result = self._finish(res, "I don't know how to do that without the language model.", "failed",
                                        t.t_start)
                return "end"
            _, listing_text = self._listing()
            lf = sanitise(listing_text, 1500, t.nonce, "UNTRUSTED_METADATA").fenced
            self._assemble_context(t)          # only when the AI actually plans (built-in commands stay instant)
            plan = self.llm.plan(t.utterance, self.cwd_rel(), lf, sliding_window(t.history), self._notes(t))
        t.plan = plan
        res.tiers_used.append(plan.tier)
        self._emit(res, "plan", plan.command or plan.say, tier=plan.tier, action=plan.action,
                   latency_ms=round(plan.latency_ms, 1))
        self.audit.append("plan", {"turn": t.turn_id, "step": t.cur, "tier": plan.tier, "action": plan.action,
                                   "command": plan.command, "latency_ms": round(plan.latency_ms, 1)})
        if plan.action == "done":
            t.final_say = plan.say or t.final_say or "Done."
            return "respond"
        if plan.action == "clarify":
            if t.resume_note:
                # the user already said yes to a question; asking again would loop forever
                t.result = self._finish(res, "I still can't tell exactly what to do, so I didn't change anything. "
                                             "Please say it precisely, for example: delete all the files in downloads.",
                                        "refused", t.t_start)
                return "end"
            self.pending = {"utterance": t.utterance, "resolved": t.utterance}
            t.result = self._finish(res, plan.say or "Can you be more specific?", "clarify", t.t_start, keep_pending=True)
            return "end"
        if plan.action == "refuse":
            if t.failed_cmds and not any(h["exit"] == 0 for h in t.history):
                # the model gave up after a failure: tell the user what actually went wrong
                t.result = self._finish(res, self._failure_say(*list(t.failed_cmds.items())[-1]), "failed", t.t_start)
            else:
                t.result = self._finish(res, plan.say or "I can't do that.", "refused", t.t_start)
            return "end"
        if plan.command in t.failed_cmds:
            # the model is repeating a command that already failed — stop and report honestly
            t.result = self._finish(res, self._failure_say(plan.command, t.failed_cmds[plan.command]), "failed",
                                    t.t_start)
            return "end"
        if any(h["command"] == plan.command and h["exit"] == 0 for h in t.history):
            t.final_say = t.final_say or "Done."      # loop guard: re-proposing a command that already succeeded
            return "respond"
        return "gate"

    def _n_gate(self, t: "_Turn") -> str:
        res, plan, env = t.res, t.plan, t.env
        verdict = self.gate.check(plan.command, self.cwd, env, t.ctx)
        t.verdict = verdict
        res.verdicts.append(verdict)
        self.audit.append("verdict", {"turn": t.turn_id, "step": t.cur, **verdict.record()})
        self._emit(res, "verdict", "ALLOWED" if verdict.allowed else "REFUSED", **verdict.record())
        if not verdict.allowed:
            if verdict.taint:
                env.shrink({Op.READ}, "provenance rule fired")
            # a delete-SCOPE refusal is a narrowing hint, safe to retry: the gate re-checks the new plan
            scope_hint = verdict.checks.get("envelope") == "FAIL" and "asked to delete only" in verdict.reasons[0]
            retriable = verdict.checks.get("parse") == "FAIL" or verdict.checks.get("rules") == "FAIL" \
                or verdict.checks.get("scope") == "FAIL" or scope_hint
            # unparseable commands carry the default FORBIDDEN tier, but a malformed command deserves one retry;
            # a genuinely forbidden verb (sudo, curl…) never does
            if retriable and t.gate_retries < 1 and plan.tier == 2 and (
                    verdict.tier != Tier.FORBIDDEN or verdict.checks.get("parse") == "FAIL"):
                t.gate_retries += 1
                t.gate_note = f"`{plan.command}` was refused: {'; '.join(verdict.reasons)}. Use a simpler allowed command."
                return "plan"
            msg = "I won't do that. " + verdict.reasons[0].removeprefix("refused: ").removeprefix("refused ")
            t1 = re.match(r"refused \(T1\): '([^']+)'", verdict.reasons[0])
            if t1:
                name = Path(t1.group(1)).name
                msg = (f"I found {t1.group(1)}, but for safety I only delete or change files you name yourself. "
                       f"If you want that, say: delete {name}.")
            if verdict.checks.get("envelope") == "FAIL" and any("ASR confidence" in h for h in env.history):
                msg = ("I didn't hear you clearly enough to delete anything, so nothing was changed. "
                       "Please say it again.")
            if verdict.checks.get("envelope") == "FAIL" and any("trust level" in h for h in env.history):
                msg = f"I won't do that: {self.speaker_note or 'your voice'} only allows {env.describe()}."
            t.result = self._finish(res, msg, "refused", t.t_start)
            return "end"
        t.gate_note = ""
        if verdict.cd_target is not None:              # cd is a session operation, not a bash process
            self.cwd = verdict.cd_target
            self.audit.append("cd", {"turn": t.turn_id, "cwd": self.cwd_rel()})
            if res.first_effect_ms is None:
                res.first_effect_ms = (time.perf_counter() - t.t_start) * 1000
            res.steps.append({"command": plan.command, "exit": 0, "output": "", "via": "session"})
            t.final_say = f"Now in {self.cwd_rel()}."
            if plan.tier == 0:
                return "respond"
            t.history.append({"command": plan.command, "exit": 0, "fenced": "(changed folder)"})
            return "plan"
        return "confirm"

    def _rehearsal_failed(self, t: "_Turn", sh) -> str:
        t.failures += 1
        so = sanitise(sh.output or "(no output)", self.cfg.context_chars, t.nonce)
        t.ctx.outputs.append(so.text)
        t.failed_cmds[t.plan.command] = so.text         # a repeat of this stops the turn honestly
        self.audit.append("rehearsal_failed", {"turn": t.turn_id, "step": t.cur, "exit": sh.exit_code})
        self._emit(t.res, "info", f"Rehearsal of `{t.plan.command}` failed, so I did not ask you to run it.")
        t.history.append({"command": t.plan.command, "exit": sh.exit_code,
                          "fenced": f"(rehearsal only - nothing changed) exit {sh.exit_code}\n{so.fenced}"})
        if t.failures > self.cfg.max_retries:
            t.result = self._finish(t.res, self._failure_say(t.plan.command, so.text), "failed", t.t_start)
            return "end"
        return "reflect"

    def _n_confirm(self, t: "_Turn") -> str:
        res, plan, verdict = t.res, t.plan, t.verdict
        t.shadow = None
        if verdict.confirm == "per_command":
            shadow = self.exec.shadow(plan.command, self.cwd, verdict.delete_targets)
            if shadow.measured and shadow.exit_code != 0:
                return self._rehearsal_failed(t, shadow)   # never offer a destructive command whose rehearsal failed
            t.shadow = shadow
            prompt = self._destructive_prompt(plan.command, shadow)
            answer = self.confirm(prompt, True)
            ok = is_yes(answer, strict=True)
            res.confirmations.append({"prompt": prompt, "answer": answer, "approved": ok, "kind": "per_command"})
            self._emit(res, "confirm", prompt, answer=answer, approved=ok)
            self.audit.append("confirm", {"turn": t.turn_id, "kind": "per_command", "prompt": prompt,
                                          "answer": answer, "approved": ok})
            if not ok:
                t.result = self._finish(res, "Cancelled. Nothing was changed.", "cancelled", t.t_start)
                return "end"
        elif verdict.confirm == "batch" and not t.batch_approved:
            # rehearse writes too, so the prompt states what WILL happen, not what the model says it does
            wshadow = self.exec.shadow(plan.command, self.cwd, [])
            if wshadow.measured and wshadow.exit_code != 0:
                return self._rehearsal_failed(t, wshadow)
            effect = (" " + describe_changes(wshadow.before, wshadow.after) + ".") if wshadow.measured else ""
            strict = wshadow.measured and bool(wshadow.deleted or wshadow.modified)
            if not strict and self.policy.auto_approves(plan.command, verdict):
                self.audit.append("confirm", {"turn": t.turn_id, "kind": "batch", "prompt": "(allow rule)",
                                              "answer": "", "approved": True, "rule": self.policy.last_rule})
                self._emit(res, "info", f"Allowed without asking by your rule: {self.policy.last_rule}")
                t.batch_approved = True
                return "execute"
            prompt = f"I'll run: {plan.command}.{effect} {'Shall I proceed?' if strict else 'Go ahead?'}"
            answer = self.confirm(prompt, strict)
            ok = is_yes(answer, strict=strict)
            res.confirmations.append({"prompt": prompt, "answer": answer, "approved": ok, "kind": "batch"})
            self._emit(res, "confirm", prompt, answer=answer, approved=ok)
            self.audit.append("confirm", {"turn": t.turn_id, "kind": "batch", "prompt": prompt,
                                          "answer": answer, "approved": ok})
            if not ok:
                t.result = self._finish(res, "Cancelled. Nothing was changed.", "cancelled", t.t_start)
                return "end"
            t.batch_approved = True
        return "execute"

    def _n_execute(self, t: "_Turn") -> str:
        res, plan, verdict, shadow, env = t.res, t.plan, t.verdict, t.shadow, t.env
        # audit first: fail-closed
        self.audit.append("execute", {"turn": t.turn_id, "step": t.cur, "command": plan.command, "cwd": self.cwd_rel(),
                                      "via": "trash" if shadow and shadow.only_deletions else "bash"})
        if res.first_effect_ms is None:
            res.first_effect_ms = (time.perf_counter() - t.t_start) * 1000
        self._emit(res, "run", plan.command)
        writes = verdict.tier != Tier.READ
        if writes and t.ws_before is None:
            t.ws_before = self.exec.snapshot()
        if shadow is not None and shadow.only_deletions:
            rr: RunResult = self.exec.trash(shadow.deleted, t.turn_id)
        else:
            rr = self.exec.execute(plan.command, self.cwd, read_only=not writes)
        if writes:
            t.ws_after = self.exec.snapshot()
            t.changed = t.changed or t.ws_after != t.ws_before
        self.audit.append("result", {"turn": t.turn_id, "step": t.cur, "exit": rr.exit_code, "via": rr.via,
                                     "ms": round(rr.duration_ms, 1), "bytes": len(rr.output)})
        if self.context is not None:
            self.context.history.add(self.cwd_rel(), plan.command, rr.exit_code)
        s = sanitise(rr.output or "(no output)", self.cfg.context_chars, t.nonce)
        if s.redacted:
            t.redacted += s.redacted
            self.audit.append("secret_redacted", {"turn": t.turn_id, "count": s.redacted, "kinds": s.redaction_kinds})
            self._emit(res, "info", f"Hid {s.redacted} secret(s) ({', '.join(sorted(set(s.redaction_kinds)))}) "
                                    "from the output — they were not shown, spoken, or logged.")
        if s.flagged:
            t.injected = True
            env.shrink({Op.READ}, f"injection signature in output: {s.hits[0]!r}")
            self.audit.append("injection_flag", {"turn": t.turn_id, "hits": s.hits[:5]})
            self._emit(res, "info", "Output contains instruction-like text; this turn is now read-only.", hits=s.hits[:3])
        t.ctx.outputs.append(s.text)
        res.steps.append({"command": plan.command, "exit": rr.exit_code, "output": s.text, "via": rr.via,
                          "ms": rr.duration_ms})
        self._emit(res, "output", s.text, exit=rr.exit_code)
        self.last_entities = re.findall(r"[\w.-]+\.\w{1,5}", plan.command)[-3:] or self.last_entities
        t.history.append({"command": plan.command, "exit": rr.exit_code, "fenced": s.fenced})

        if rr.exit_code != 0:
            t.failures += 1
            t.failed_cmds[plan.command] = s.text
            if t.failures >= 2:
                env.drop(Op.DELETE, "two failed steps")
            if t.failures > self.cfg.max_retries:
                t.result = self._finish(res, f"I tried {t.failures} times and it kept failing, so I stopped. "
                                             f"Last error: {s.text.splitlines()[-1] if s.text else 'unknown'}",
                                        "abandoned", t.t_start)
                return "end"
        if shadow is not None and shadow.only_deletions and rr.exit_code == 0:
            n = len(shadow.deleted)
            t.final_say = t.deterministic = (f"Done. Deleted {n} item{'s' if n != 1 else ''}. Say 'undo that' within "
                                             f"{self.cfg.trash_hours:g} hours to restore them.")
        if plan.tier == 0:
            if not t.deterministic:
                t.final_say = plan.summarize(rr.output) if plan.summarize else "Done."
            if rr.exit_code != 0:
                t.final_say = "That didn't work: " + (s.text.splitlines()[-1] if s.text else "unknown error")
            return "respond"
        if plan.final and rr.exit_code == 0 and verdict.tier != Tier.READ:
            return "respond"
        if t.injected:
            return "respond"         # never let the model summarise text that tried to instruct it
        # empty output never answers a question: let the planner see "(no output)" and try again
        if rr.exit_code == 0 and verdict.tier == Tier.READ and self.llm is not None and rr.output.strip():
            answered, say, ms = self.llm.answer(t.utterance, t.history)
            self.audit.append("answer_check", {"turn": t.turn_id, "step": t.cur, "answered": answered,
                                               "ms": round(ms, 1)})
            if answered and say:
                t.final_say = say
                return "respond"
        return "reflect" if rr.exit_code != 0 else "plan"

    def _n_reflect(self, t: "_Turn") -> str:
        """Reflexion: after a failure, a one-sentence lesson feeds the next plan (and the MemoryBank)."""
        if self.llm is not None and hasattr(self.llm, "reflect") and t.history:
            lesson, ms = self.llm.reflect(t.utterance, t.history)
            if lesson:
                t.reflections.append(lesson)
                self.audit.append("reflection", {"turn": t.turn_id, "step": t.cur, "lesson": lesson[:240],
                                                 "ms": round(ms, 1)})
                self._emit(t.res, "info", f"Lesson: {lesson}")
        return "plan"

    def _n_respond(self, t: "_Turn") -> str:
        res, env = t.res, t.env
        final_say = t.final_say
        res.envelope = env.describe()
        last_ok = next((s for s in reversed(res.steps) if s["exit"] == 0 and s.get("via") in ("bash", "pty")), None)
        if is_generic(final_say) and last_ok is not None:
            final_say = summarize(last_ok["command"], last_ok["output"], self.cwd)
        if t.changed and not t.deterministic:
            # speak the MEASURED change, never the model's own claim about what it did
            final_say = "Done. " + describe_changes(t.ws_before, t.ws_after) + "."
        if not t.changed and ACTION_CLAIM.search(final_say):
            # nothing was changed this turn, so a claim that something was is false by construction
            self.audit.append("false_claim_blocked", {"turn": t.turn_id, "say": final_say[:200]})
            final_say = summarize(last_ok["command"], last_ok["output"], self.cwd) if last_ok else "I didn't change anything."
        if t.injected:
            note = ("the output contains text that tries to give me instructions. I ignored it, "
                    "and the content is on screen for you to read.")
            final_say = (f"{final_say} Note: {note}" if t.changed else f"Careful: {note} Nothing was changed.")
        if WHOLE_MACHINE.search(t.utterance) and res.steps:
            final_say = f"I can only look inside your workspace folder, not the whole computer. {final_say}"
        t.result = self._finish(res, final_say or "Done.", "ok", t.t_start)
        return "end"

    def _resolve_spoken_names(self, utterance: str, res: TurnResult) -> str:
        """Speech loses punctuation in file names ("reportold.txt" for report-old.txt). Map a spoken name to a
        real file ONLY when the letters and digits match exactly and exactly one file matches — never a guess."""
        key = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731

        def fix(m):
            name = m.group(0)
            if (self.cwd / name).exists():
                return name
            hits = [p.name for p in self.cwd.iterdir() if key(p.name) == key(name)]
            if len(hits) == 1:
                self._emit(res, "info", f"I heard “{name}” and matched it to the file {hits[0]}.")
                return hits[0]
            return name
        try:
            return re.sub(r"[\w.-]+\.\w{1,5}\b", fix, utterance)
        except OSError:
            return utterance

    def _failure_say(self, command: str, error: str) -> str:
        last = next((l.strip() for l in reversed(error.splitlines()) if l.strip()), "it failed")
        say = f"That didn't work. {last[:160].rstrip('.')}."
        m = re.search(r"'([^']+)'|([\w.-]+\.\w{1,5})", last) or re.search(r"([\w.-]+\.\w{1,5})", command)
        missing = (m.group(1) or m.group(2)) if m else ""
        if missing and ("No such file" in last or "cannot" in last or "not found" in last.lower()):
            import difflib
            names = [p.name for p in self.cfg.workspace.rglob("*") if p.is_file()][:2000]
            close = difflib.get_close_matches(Path(missing).name, names, n=2, cutoff=0.7)
            if close:
                say += f" Did you mean {' or '.join(close)}?"
        return say

    def _recap(self) -> str:
        t = self.last_turn
        if not t:
            return "I haven't done anything yet in this session."
        if not t["commands"]:
            return f"You asked: {t['utterance']}. I didn't run any command. I said: {t['say']}"
        cmds = "; then ".join(t["commands"])
        return f"You asked: {t['utterance']}. I ran: {cmds}. Result: {t['say']}"

    def _destructive_prompt(self, command: str, sh) -> str:
        if sh.exit_code != 0 and sh.measured:
            return f"I rehearsed `{command}` and it failed (exit {sh.exit_code}). Run it for real anyway?"
        parts = []
        if sh.deleted:
            files = [d for d in sh.deleted if "." in d.rsplit("/", 1)[-1]] or sh.deleted
            where = sorted({d.rsplit("/", 1)[0] if "/" in d else "this folder" for d in sh.deleted})
            parts.append(f"permanently delete {len(sh.deleted)} item{'s' if len(sh.deleted) != 1 else ''}, "
                         f"{human_bytes(sh.bytes_deleted)}, in {', '.join(where[:3])}"
                         f" (e.g. {', '.join(f.rsplit('/', 1)[-1] for f in files[:3])})")
        if sh.modified:
            parts.append(f"overwrite {len(sh.modified)} existing file{'s' if len(sh.modified) != 1 else ''} "
                         f"({', '.join(m.rsplit('/', 1)[-1] for m in sh.modified[:3])})")
        if sh.created:
            parts.append(f"create {len(sh.created)} item{'s' if len(sh.created) != 1 else ''}")
        what = "; ".join(parts) or "change nothing that I can measure"
        lead = "That will" if sh.measured else "I estimate that will"
        note = f" {sh.note}" if sh.note else ""
        return f"{lead} {what}.{note} Shall I proceed?"

    def _finish(self, res: TurnResult, say: str, status: str, t_start: float, remember: bool = True,
                keep_pending: bool = False) -> TurnResult:
        if not keep_pending:
            self.pending = None
        if UNSAFE_SAY.search(say):
            # the model echoed a context fence or offered to run something it read: never speak that
            self.audit.append("unsafe_say_blocked", {"say": say[:200]})
            say = ("I saw text in your files that looks like instructions for me, and I ignored it. "
                   "Nothing was changed. What would you like me to do?")
        res.say, res.status = say, status
        if remember:
            self.last_turn = {"utterance": res.utterance, "commands": [s["command"] for s in res.steps], "say": say}
        res.total_ms = (time.perf_counter() - t_start) * 1000
        self._emit(res, "say" if status in ("ok", "clarify") else "refuse" if status == "refused" else "say", say,
                   status=status)
        self.audit.append("outcome", {"status": status, "say": say, "ms": round(res.total_ms, 1)})
        return res
