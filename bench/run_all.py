"""One command for all the evidence:  python bench/run_all.py

Runs every suite fresh, saves each raw log, records the machine and code versions, runs a tamper test
on this run's audit log, and writes proof/<timestamp>/index.html (+ proof/LATEST.txt)."""
from __future__ import annotations

import hashlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUTB = ROOT / "bench" / "out"

SUITES = [
    ("doctor", "Self-check", [sys.executable, "-m", "voiceshell", "doctor"]),
    ("unit", "Unit tests", [sys.executable, "-m", "pytest", "-v", "tests"]),
    ("bench", "Benchmark (50 tasks)", [sys.executable, "bench/run_bench.py"]),
    ("voice", "Voice end-to-end (12 tasks)", [sys.executable, "bench/voice_e2e.py"]),
    ("scenarios", "Scenario suite (35)", [sys.executable, "bench/scenarios.py"]),
    ("live", "Live-test guide replay (15 steps)", [sys.executable, "bench/live_guide_replay.py"]),
    ("real", "Real folder (9 tasks)", [sys.executable, "bench/real_folder.py"]),
    ("ladder", "Hard-task ladder (12)", [sys.executable, "bench/complex_probe.py"]),
]


def sh(cmd, timeout=30):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                              errors="replace").stdout.strip()
    except Exception as e:  # noqa: BLE001
        return f"n/a ({e})"


def environment() -> dict:
    import psutil
    from voiceshell.config import Config
    from voiceshell.gate.gate import ruleset_sha
    cfg = Config()
    code = hashlib.sha256()
    for p in sorted((ROOT / "voiceshell").rglob("*.py")):
        code.update(p.read_bytes().replace(b"\r\n", b"\n"))
    try:
        import httpx
        tags = httpx.get(f"{cfg.ollama_url}/api/tags", timeout=3).json()["models"]
        digest = next((m["digest"][:12] for m in tags if m["name"].startswith(cfg.model)), "?")
    except Exception:  # noqa: BLE001
        digest = "?"
    return {
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "cpu": sh(["powershell", "-c", "(Get-CimInstance Win32_Processor).Name"]) or platform.processor(),
        "cores": psutil.cpu_count(),
        "ram_gb": round(psutil.virtual_memory().total / 2**30, 1),
        "gpu": sh(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]),
        "python": platform.python_version(),
        "ollama": sh(["ollama", "--version"]).splitlines()[-1] if sh(["ollama", "--version"]) else "?",
        "model": f"{cfg.model} (digest {digest})",
        "asr": f"faster-whisper {cfg.asr_model} (int8, CPU)",
        "gate_sha256": ruleset_sha(),
        "code_sha256": code.hexdigest(),
    }


def tamper_test(proof: Path) -> dict:
    from voiceshell.audit import verify
    src = OUTB / "state" / "audit.jsonl"
    good = proof / "audit-benchmark.jsonl"
    shutil.copy(src, good)
    ok, n, _ = verify(good)
    bad = proof / "audit-tampered.jsonl"
    lines = good.read_text(encoding="utf-8").splitlines()
    idx = next(i for i, l in enumerate(lines) if '"kind": "confirm"' in l and '"approved": false' in l)
    rec = json.loads(lines[idx])
    rec["data"]["approved"], rec["data"]["answer"] = True, "yes"
    lines[idx] = json.dumps(rec, ensure_ascii=False)
    bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t_ok, _, at = verify(bad)
    return {"records": n, "chain_valid": ok, "tampered_record": idx, "tamper_detected": not t_ok, "detected_at": at,
            "what": "a recorded 'No' to a delete confirmation was rewritten as 'yes'"}


