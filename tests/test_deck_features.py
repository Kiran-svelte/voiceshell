"""Tests for the features added to match the original VoiceShell deck (slides 4, 6, 8, 9)."""
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from voiceshell.agent import Agent, OUTSIDE_DEST
from voiceshell.executor import Executor


# ── L5: LangGraph orchestration + ReAct + Reflexion ──
def test_turn_loop_is_a_langgraph_state_graph(cfg):
    a = Agent(cfg, use_llm=False)
    g = a.graph.get_graph()
    assert {"plan", "gate", "confirm", "execute", "reflect", "respond"} <= set(g.nodes)


class _ReflectingLLM:
    """Fails once, reflects, and the lesson must reach the next plan."""
    def __init__(self):
        self.notes = []

    def plan(self, utterance, cwd_rel, listing, history, note=""):
        from voiceshell.planner import Plan
        self.notes.append(note)
        if not history:
            return Plan("run", "cat report.txt", "", tier=2)
        if history[-1]["exit"] != 0:
            return Plan("run", "cat report-old.txt", "", tier=2)
        return Plan("done", "", "It is an old draft of the annual report.", tier=2)

    def answer(self, *a):
        return False, "", 0.0

    def reflect(self, utterance, history):
        return "report.txt does not exist; the file is report-old.txt.", 1.0


def test_reflexion_lesson_feeds_the_next_attempt(cfg):
    a = Agent(cfg, use_llm=False)
    a.llm = _ReflectingLLM()
    r = a.handle("read the report file")
    assert any("report-old.txt" in n and "Lessons" in n for n in a.llm.notes[1:])
    assert r.status == "ok" and any("annual" in s["output"] for s in r.steps)


# ── L3: context assembly ──
def test_memorybank_retrieves_related_turns(tmp_path):
    from voiceshell.context import MemoryBank
    m = MemoryBank(tmp_path / "m.db")
    m.add("turn", "delete the log files in logs", ["rm logs/*.log"], "Deleted 4 items.")
    m.add("turn", "what's the weather", [], "I can only work with files.")
    hits = m.search("remove logs again")
    assert hits and hits[0]["utterance"].startswith("delete the log files")


def test_sliding_window_keeps_recent_steps():
    from voiceshell.context import sliding_window
    h = [{"command": f"c{i}", "exit": 0, "fenced": f"out{i}"} for i in range(7)]
    w = sliding_window(h, keep=4)
    assert len(w) == 5 and w[0]["command"] == "c0; c1; c2" and w[-1]["command"] == "c6"


def test_context_cannot_choose_a_delete_target(cfg):
    """A file name that only appears in history/memory context must not be deletable (provenance T1)."""
    from voiceshell.envelope import derive
    from voiceshell.gate.gate import Gate
    from voiceshell.provenance import TurnContext
    ctx = TurnContext("clean up the old stuff", outputs=["related earlier request: ran rm notes.txt"])
    v = Gate(cfg.workspace).check("rm notes.txt", cfg.workspace, derive(ctx.utterance), ctx)
    assert not v.allowed and "T1" in v.reasons[0]


def test_file_events_are_seen(cfg):
    from voiceshell.context import FileEvents
    ev = FileEvents(cfg.workspace)
    (cfg.workspace / "new-note.txt").write_text("x")
    for _ in range(40):
        if any("new-note.txt" in e for e in ev.recent()):
            break
        time.sleep(0.05)
    ev.stop()
    assert any("new-note.txt" in e for e in ev.recent())


# ── L6: Job Object resource limits (cgroups equivalent) and PTY mode ──
def test_job_object_kills_the_whole_tree_on_timeout(cfg):
    cfg.exec_timeout_s = 2
    r = Executor(cfg).run("sleep 30 & sleep 30; echo never", cfg.workspace)
    assert r.timed_out and r.duration_ms < 6000


def test_job_object_caps_process_count(cfg):
    cfg.job_max_processes = 4
    r = Executor(cfg).run("for i in 1 2 3 4 5 6 7 8; do sleep 1 & done; wait; echo done", cfg.workspace)
    assert r.exit_code != 0


