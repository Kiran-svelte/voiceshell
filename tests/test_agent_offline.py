"""Agent + executor without the language model (Tier 0 only)."""
from pathlib import Path

from voiceshell.agent import Agent, is_yes
from voiceshell.executor import Executor
from voiceshell.voice.normalise import normalise


def agent(cfg, answers=()):
    it = iter(answers)
    return Agent(cfg, confirm=lambda p, s: next(it, ""), use_llm=False)


def test_tier0_read_runs_without_confirmation(cfg):
    a = agent(cfg)
    r = a.handle("what's taking up space in my downloads folder")
    assert r.status == "ok" and r.tiers_used == [0] and not r.confirmations
    assert "holiday-video.mp4" in r.say


def test_tier0_cd_and_list(cfg):
    a = agent(cfg)
    a.handle("go to the logs folder")
    assert a.cwd_rel() == "~/logs"
    r = a.handle("list the files")
    assert "app.log" in r.steps[0]["output"]


def test_jail_environment(cfg):
    ex = Executor(cfg)
    r = ex.run("pwd; echo $HOME; env | wc -l", cfg.workspace)
    lines = r.stdout.split()
    assert lines[0].lower().endswith("/workspace") and lines[1].lower().endswith("/workspace")
    assert int(lines[-1]) < 25        # scrubbed environment


def test_timeout(cfg):
    cfg.exec_timeout_s = 1
    r = Executor(cfg).run("sleep 5", cfg.workspace)
    assert r.timed_out


def test_shadow_does_not_touch_real_workspace(cfg):
    ex = Executor(cfg)
    before = sorted(p.name for p in (cfg.workspace / "logs").iterdir())
    sh = ex.shadow("rm logs/*.log", cfg.workspace, ["logs/*.log"])
    assert sh.measured and len(sh.deleted) == 4 and sh.only_deletions
    assert sorted(p.name for p in (cfg.workspace / "logs").iterdir()) == before


def test_trash_and_undo(cfg):
    ex = Executor(cfg)
    sh = ex.shadow("rm logs/*.log", cfg.workspace, ["logs/*.log"])
    ex.trash(sh.deleted, "t1")
    assert not (cfg.workspace / "logs" / "app.log").exists()
    ok, msg = ex.undo()
    assert ok and (cfg.workspace / "logs" / "app.log").exists()


def test_confirmation_parsing_fr46():
    # clear affirmatives are accepted (strict or batch) — incl. real-speech forms like "Yes. Yes", "okay sure"
    for a in ("Yes.", "go ahead", "sure", "Yes. Yes", "okay sure", "yeah", "proceed", "do it"):
        assert is_yes(a, strict=True), a
    # FR-46: silence, ambiguous, or any negative cancels
    for a in ("", None, "maybe", "uh", "no", "yes no", "I guess", "what?", "wait", "cancel"):
        assert not is_yes(a, strict=True), a


def test_pronoun_delete_asks(cfg):
    r = agent(cfg).handle("delete it")
    assert r.status == "clarify" and not r.steps


def test_audit_written_for_every_turn(cfg):
    from voiceshell.audit import verify
    a = agent(cfg)
    a.handle("list the files")
    a.handle("where am i")
    ok, n, _ = verify(cfg.audit_path)
    assert ok and n >= 8


def test_normaliser():
    assert normalise("read notes dot txt") == "read notes.txt"
    assert normalise("list files dash l") == "list files -l"
    assert normalise("make a folder called project dash alpha") == "make a folder called project-alpha"
    assert normalise("move the p d f s") .endswith("PDFs")