def main():
    stamp = time.strftime("%Y%m%d-%H%M")
    proof = ROOT / "proof" / stamp
    proof.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    runs = []
    for key, title, cmd in SUITES:
        t0 = time.time()
        print(f"running {title}…", flush=True)
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (proof / f"{key}.log").write_text(p.stdout + ("\n--- stderr ---\n" + p.stderr if p.stderr.strip() else ""),
                                          encoding="utf-8")
        runs.append({"key": key, "title": title, "exit": p.returncode, "minutes": round((time.time() - t0) / 60, 1)})
    for src, name in [(OUTB / "results.json", "bench.json"), (OUTB / "voice" / "voice_results.json", "voice.json"),
                      (OUTB / "scen" / "scenarios.json", "scenarios.json"),
                      (OUTB / "live_guide" / "result.json", "live.json"), (OUTB / "real_folder.json", "real.json"),
                      (OUTB / "complex" / "complex.json", "ladder.json"),
                      (OUTB / "scen" / "cli_transcript.txt", "cli_transcript.txt")]:
        if src.exists():
            shutil.copy(src, proof / name)
    data = {"env": environment(), "runs": runs, "tamper": tamper_test(proof)}
    (proof / "summary.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    page(proof, data)
    (ROOT / "proof" / "LATEST.txt").write_text(f"{stamp}\n", encoding="utf-8")
    print(f"proof written to {proof / 'index.html'}")


# ─────────────────────────────── proof page ───────────────────────────────
def e(x) -> str:
    return html.escape(str(x))


def load(proof: Path, name: str):
    p = proof / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def badge(ok: bool) -> str:
    return '<span class="b ok">PASS</span>' if ok else '<span class="b no">FAIL</span>'


def page(proof: Path, data: dict) -> None:
    env, tam = data["env"], data["tamper"]
    unit_log = (proof / "unit.log").read_text(encoding="utf-8")
    m = re.search(r"(\d+) passed(?:, (\d+) failed)?", unit_log)
    unit_pass, unit_fail = (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 1)
    unit_names = re.findall(r"tests/\S+::(\S+) PASSED", unit_log)
    bench, voice, scen = load(proof, "bench.json"), load(proof, "voice.json"), load(proof, "scenarios.json")
    live, real, ladder = load(proof, "live.json"), load(proof, "real.json"), load(proof, "ladder.json")
    doctor = (proof / "doctor.log").read_text(encoding="utf-8")
    bs = bench["summary"]
    live_res = {int(k): v for k, v in live["results"].items()}
    cards = [
        ("Unit tests", f"{unit_pass}/{unit_pass + unit_fail}", unit_fail == 0),
        ("Benchmark", f"{sum(bs[c][0] for c in ('simple', 'multi', 'safety', 'injection'))}/"
                      f"{sum(bs[c][1] for c in ('simple', 'multi', 'safety', 'injection'))}",
         all(bs[c][0] == bs[c][1] for c in ('simple', 'multi', 'safety', 'injection'))),
        ("Deletes without your yes", str(bs["audit_unconfirmed_destructive"]), bs["audit_unconfirmed_destructive"] == 0),
        ("Injection attacks blocked", f"{bs['injection'][0]}/{bs['injection'][1]}", bs["injection"][0] == bs["injection"][1]),
        ("Voice tasks", f"{voice['summary']['pass']}/{voice['summary']['n']}", voice["summary"]["pass"] == voice["summary"]["n"]),
        ("Scenarios", f"{sum(s['passed'] for s in scen)}/{len(scen)}", all(s["passed"] for s in scen)),
        ("Live guide, hands-free", f"{sum(live_res.values())}/15", all(live_res.values())),
        ("Real folder", f"{sum(t['pass'] for t in real['tasks'])}/{len(real['tasks'])}", all(t["pass"] for t in real["tasks"])),
        ("Tamper detected", "yes" if tam["tamper_detected"] else "NO", tam["tamper_detected"]),
        ("Hard-task ladder", f"{sum(t['pass'] for t in ladder)}/{len(ladder)}", None),
    ]
    priv = next((s for s in scen if s["id"] == "B6"), None)
    hw = next((s for s in scen if s["id"] == "B7"), None)

    def table(head, rows):
        return ("<div class='tw'><table><thead><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr></thead><tbody>"
                + "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows) + "</tbody></table></div>")

    bench_rows = [[e(t["id"]), e(t["cat"]), e(" / ".join(t["utterances"])), badge(t["pass"]),
                   "<code>" + e("; ".join(t["commands"]) or "—") + "</code>", e(t["say"][-1][:220])] for t in bench["tasks"]]
    voice_rows = [[e(t["id"]), e(t["spoken"]), e(t["heard"]), e(t["asr_conf"]), "<code>" + e("; ".join(t["commands"]) or "—") + "</code>",
                   e(t["say"][:200]), badge(t["pass"])] for t in voice["tasks"]]
    scen_rows = [[e(s["id"]), e(s["source"]), e(s["title"]), badge(s["passed"]), e(s["evidence"][:400])] for s in scen]
    live_turns = []
    for ent in live["log"]:
        if ent["kind"] == "turn":
            live_turns.append([e(ent["heard"]), "<code>" + e("; ".join(ent["commands"]) or "—") + "</code>", e(ent["say"][:220])])
        elif ent["kind"] == "answer":
            live_turns.append([f"<i>answer to: {e(ent['prompt'][:90])}…</i>", "", e(ent["answer"] or "(silence)")])
        elif ent["kind"] == "ignored":
            live_turns.append(["<i>(speech without the wake word)</i>", "", "ignored"])
    real_rows = [[e(t["task"]), badge(t["pass"]), e(t["seconds"]), "<code>" + e("; ".join(t["commands"]) or "—") + "</code>",
                  e((t["asked"][0][:150] + "…") if t["asked"] else "—"), e(t["say"][:200])] for t in real["tasks"]]
    ladder_rows = [[f"L{t['level']}", e(t["task"]), e(t["why_hard"]), badge(t["pass"]), e(t["say"][:180])] for t in ladder]
    run_rows = [[e(r["title"]), f"<a href='{r['key']}.log'>{r['key']}.log</a>", e(r["exit"]), e(r["minutes"])] for r in data["runs"]]

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceShell Proof Run</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e3e0;--ok:#1a7f37;--okbg:#e6f4ea;--no:#b42318;--nobg:#fdecea;--accent:#2d5bd7;--code:#f0f0ee}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#141416;--card:#1c1c1f;--ink:#ececee;--mute:#9a9aa2;--line:#2c2c31;--ok:#5cc97a;--okbg:#16301e;--no:#ff7a6e;--nobg:#3a1b19;--accent:#7aa2ff;--code:#26262b}}}}
:root[data-theme="dark"]{{--bg:#141416;--card:#1c1c1f;--ink:#ececee;--mute:#9a9aa2;--line:#2c2c31;--ok:#5cc97a;--okbg:#16301e;--no:#ff7a6e;--nobg:#3a1b19;--accent:#7aa2ff;--code:#26262b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 80px}}h1{{font-size:28px;margin:0 0 4px}}h2{{font-size:19px;margin:36px 0 10px}}
.sub{{color:var(--mute);margin:0 0 22px;overflow-wrap:anywhere}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}.card .n{{font-size:24px;font-weight:650}}
.card .l{{color:var(--mute);font-size:13px}}.card.ok .n{{color:var(--ok)}}.card.no .n{{color:var(--no)}}
.tw{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line)}}th{{font-weight:600;color:var(--mute);white-space:nowrap}}
tr:last-child td{{border-bottom:0}}code{{background:var(--code);padding:1px 5px;border-radius:5px;font-size:12px;word-break:break-word}}
.b{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:20px;white-space:nowrap}}.b.ok{{background:var(--okbg);color:var(--ok)}}.b.no{{background:var(--nobg);color:var(--no)}}
pre{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;overflow-x:auto;font-size:12.5px}}
.note{{background:var(--card);border-left:3px solid var(--accent);padding:10px 14px;border-radius:6px;margin:10px 0}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;margin:0}}dt{{color:var(--mute)}}dd{{margin:0;word-break:break-all}}a{{color:var(--accent)}}
</style></head><body><main>
<h1>VoiceShell — proof run</h1>
<p class="sub">Every suite run fresh on {e(env['when'])}, on the machine below. Raw logs and result files sit next to this page.</p>
<div class="grid">{''.join(f"<div class='card {'ok' if ok else ('no' if ok is False else '')}'><div class='n'>{e(v)}</div><div class='l'>{e(k)}</div></div>" for k, v, ok in cards)}</div>
<div class="note">The hard-task ladder is reported as measured: it maps the small local model's limits and is not expected to be all green.</div>

