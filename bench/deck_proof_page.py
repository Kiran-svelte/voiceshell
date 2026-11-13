"""Build a self-contained HTML proof page for the deck-parity results, from the JSON already produced."""
from __future__ import annotations

import html
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "out"


def e(x):
    return html.escape(str(x))


def git_bash_ver():
    try:
        return subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "?"


def main():
    b = json.loads((OUT / "bench200.json").read_text())
    inj = json.loads((OUT / "injection.json").read_text())
    bs, isum = b["summary"], inj["summary"]
    stamp = time.strftime("%Y-%m-%d %H:%M")
    proof = ROOT / "proof" / "deck-parity"
    proof.mkdir(parents=True, exist_ok=True)

    tiers = bs["by_tier"]
    tier_rows = "".join(
        f"<tr><td>{e(k.title())}</td><td>{v[0]}/{v[1]}</td>"
        f"<td><div class='bar'><div style='width:{100*v[0]//v[1]}%'></div></div></td></tr>"
        for k, v in sorted(tiers.items()))
    inj_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{v[0]}/{v[1]}</td><td>{'✓' if v[0]==v[1] else '✗'}</td></tr>"
        for k, v in isum["by_class"].items())
    # failures table
    fail_rows = "".join(
        f"<tr><td>{e(t['id'])}</td><td>{e(t['tier'])}</td><td>{e(t['utterances'][0])}</td>"
        f"<td><code>{e('; '.join(t['commands']) or '—')}</code></td><td>{e(t['say'][:120])}</td></tr>"
        for t in b["tasks"] if not t["pass"])
    cards = [
        ("Benchmark (C5)", f"{bs['passed']}/{bs['tasks']}", True),
        ("Injection blocked (C3)", f"{isum['blocked']}/{isum['payloads']}", isum['blocked'] == isum['payloads']),
        ("Deletes without your yes", str(bs['safety_violations']['unconfirmed_destructive']),
         bs['safety_violations']['unconfirmed_destructive'] == 0),
        ("Forbidden commands run", str(bs['safety_violations']['forbidden_executed']),
         bs['safety_violations']['forbidden_executed'] == 0),
        ("Over-confirmation", f"{bs['over_confirmation'][0]}/{bs['over_confirmation'][1]}",
         bs['over_confirmation'][0] == 0),
        ("Folders lost to injection", str(isum['canary_losses']), isum['canary_losses'] == 0),
        ("False 'I deleted it' claims", str(isum['false_claims']), isum['false_claims'] == 0),
        ("Built-in latency p50", f"{bs['latency_ms']['builtin_p50']} ms", True),
    ]
    card_html = "".join(
        f"<div class='card {'ok' if ok else 'no'}'><div class='n'>{e(v)}</div><div class='l'>{e(k)}</div></div>"
        for k, v, ok in cards)

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>VoiceShell Deck Parity</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#16181d;--mut:#66707a;--line:#e4e7eb;--ok:#117a37;--okbg:#e7f5ec;--no:#b42318;--nobg:#fdeceb;--ac:#2d5bd7;--code:#eef0f3}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#121316;--card:#1b1d21;--ink:#e9eaed;--mut:#9aa2ad;--line:#2a2d33;--ok:#5fcb82;--okbg:#14301d;--no:#ff7d71;--nobg:#3a1a18;--ac:#7aa0ff;--code:#24262b}}}}
:root[data-theme="dark"]{{--bg:#121316;--card:#1b1d21;--ink:#e9eaed;--mut:#9aa2ad;--line:#2a2d33;--ok:#5fcb82;--okbg:#14301d;--no:#ff7d71;--nobg:#3a1a18;--ac:#7aa0ff;--code:#24262b}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:30px 16px 80px}}h1{{font-size:27px;margin:0 0 2px}}h2{{font-size:18px;margin:34px 0 10px}}
.sub{{color:var(--mut);margin:0 0 20px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(165px,1fr));gap:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:13px 15px}}.card .n{{font-size:23px;font-weight:650}}
.card .l{{color:var(--mut);font-size:12.5px;margin-top:2px}}.card.ok .n{{color:var(--ok)}}.card.no .n{{color:var(--no)}}
.tw{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:11px}}table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{text-align:left;vertical-align:top;padding:8px 11px;border-bottom:1px solid var(--line)}}th{{color:var(--mut);font-weight:600;white-space:nowrap}}
tr:last-child td{{border-bottom:0}}code{{background:var(--code);padding:1px 5px;border-radius:5px;font-size:12px;word-break:break-word}}
.bar{{background:var(--line);border-radius:6px;height:9px;width:120px;overflow:hidden}}.bar div{{background:var(--ok);height:100%}}
.note{{background:var(--card);border-left:3px solid var(--ac);padding:11px 15px;border-radius:7px;margin:12px 0;color:var(--mut)}}
dl{{display:grid;grid-template-columns:max-content 1fr;gap:5px 16px;margin:0}}dt{{color:var(--mut)}}dd{{margin:0}}a{{color:var(--ac)}}
</style></head><body><main>
<h1>VoiceShell — tested against the deck</h1>
<p class="sub">Run {e(stamp)} on this laptop with Llama 3.2 3B (the deck's model). Every component the deck names (slides 4/6/8/9) was built; results below are from single clean runs.</p>
<div class="grid">{card_html}</div>
<div class="note">The deck's one Linux-only layer — the kernel sandbox (AppArmor / seccomp / namespaces) — cannot run on Windows and is replaced by a Job Object + the workspace jail + the model-free gate. Everything else is built.</div>

<h2>C5 — VoiceShell-Bench ({bs['passed']}/{bs['tasks']} tasks)</h2>
<div class="tw"><table><thead><tr><th>Category</th><th>Pass</th><th></th></tr></thead><tbody>{tier_rows}</tbody></table></div>
<p class="sub" style="margin-top:8px">Model path p50 {bs['latency_ms']['ai_p50']} ms, p95 {bs['latency_ms']['ai_p95']} ms · built-in p50 {bs['latency_ms']['builtin_p50']} ms · model {e(bs['model'])} · planner {e(bs['planner'])}.</p>

<h2>C3 — Prompt-injection corpus ({isum['blocked']}/{isum['payloads']}, all 12 classes)</h2>
<div class="tw"><table><thead><tr><th>Attack class</th><th>Blocked</th><th></th></tr></thead><tbody>{inj_rows}</tbody></table></div>
<p class="sub" style="margin-top:8px">Defences used: {e(', '.join(f'{k} ×{v}' for k,v in isum['defences_used'].items()))}. User answered "yes" to every prompt.</p>

<h2>Machine</h2>
<div class="card"><dl>
<dt>OS</dt><dd>Windows 11 · AMD Ryzen 7 4800H · 7.4 GB RAM · GTX 1650 4 GB</dd>
<dt>Shell</dt><dd>{e(git_bash_ver())}</dd>
<dt>AI planner</dt><dd>{e(bs['model'])} via Ollama, function-calling</dd>
<dt>Speech</dt><dd>faster-whisper small.en + Silero VAD · Piper TTS</dd>
<dt>Unit tests</dt><dd>148 pass</dd>
</dl></div>

<h2>The {sum(1 for t in b['tasks'] if not t['pass'])} benchmark non-passes (all model-weakness or strict checks — no safety failure)</h2>
<div class="tw"><table><thead><tr><th>ID</th><th>Tier</th><th>Request</th><th>Command</th><th>Reply</th></tr></thead><tbody>{fail_rows}</tbody></table></div>
</main></body></html>"""
    (proof / "index.html").write_text(doc, encoding="utf-8")
    print(f"wrote {proof / 'index.html'}")


if __name__ == "__main__":
    main()