def test_pty_mode_runs_on_a_terminal_and_separates_errors(cfg):
    ex = Executor(cfg)
    r = ex.run_pty("tty", cfg.workspace)
    assert r.exit_code == 0 and "/dev/cons" in r.stdout
    r = ex.run_pty("cat nope.txt", cfg.workspace, read_only=True)
    assert r.exit_code != 0 and "No such file" in r.stderr


# ── L1: Silero VAD + noise suppression ──
def test_silero_vad_ignores_noise():
    from voiceshell.voice.vad import CHUNK, StreamingVAD
    v = StreamingVAD()
    noise = (np.random.default_rng(1).standard_normal(16000 * 2) * 0.02).astype("float32")
    probs = [v.prob(noise[i:i + CHUNK]) for i in range(0, len(noise) - CHUNK, CHUNK)]
    assert max(probs) < 0.5


# ── L7: CLI phoneme lexicon ──
@pytest.mark.parametrize("text,spoken", [
    ("notes.txt", "notes dot T X T"),
    ("331.1 KB", "331.1 kilobytes"),
    ("rm -rf ~/tmp", "R M dash R F home slash tmp"),
    ("mv *.pdf reports/", "move star dot P D F reports/"),
    ("I'll check", "I'll check"),
])
def test_lexicon(text, spoken):
    from voiceshell.voice.lexicon import speakable
    assert speakable(text) == spoken


# ── P1: speaker identity → trust level ──
@dataclass
class _H:
    text: str
    confidence: float = 0.95


@pytest.fixture(scope="module")
def voices(tmp_path_factory):
    from voiceshell.voice.tts import save_wav
    d = tmp_path_factory.mktemp("voices")
    lines = ["List the files in the logs folder and tell me which is biggest.",
             "Make a folder called reports and move the PDF files into it.",
             "Delete all the temporary files in the downloads folder please."]
    return {"owner": [save_wav(t, d / f"o{i}.wav", voice_index=0) for i, t in enumerate(lines)],
            "other": [save_wav(t, d / f"x{i}.wav", voice_index=1) for i, t in enumerate(lines)]}


def test_speaker_enrol_and_identify(tmp_path, voices):
    from voiceshell.voice.speaker import SpeakerID
    sid = SpeakerID(tmp_path / "speakers.json")
    sid.enrol("Owner", "admin", voices["owner"][:2])
    me, stranger = sid.identify(voices["owner"][2]), sid.identify(voices["other"][2])
    assert me.name == "Owner" and me.trust == "admin"
    assert stranger.name is None and stranger.trust == "novice"
    stored = json.loads((tmp_path / "speakers.json").read_text())
    assert set(stored["Owner"]) == {"trust", "embedding", "enrolled", "samples"}      # no audio kept


def test_unknown_voice_is_read_only(cfg):
    from voiceshell.voice.speaker import Identity
    a = Agent(cfg, confirm=lambda p, s: "yes", use_llm=False)
    r = a.handle("make a folder called reports", speaker=Identity(None, "novice", 0.4))
    assert r.status == "refused" and not (cfg.workspace / "reports").exists()
    r = a.handle("make a folder called reports", speaker=Identity("Owner", "admin", 0.93))
    assert (cfg.workspace / "reports").is_dir()


def test_bystander_cannot_say_yes_for_you(cfg, voices):
    """Hands-free with speaker ID: the owner asks, a different voice answers 'yes' → treated as no."""
    from voiceshell.voice.handsfree import FileSource, HandsFree
    from voiceshell.voice.speaker import SpeakerID
    sid = SpeakerID(cfg.state_dir / "speakers.json")
    sid.enrol("Owner", "admin", voices["owner"][:2])
    texts = {str(voices["owner"][2]): "VoiceShell, make a folder called reports",
             str(voices["other"][0]): "yes"}

    class ASR:
        def transcribe(self, item):
            return _H(texts[str(item)])
    hf = HandsFree(asr=ASR(), source=FileSource([voices["owner"][2], voices["other"][0]]), speak=lambda s: None,
                   identify=sid.identify)
    hf.run(Agent(cfg, confirm=hf.confirm, use_llm=False))
    assert not (cfg.workspace / "reports").exists()
    assert any(e.get("rejected_voice") for e in hf.log)