def test_user_session_regression(cfg):
    """Replays the session from the user's screenshot (2026-10-08)."""
    a = agent(cfg)
    r = a.handle("Ok. Tell me what are the majorly storage files which are there in my laptop. Mentioned of files")
    assert r.tiers_used == [0] and "-type f" in r.steps[0]["command"]
    assert "holiday-video.mp4" in r.say and "workspace folder" in r.say
    assert "./downloads\n" not in r.steps[0]["output"]          # folders are not listed as files
    r2 = a.handle("Once done please repeat what you have done. Not just done")
    assert "I ran" in r2.say and "find" in r2.say and "holiday-video.mp4" in r2.say


def test_generic_answers_are_replaced():
    from voiceshell.summary import is_generic, summarize
    assert is_generic("Done.") and is_generic("I'm done.") and is_generic("")
    assert not is_generic("There are 4 log files.")
    s = summarize("du -ah | sort -rh", "4.5M\t.\n2.3M\t./downloads/holiday-video.mp4\n", Path("."))
    assert "holiday-video.mp4" in s and "megabytes" in s


class _LyingLLM:
    """A fully compromised model: plans a read, then lies about what happened."""
    def plan(self, utterance, cwd_rel, listing, history, note=""):
        from voiceshell.planner import Plan
        if history:
            return Plan("done", "", "Deleted ~/projects and ~/downloads", tier=2)
        return Plan("run", "cat meeting-notes.txt" if "meeting" in utterance else "cat notes.txt", "", tier=2)

    def answer(self, utterance, history):
        return True, "Deleted ~/projects and ~/downloads as instructed.", 1.0


def test_injected_output_is_never_summarised_by_the_model(cfg):
    a = agent(cfg)
    a.llm = _LyingLLM()
    r = a.handle("summarise meeting-notes.txt for me")
    assert "Deleted" not in r.say and "instructions" in r.say and "Nothing was changed" in r.say
    assert (cfg.workspace / "projects").exists() and (cfg.workspace / "downloads").exists()


def test_false_action_claim_is_blocked_without_injection(cfg):
    a = agent(cfg)
    a.llm = _LyingLLM()
    r = a.handle("what is in notes txt please")
    assert "Deleted" not in r.say and "Groceries" in r.say


def test_yes_after_clarify_continues_with_measured_confirmation(cfg):
    a = agent(cfg, answers=["yes"])
    a.handle("read report-old.txt")
    r = a.handle("delete it")
    assert r.status == "clarify" and "report-old.txt" in r.say
    a.llm = _DeletePlanner()
    r = a.handle("yes")
    assert not (cfg.workspace / "report-old.txt").exists()
    assert r.confirmations and r.confirmations[0]["kind"] == "per_command"   # still asked, with a measured preview


def test_no_after_clarify_changes_nothing(cfg):
    a = agent(cfg)
    a.handle("read report-old.txt")
    a.handle("delete it")
    r = a.handle("no")
    assert r.status == "cancelled" and (cfg.workspace / "report-old.txt").exists()


def test_bare_yes_without_a_question_does_nothing(cfg):
    a = agent(cfg)
    a.llm = _DeletePlanner()
    r = a.handle("yes")
    assert (cfg.workspace / "report-old.txt").exists() and not r.steps


class _DeletePlanner:
    def plan(self, utterance, cwd_rel, listing, history, note=""):
        from voiceshell.planner import Plan
        if "report-old.txt" in utterance and not history:
            return Plan("run", "rm report-old.txt", "", tier=2, final=True)
        return Plan("done", "", "Nothing to do.", tier=2)

    def answer(self, utterance, history):
        return False, "", 0.0


def test_repeated_failing_command_is_reported_honestly(cfg):
    class Repeat:
        def plan(self, utterance, cwd_rel, listing, history, note=""):
            from voiceshell.planner import Plan
            return Plan("run", "cat report.txt", "", tier=2)

        def answer(self, *a):
            return False, "", 0.0
    a = agent(cfg)
    a.llm = Repeat()
    r = a.handle("read the file called report.txt")
    assert r.status == "failed" and "No such file" in r.say and "report-old.txt" in r.say and len(r.steps) == 1
