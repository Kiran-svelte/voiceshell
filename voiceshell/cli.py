"""Front-ends: typed, microphone (push-to-talk), and audio file."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from .config import Config

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
console = Console()

_TIER = {0: "Tier 0 · template", 2: "Tier 2 · Qwen2.5-Coder-3B"}


def show(ev) -> None:
    k = ev.kind
    if k == "heard":
        conf = ev.data.get("confidence", 1.0)
        console.print(f"[bold cyan]YOU[/] {ev.text}" + (f"  [dim](asr conf {conf:.2f})[/]" if conf < 1 else ""))
    elif k == "envelope":
        console.print(f"  [dim]envelope[/] {ev.text}")
    elif k == "plan":
        if ev.data.get("action") == "run":
            console.print(f"  [dim]{_TIER.get(ev.data['tier'], ev.data['tier'])} · {ev.data['latency_ms']} ms[/]  "
                          f"[bold]$ {ev.text}[/]")
    elif k == "verdict":
        tier = ev.data.get("tier")
        if ev.text == "ALLOWED":
            console.print(f"  [green]gate ✓[/] {tier}  [dim]{ev.data.get('checks')}[/]")
        else:
            console.print(f"  [red]gate ✗[/] {tier}  {ev.data.get('reasons')}")
    elif k == "output":
        if ev.text.strip() and ev.text != "(no output)":
            console.print(Panel(ev.text[:1500], title=f"output · exit {ev.data.get('exit')}", border_style="dim"))
    elif k == "info":
        console.print(f"  [yellow]⚠ {ev.text}[/]")
    elif k in ("say", "refuse"):
        style = "red" if k == "refuse" else "bold green"
        console.print(f"[{style}]VOICESHELL[/] {ev.text}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="voiceshell", description="Speak to your OS. Securely. Offline.")
    ap.add_argument("command", nargs="?", default="text",
                    choices=["handsfree", "voice", "text", "file", "doctor", "resources", "verify", "seal",
                             "demo-setup", "export", "rotate-log", "enrol", "policy"])
    ap.add_argument("--workspace", type=Path, default=None)
    ap.add_argument("--state-dir", type=Path, default=None, help="where the audit log and trash live")
    ap.add_argument("--reason", default="", help="rotate-log: why the log is being rotated")
    ap.add_argument("--name", default="", help="enrol: your name")
    ap.add_argument("--trust", default="admin", choices=["novice", "operator", "admin"], help="enrol: trust level")
    ap.add_argument("--wavs", nargs="*", type=Path, help="enrol: use these recordings instead of the microphone")
    ap.add_argument("--allow", default="", help="policy: comma-separated verbs that may skip the write question")
    ap.add_argument("--note", default="", help="policy: why the allow rule exists")
    ap.add_argument("--reviewed", action="store_true", help="policy: record that the policy was reviewed")
    ap.add_argument("--say", action="store_true", help="speak replies aloud")
    ap.add_argument("--wav", type=Path, help="audio file for the 'file' command")
    ap.add_argument("--yes", action="store_true", help="file mode: answer confirmations with 'yes'")
    a = ap.parse_args(argv)
    cfg = Config(**{k: v for k, v in (("workspace", a.workspace), ("state_dir", a.state_dir)) if v})

    if a.command == "seal":
        from .gate.gate import seal
        console.print(f"gate sealed: {seal()}")
        return 0
    if a.command == "verify":
        from .audit import verify
        ok, n, bad = verify(cfg.audit_path)
        console.print(f"audit log: {n} records, chain {'[green]VALID' if ok else f'[red]BROKEN at record {bad}'}[/]")
        return 0 if ok else 1
    if a.command == "rotate-log":
        from .audit import rotate, verify
        ok, n, bad = verify(cfg.audit_path)
        if ok:
            console.print(f"audit log is valid ({n} records); nothing to rotate")
            return 0
        if not a.reason:
            console.print(f"[red]chain broken at record {bad}.[/] Re-run with --reason \"why\" to archive it and "
                          "start a new chain. The archive is kept byte-for-byte and bound by its SHA-256.")
            return 1
        arch = rotate(cfg.audit_path, a.reason)
        console.print(f"archived the broken log as {arch.name} (unchanged); new chain started and bound to it")
        return 0
    if a.command == "export":
        from .audit import export_csv, verify
        ok, n, bad = verify(cfg.audit_path)
        out = cfg.state_dir / "audit-export.csv"
        export_csv(cfg.audit_path, out)
        console.print(f"exported {n} records to {out} (chain {'valid' if ok else f'BROKEN at {bad}'})")
        return 0 if ok else 1
    if a.command == "enrol":
        return _enrol(cfg, a)
    if a.command == "policy":
        return _policy(cfg, a)
    if a.command == "doctor":
        from .runtime import doctor
        rows = doctor(cfg)
        for name, ok, detail in rows:
            console.print(f"  {'[green]✓' if ok else '[red]✗'}[/] {name:14} {detail}")
        bad = [n for n, ok, _ in rows if not ok]
        console.print("[bold green]Ready.[/]" if not bad else f"[bold red]Not ready:[/] fix {', '.join(bad)}")
        return 0 if not bad else 1
    if a.command == "resources":
        from .runtime import enforce_limits, resources
        enforce_limits(cfg)                      # trim every store to its cap, then report
        for name, detail, ok in resources(cfg):
            console.print(f"  {'[green]✓' if ok else '[yellow]⚠'}[/] {name:22} {detail}")
        console.print("[dim]Every store is bounded; stores over cap are trimmed automatically.[/]")
        return 0
    if a.command == "demo-setup":
        from .fixtures import build
        build(cfg.workspace)
        console.print(f"demo workspace created at {cfg.workspace}")
        return 0

    from .agent import Agent
    from .runtime import ensure_ollama
    with console.status("checking the local model server…"):
        up, msg = ensure_ollama(cfg)
    console.print(f"[dim]{msg}[/]" if up else f"[yellow]{msg}[/]")
    tts = None
    if a.say or a.command in ("voice", "handsfree"):
        from .voice.tts import speak as tts

    asr = None
    if a.command in ("voice", "file", "handsfree"):
        from .voice.asr import ASR
        with console.status("loading speech model…"):
            asr = ASR(cfg.asr_model)

    def listen(wait_s: float | None = None) -> tuple[str, float]:
        """Hold-to-talk on Windows: the mic is on exactly while Enter is held (no pause cut-off)."""
        from .voice import ptt
        from .voice.normalise import normalise

        def state(s):
            if s == "recording":
                console.print("[bold red]● RECORDING[/] [dim]keep holding Enter while you speak, release when done[/]")
            elif s.startswith("stopped:"):
                console.print(f"[dim]○ mic off ({s.split(':')[1]} s)[/]")
        if ptt.available():
            audio = ptt.record_while_held(wait_s=wait_s, on_state=state)
        else:                                       # other platforms: press Enter, stops on silence
            from .voice.asr import record_until_silence
            input()
            console.print("[bold red]● LISTENING[/]")
            audio = record_until_silence()
        if audio.size < 16000 * 0.3:
            return "", 0.0
        h = asr.transcribe(audio)
        listen.last_audio = audio
        return normalise(h.text), h.intent_confidence

    def confirm(prompt: str, strict: bool) -> str:
        console.print(f"[bold yellow]VOICESHELL[/] {prompt}")
        if tts:
            tts(prompt)
        if a.command == "voice":
            console.print("[dim]hold Enter and answer yes or no (no answer within 15 s = cancel)[/]")
            ans, _ = listen(wait_s=15)
            console.print(f"[cyan]YOU[/] {ans or '(no answer: cancelled)'}")
            return ans
        if a.command == "file":
            ans = "yes" if a.yes else ""
            console.print(f"[cyan]YOU[/] {ans or '(silence)'}")
            return ans
        return console.input("[cyan]YOU[/] ")

    def on_event(ev):
        show(ev)
        if tts and ev.kind in ("say", "refuse"):
            tts(ev.text)

    if a.command == "handsfree":
        return _handsfree(cfg, asr, tts)

    agent = Agent(cfg, confirm=confirm, on_event=on_event)
    from .voice.speaker import SpeakerID
    sid = SpeakerID(cfg.state_dir / "speakers.json", agent.policy.data["unknown_voice_trust"])
    if a.command == "voice" and sid.enabled:
        console.print(f"[dim]speaker identity on ({len(sid.profiles)} enrolled); other voices are "
                      f"{sid.unknown_trust}[/]")
    if agent.policy.review_due():
        console.print("[yellow]Policy review is due: run  python -m voiceshell policy  and then "
                      "python -m voiceshell policy --reviewed[/]")
    if agent.llm and not agent.llm.available():
        console.print("[yellow]Model not reachable — only built-in commands will work. Run: python -m voiceshell doctor[/]")
    elif agent.llm:
        agent.llm.warm()

    if a.command == "file":
        from .voice.normalise import normalise
        h = asr.transcribe(str(a.wav))
        agent.handle(normalise(h.text), h.intent_confidence)
        return 0

    console.print(Panel("[bold]VoiceShell[/] — speak to your OS. Securely. Offline.\n"
                        f"workspace: {cfg.workspace}\n"
                        + ("HOLD Enter while you speak, release when you're done. Ctrl+C cancels a request; "
                           "Ctrl+C at the prompt quits." if a.command == "voice" else "Type a request. 'exit' to quit."),
                        border_style="cyan"))
    def run_turn(text: str, conf: float = 1.0) -> None:
        """FR-05: Ctrl+C cancels the request in progress, not the whole program."""
        try:
            speaker = None
            if sid.enabled and getattr(listen, "last_audio", None) is not None and a.command == "voice":
                speaker = sid.identify(listen.last_audio)
                console.print(f"  [dim]speaker[/] {speaker.describe()} [dim](match {speaker.score:.2f})[/]")
            agent.handle(text, conf, speaker=speaker)
        except KeyboardInterrupt:
            agent.audit.append("cancelled_by_user", {"text": text})
            console.print()
            console.print("[yellow]Cancelled this request (Ctrl+C). Anything already confirmed and done stays "
                          "done and is in the log.[/]")

    while True:
        try:
            if a.command == "voice":
                console.print(f"[dim]{agent.cwd_rel()} — hold Enter and speak…[/]")
                text, conf = listen()
                if not text:
                    console.print("[dim]didn't catch that: hold Enter for the whole sentence[/]")
                    continue
                run_turn(text, conf)
            else:
                text = console.input(f"[dim]{agent.cwd_rel()}[/] [cyan]›[/] ").strip()
                if text in ("exit", "quit"):
                    return 0
                if text:
                    run_turn(text)
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print("[dim]Stopped.[/]")
            return 0


ENROL_PROMPTS = [
    "VoiceShell, list the files in the downloads folder and tell me which one is the biggest.",
    "Make a folder called reports and move all the PDF files into it.",
    "Delete the temporary files in the logs folder, then show me how much disk space is free.",
]


def _enrol(cfg: Config, a) -> int:
    """P1: record a few sentences (hold Enter for each) and store only a voice fingerprint, never the audio."""
    from .voice.speaker import SpeakerID
    if not a.name:
        console.print("[red]Give your name:[/] python -m voiceshell enrol --name Kiran --trust admin")
        return 1
    sid = SpeakerID(cfg.state_dir / "speakers.json")
    samples = [str(p) for p in a.wavs] if a.wavs else []
    if not samples:
        from .voice import ptt
        console.print(f"Enrolling [bold]{a.name}[/] as [bold]{a.trust}[/]. For each sentence: HOLD Enter, read it "
                      "aloud, release.")
        for i, line in enumerate(ENROL_PROMPTS, 1):
            console.print(f"\n[bold]{i}/{len(ENROL_PROMPTS)}[/]  \"{line}\"")
            audio = ptt.record_while_held(on_state=lambda s: console.print(
                "[bold red]● RECORDING[/]" if s == "recording" else f"[dim]{s}[/]"))
            if audio.size < 16000:
                console.print("[yellow]Too short, skipped.[/]")
                continue
            samples.append(audio)
    if len(samples) < 2:
        console.print("[red]Need at least two recordings.[/]")
        return 1
    consistency = sid.enrol(a.name, a.trust, samples)
    console.print(f"[green]Enrolled {a.name} ({a.trust})[/] from {len(samples)} recordings; consistency "
                  f"{consistency:.2f}. Only a voice fingerprint was stored (no audio) in {sid.path.name}.")
    return 0


def _policy(cfg: Config, a) -> int:
    """P4 governance: show the policy, add allow rules, record reviews (all in the audit log)."""
    from .audit import AuditLog
    from .policy import ALLOWABLE_VERBS, Policy, TRUST
    from .voice.speaker import SpeakerID
    pol = Policy(cfg.state_dir / "policy.json")
    log = AuditLog(cfg.audit_path)
    if a.allow:
        verbs = [v.strip() for v in a.allow.split(",") if v.strip()]
        ok = pol.add_rule(verbs, a.note)
        rejected = sorted(set(verbs) - set(ok))
        log.append("policy_change", {"allow": ok, "rejected": rejected, "note": a.note})
        console.print(f"[green]Allow rule added:[/] {', '.join(ok) or '(none)'}"
                      + (f"   [red]rejected (never allowed to skip a question): {', '.join(rejected)}[/]" if rejected else ""))
    if a.reviewed:
        pol.mark_reviewed()
        log.append("policy_review", {"rules": pol.rules(), "unknown_voice_trust": pol.data["unknown_voice_trust"]})
        console.print("[green]Policy review recorded in the audit log.[/]")
    sid = SpeakerID(cfg.state_dir / "speakers.json")
    console.print("[bold]Permission model (P2)[/]  read: no question · write: one question (measured preview) · "
                  "destructive: per-command spoken yes + undo")
    console.print("[bold]Trust levels (P1)[/]  " + " · ".join(f"{k}: {', '.join(sorted(v))}" for k, v in TRUST.items()))
    console.print("[bold]Enrolled voices[/]  " + (", ".join(f"{n} → {p['trust']} (since {p['enrolled']})"
                                                             for n, p in sid.profiles.items()) or "none")
                  + f"   ·   unknown voices → {pol.data['unknown_voice_trust']}")
    console.print("[bold]Allow rules (P4)[/]  " + ("; ".join(f"{', '.join(r['verbs'])} ({r['note']})" for r in pol.rules())
                                                     or "none")
                  + f"   ·   only these may ever skip the write question: {', '.join(sorted(ALLOWABLE_VERBS))}")
    last = pol.data.get("last_review")
    console.print("[bold]Last review[/]  " + (time.strftime("%Y-%m-%d", time.localtime(last)) if last else "never")
                  + ("   [yellow](due)[/]" if pol.review_due() else ""))
    return 0


def _handsfree(cfg: Config, asr, tts) -> int:
    from .agent import Agent
    from .voice.handsfree import HandsFree, MicSource

    def state(s):
        if s == "listening":
            console.print("[bold red]● listening[/] [dim](say \"VoiceShell\" first)[/]")

    def hf_event(kind, text):
        styles = {"ignored": "[dim]  (heard speech without the wake word: ignored, not shown, not kept)[/]", "woke": "[bold cyan]VOICESHELL[/] Yes?",
                  "request": "[bold cyan]YOU[/] {}", "ask": "[bold yellow]VOICESHELL[/] {}",
                  "answer": "[cyan]YOU[/] {}", "info": "[dim]{}[/]"}
        console.print(styles.get(kind, "{}").format(text))

    from .policy import Policy
    from .voice.speaker import SpeakerID
    sid = SpeakerID(cfg.state_dir / "speakers.json", Policy(cfg.state_dir / "policy.json").data["unknown_voice_trust"])
    hf = HandsFree(asr=asr, source=MicSource(on_state=state), speak=tts, phrase=cfg.wake_phrase, on_event=hf_event,
                   identify=sid.identify if sid.enabled else None)
    if sid.enabled:
        people = ", ".join(f"{n} ({p['trust']})" for n, p in sid.profiles.items())
        console.print(f"[dim]speaker identity on: {people}; other voices are {sid.unknown_trust}[/]")

    def on_event(ev):
        if ev.kind != "heard":
            show(ev)

    agent = Agent(cfg, confirm=hf.confirm, on_event=on_event)
    if agent.llm and agent.llm.available():
        agent.llm.warm()
    console.print(Panel("[bold]VoiceShell — hands-free[/]\n"
                        f"workspace: {cfg.workspace}\n"
                        "Say [bold]\"VoiceShell\"[/] then your request, e.g. \"VoiceShell, what can you do?\"\n"
                        "It listens for your yes/no by itself. Say \"VoiceShell, stop listening\" to quit.",
                        border_style="cyan"))
    tts("Hands-free mode. Say VoiceShell, then your request.")
    try:
        hf.run(agent)
    except KeyboardInterrupt:
        console.print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