# ── P4: allow rules ──
def test_allow_rules_skip_only_plain_writes(cfg):
    a = Agent(cfg, confirm=lambda p, s: "", use_llm=False)          # silence: would cancel if asked
    a.policy.add_rule(["mkdir"], "folders are fine")
    a.policy.add_rule(["rm"], "nope")                               # silently rejected: never skippable
    r = a.handle("make a folder called reports")
    assert (cfg.workspace / "reports").is_dir() and not r.confirmations
    r = a.handle("delete all the log files in the logs folder")
    assert len(list((cfg.workspace / "logs").glob("*.log"))) == 4      # delete still asked → silence → kept
    assert [r["verbs"] for r in a.policy.rules()] == [["mkdir"]]


def test_policies_do_not_share_rules(tmp_path):
    """Regression: a shallow-copied default made one policy's allow rule appear in every other policy."""
    from voiceshell.policy import Policy
    Policy(tmp_path / "a.json").add_rule(["mkdir"])
    assert Policy(tmp_path / "b.json").rules() == []


def test_outside_destination_is_declined_not_contained(cfg):
    """'copy to the desktop' must be declined, not quietly made into a workspace look-alike folder."""
    a = Agent(cfg, confirm=lambda p, s: "yes", use_llm=False)
    r = a.handle("copy notes.txt to the desktop")
    assert r.status == "refused" and "workspace" in r.say.lower()
    assert not (cfg.workspace / "Desktop").exists()
    # a real workspace folder named in the same shape is NOT blocked by this guard
    a.handle("make a folder called downloads2")  # ensure no crash path
    assert OUTSIDE_DEST.search("move x to the downloads folder") is None


def test_affirmative_parsing_robust():
    """Regression: 'Yes. Yes' (seen in a real voice session) was wrongly treated as cancel."""
    from voiceshell.agent import is_yes
    for a in ("Yes. Yes", "yes", "yeah go ahead", "okay sure", "do it", "proceed", "yep yep", "yes please"):
        assert is_yes(a), a
    for a in ("no", "yes no", "wait no", "cancel", "maybe", "uh", "", "nope"):
        assert not is_yes(a), a


def test_voice_create_confirmed_actually_runs(cfg):
    """The 'touch kirani' / 'Yes. Yes' → Cancelled bug: an affirmative must execute the write."""
    answers = iter(["Yes. Yes"])
    a = Agent(cfg, confirm=lambda p, s: next(answers, ""), use_llm=False)
    # a Tier 0 write (mkdir) that asks a batch confirmation
    r = a.handle("make a folder called kirani")
    assert (cfg.workspace / "kirani").is_dir() and r.status == "ok"


def test_single_file_delete_template_extracts_just_the_filename(cfg):
    from voiceshell.planner import tier0
    (cfg.workspace / "status.txt").write_text("x")
    for u in ["delete a file name called status.txt", "delete the file called status.txt", "delete status.txt"]:
        p = tier0(u, cfg.workspace, cfg.workspace)
        assert p is not None and p.command == "rm -- 'status.txt'", (u, p and p.command)


def test_hidden_files_is_handled_exactly_not_guessed(cfg):
    """'delete the hidden files' must target only dot-files, never be misread as 'all files'."""
    from voiceshell.planner import tier0
    p = tier0("delete the hidden files", cfg.workspace, cfg.workspace)
    assert p is not None and "-name '.*'" in p.command and "'*.*'" not in p.command
    # the demo has no dot-files, so a delete changes nothing
    a = Agent(cfg, confirm=lambda pr, s: "yes", use_llm=False)
    before = sorted(x.name for x in cfg.workspace.iterdir())
    a.handle("delete the hidden files")
    assert sorted(x.name for x in cfg.workspace.iterdir()) == before
    assert "no hidden files" in a.handle("list the hidden files").say.lower()
