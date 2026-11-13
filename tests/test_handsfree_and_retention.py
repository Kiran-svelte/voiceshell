"""Hands-free loop (no keyboard), wake word, and 24-hour trash retention."""
import json
import time
from dataclasses import dataclass

import pytest

from voiceshell.agent import Agent
from voiceshell.executor import Executor
from voiceshell.voice.handsfree import FileSource, HandsFree, match_wake


@pytest.mark.parametrize("text,woke,rest", [
    ("VoiceShell, list the files in the logs folder.", True, "list the files in the logs folder."),
    ("Voice shell.", True, ""),
    ("Hey voice shell, delete it", True, "delete it"),
    ("Voice cell, where am I?", True, "where am I?"),
    ("I think I'll make some tea now.", False, ""),
    ("Delete the notes file.", False, ""),
    ("Shell scripts are fun", False, ""),
])
def test_wake_word(text, woke, rest):
    assert match_wake(text) == (woke, rest)


@dataclass
class _Heard:
    text: str
    confidence: float = 0.95


class _TextASR:
    """Stands in for Whisper: the 'audio' items are already text."""
    def transcribe(self, item):
        return _Heard(item)


def _session(cfg, items):
    spoken = []
    hf = HandsFree(asr=_TextASR(), source=FileSource(items), speak=spoken.append)
    agent = Agent(cfg, confirm=hf.confirm, use_llm=False)
    hf.run(agent)
    return hf, spoken


def test_handsfree_full_session_without_keyboard(cfg):
    hf, spoken = _session(cfg, [
        "I think I'll make some tea now.",                       # ignored
        "Delete all the log files.",                             # no wake word: must be ignored
        "VoiceShell, what's taking up space in my downloads folder?",
        "VoiceShell.", "go to the logs folder",                  # wake word alone, then the request
        "VoiceShell, stop listening",
    ])
    kinds = [e["kind"] for e in hf.log]
    assert kinds == ["ignored", "ignored", "turn", "turn", "stop"]
    assert "holiday-video.mp4" in hf.log[2]["say"]
    assert len(list((cfg.workspace / "logs").glob("*.log"))) == 4          # the un-woken delete never ran
    assert "Yes?" in spoken and spoken[-1] == "Goodbye."


def test_handsfree_spoken_confirmation_and_silence(cfg):
    # 'make a folder called x' is a Tier 0 write: VoiceShell asks, then LISTENS for the answer
    hf, _ = _session(cfg, [
        "VoiceShell, make a folder called reports", "yes",
        "VoiceShell, make a folder called drafts", None,          # silence = no
    ])
    assert (cfg.workspace / "reports").is_dir()
    assert not (cfg.workspace / "drafts").exists()
    answers = [e for e in hf.log if e["kind"] == "answer"]
    assert answers[0]["answer"] == "yes" and answers[1]["answer"] == ""


def test_trash_expires_after_retention(cfg):
    ex = Executor(cfg)
    sh = ex.shadow("rm logs/*.log", cfg.workspace, ["logs/*.log"])
    ex.trash(sh.deleted, "old-batch")
    m = cfg.trash_dir / "old-batch" / ".manifest.json"
    data = json.loads(m.read_text())
    data["ts"] = time.time() - 25 * 3600                       # pretend it was deleted 25 hours ago
    m.write_text(json.dumps(data))
    assert ex.purge_expired() == 1
    ok, msg = ex.undo()
    assert not ok and "24 hours" in msg


def test_undo_only_restores_into_its_own_workspace(cfg, tmp_path):
    from voiceshell.config import Config
    from voiceshell.fixtures import build
    ex = Executor(cfg)
    sh = ex.shadow("rm notes.txt", cfg.workspace, ["notes.txt"])
    ex.trash(sh.deleted, "b1")
    other = Config(workspace=build(tmp_path / "other"), state_dir=cfg.state_dir)
    ok, _ = Executor(other).undo()
    assert not ok                                                # not offered to a different workspace
    assert Executor(cfg).undo()[0] and (cfg.workspace / "notes.txt").exists()


def test_clarifying_question_is_answered_without_wake_word(cfg):
    hf, _ = _session(cfg, [
        "VoiceShell, read report-old.txt",
        "VoiceShell, delete it",                 # → "Do you mean report-old.txt?"
        "no",                                    # answered WITHOUT the wake word
        "VoiceShell, stop listening",
    ])
    turns = [e for e in hf.log if e["kind"] == "turn"]
    assert "report-old.txt" in turns[1]["say"] and turns[2]["status"] == "cancelled"
    assert (cfg.workspace / "report-old.txt").exists()
    assert not [e for e in hf.log if e["kind"] == "ignored"]


def test_spoken_file_name_without_punctuation_is_matched_exactly(cfg):
    a = Agent(cfg, use_llm=False)
    r = a.handle("read reportold.txt")                       # speech dropped the hyphen
    assert "annual report" in r.steps[0]["output"]
    r = a.handle("read repotold.txt")                        # different letters: never guessed
    assert not r.steps or r.steps[0]["exit"] != 0 or "annual" not in r.steps[0]["output"]


def test_delete_confidence_judges_the_authority_words():
    from voiceshell.envelope import derive
    from voiceshell.gate.rules import Op
    # clear real-mic speech (~0.5-0.85) must admit DELETE — the measured preview is the real safeguard
    assert Op.DELETE in derive("delete report-old.txt", asr_confidence=0.55).ops
    assert Op.DELETE in derive("delete report-old.txt", asr_confidence=0.89).ops
    # garbled transcription (e.g. a 0.17 "notes.notes.txt") still withholds DELETE
    assert Op.DELETE not in derive("delete report-old.txt", asr_confidence=0.3).ops


def test_hold_to_talk_records_exactly_while_key_is_held():
    """Mic stays on through pauses while Enter is held; stops (plus a short tail) on release."""
    import numpy as np
    from voiceshell.voice import ptt

    # key: released 5 polls, then held for 100 blocks (3 s, incl. a long silent pause), then released
    states = iter([False] * 5 + [True] * 101 + [False] * 1000)
    reads = {"n": 0}

    class FakeMic:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def read(self):
            reads["n"] += 1
            return np.zeros(ptt.BLOCK, dtype=np.float32)       # silence: must NOT stop the recording

    audio = ptt.record_while_held(is_down=lambda: next(states), mic_factory=FakeMic, tail_s=0.3)
    held_blocks = 100
    assert reads["n"] == held_blocks + 10                       # all held blocks + 0.3 s tail, despite silence
    assert abs(len(audio) / ptt.SR - (held_blocks + 10) * 0.03) < 0.01


def test_hold_to_talk_gives_up_if_never_pressed():
    from voiceshell.voice import ptt
    audio = ptt.record_while_held(is_down=lambda: False, wait_s=0.05)
    assert audio.size == 0