<h2>Machine and code under test</h2>
<div class="card"><dl>{''.join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in env.items())}</dl></div>

<h2>Self-check</h2><pre>{e(doctor)}</pre>

<h2>Safety evidence</h2>
{table(["Check", "Result"], [
    ["Destructive commands executed (counted from the audit log)", e(bs["audit_destructive_executions"])],
    ["…of which without an explicit 'yes'", f"<b>{e(bs['audit_unconfirmed_destructive'])}</b>"],
    ["Forbidden commands executed", e(bs["forbidden_executed"])],
    ["Read-only requests that asked for confirmation", f"{bs['over_confirmation'][0]}/{bs['over_confirmation'][1]}"],
    ["Audit chain of the benchmark run", f"{tam['records']} records, valid={tam['chain_valid']}"],
    ["Tamper test", f"{e(tam['what'])} at record {tam['tampered_record']} → detected at record {e(tam['detected_at'])}"],
    ["Network (scenario B6)", e(priv["evidence"] if priv else "n/a")],
    ["Memory (scenario B7)", e(hw["evidence"] if hw else "n/a")],
])}

<h2>Live-test guide, replayed hands-free (wake word, spoken answers, silence)</h2>
{table(["Step", "Result"], [[f"Step {k}", badge(v)] for k, v in sorted(live_res.items())])}
<p></p>{table(["Heard (via Whisper)", "Command", "VoiceShell said"], live_turns)}

<h2>Voice end-to-end</h2>
<p class="sub">Mean word error rate {voice['summary']['mean_wer']}, speech recognition p50 {voice['summary']['asr_ms_p50']} ms.</p>
{table(["ID", "Spoken", "Heard", "Conf.", "Command", "Reply", ""], voice_rows)}

<h2>Benchmark — all 50 tasks</h2>
<p class="sub">Built-in requests p50 {bs['tier0_first_effect_ms']['p50']} ms · AI-planned p50 {bs['tier2_first_effect_ms']['p50']} ms, p95 {bs['tier2_first_effect_ms']['p95']} ms to first effect.</p>
{table(["ID", "Type", "Request", "", "Command(s)", "Reply"], bench_rows)}

<h2>Scenarios</h2>{table(["ID", "From", "Scenario", "", "Evidence"], scen_rows)}

<h2>Real folder ({real['files']} files, {real['mb']} MB, non-personal)</h2>
{table(["Request", "", "s", "Command", "Asked first", "Reply"], real_rows)}

<h2>Hard-task ladder</h2>{table(["", "Task", "Why it's hard", "", "Reply"], ladder_rows)}

<h2>The real CLI, driven through stdin</h2><pre>{e((proof / 'cli_transcript.txt').read_text(encoding='utf-8')[-6000:] if (proof / 'cli_transcript.txt').exists() else 'n/a')}</pre>

<h2>Unit tests ({unit_pass})</h2><p class="sub">{e(', '.join(sorted(set(unit_names)))[:4000])}</p>

<h2>Raw logs</h2>{table(["Suite", "Log", "Exit code", "Minutes"], run_rows)}

<h2>Not proven by this run</h2>
<ul><li>Real human voices, accents and a live microphone: all automated voice tests use synthetic speech. A speaker-to-microphone attempt on 2026-10-14 picked up people talking nearby instead (all correctly ignored); it was stopped and the recordings deleted.</li>
<li>Busy rooms: overheard speech is transcribed locally (about 3 s each) and can delay hearing "VoiceShell".</li>
<li>No operating-system sandbox on Windows; no independent security review; English only; one laptop.</li></ul>
</main></body></html>"""
    (proof / "index.html").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    main()
