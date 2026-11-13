# VoiceShell — Interface Control Document (ICD)

| Field | Value |
|---|---|
| Document ID | VS-ICD-001 |
| Version | 1.0 |
| Status | **Normative** — this document is the single source of truth for all inter-process contracts |
| Audience | Every engineer on the team, in every language |
| Last updated | 2026-09-04 |
| Related | [PRD](01-PRD.md) · [SAD/HLD](02-SAD-HLD.md) · [Extreme Architecture](02X-ARCHITECTURE-EXTREME.md) · [Threat Model](04-THREAT-MODEL.md) |

---

## 0. Why this document exists, and the rule that makes it work

Four people are building eleven processes in two languages. Without a contract, they will
build eleven incompatible things and discover it in month five. This document is the
contract.

> ### The Prime Rule
>
> **Schemas are defined once, in `src/voiceshell/contracts/`, as Pydantic models.**
> JSON Schema and Rust `serde` structs are **generated** from them at build time.
> Nobody hand-writes a struct on either side. If the generated artefacts drift from the
> source, CI fails.
>
> **A message that does not validate is dropped and logged. It is never "handled
> leniently".** Leniency at an interface boundary is how a malformed plan becomes an
> executed command.

### Transport

| Property | Value |
|---|---|
| Mechanism | Unix domain sockets, `SOCK_SEQPACKET` |
| Location | `$XDG_RUNTIME_DIR/voiceshell/<component>.sock`, mode `0600` |
| Serialisation | MessagePack (canonical), JSON (debug builds only) |
| Framing | 4-byte big-endian length prefix, then the payload |
| Max frame | 4 MiB — a larger message is a bug, not a large message |
| Network | **None. Ever.** No component may create a socket in `AF_INET`/`AF_INET6`. Enforced by seccomp on every process. |

### Envelope — every message on every socket

```jsonc
{
  "v":        1,                        // contract major version
  "id":       "01J8Q2...",              // ULID, unique per message
  "turn_id":  "01J8Q2...",              // ULID, groups a whole user turn
  "step":     2,                        // step index within the turn, 0-based
  "ts":       1757001600123456,         // microseconds since epoch, CLOCK_REALTIME
  "src":      "planner",                // sending component
  "dst":      "gate",                   // intended recipient
  "kind":     "PlanProposal",           // payload type, selects the schema
  "trace":    "8f3a2c...",              // OpenTelemetry trace id
  "payload":  { }                       // schema per "kind"
}
```

**`turn_id` is the join key across every log, trace, and audit record in the system.**
Anything that cannot be attributed to a turn is a bug.

---

## 1. Contract map

```
  vsd-audio ──── AudioSegment ────────────► vsd-asr-stream
       │                                          │
       │                                    PartialTranscript
       │                                          │
       └──── AudioSegment ──────────────────► vsd-asr-rescore
                                                  │
                                            FinalTranscript
                                                  │
                                                  ▼
                                            vsd-planner
                                                  │
       ┌──────────────────────────────────────────┤
       │                                          │
  ContextBundle (internal)              PlanProposal
       │                                          │
       │                                          ▼
       │                                     vsd-gate
       │                                          │
       │                                   RiskVerdict
       │                                          │
       │                              ┌───────────┴───────────┐
       │                              │                       │
       │                     ConfirmationRequest       ExecutionRequest
       │                              │                       │
       │                              ▼                       ▼
       │                        vsd-voice              vsd-exec-pool
       │                              │                       │
       │                     ConfirmationResponse      ExecutionResult
       │                              │                       │
       │                              └───────────┬───────────┘
       │                                          ▼
       │                                   Observation (sanitised)
       │                                          │
       └──────────────────────────────────────────┘
                          (loop back to planner)

  ALL components ──── AuditRecord ────────► vsd-audit   (fire-and-forget, but
                                                          execution BLOCKS on ack)
```

---

## 2. Core value types

Used inside many messages. Defined once here.

### 2.1 `Provenance`

**The most important type in this document.** See [Extreme Architecture §9](02X-ARCHITECTURE-EXTREME.md#9-provenance-taint-tracking).

```jsonc
// Ordered lattice. Lower index = MORE trusted.
// Any join of two labels yields the LESS trusted (higher index) of the two.
"SYSTEM"              // 0 — our own prompt and rules
"USER_SPEECH"         // 1 — what the user actually said
"VERIFIED_FS"         // 2 — paths we resolved and stat'd ourselves
"UNTRUSTED_METADATA"  // 3 — filenames, dir entries, env values
"UNTRUSTED_OUTPUT"    // 4 — stdout/stderr, file contents
```

```jsonc
// A labelled span of text.
{
  "text":       "~/Downloads",
  "provenance": "VERIFIED_FS",
  "span_id":    "ctx.cwd.entries[3]",   // where it came from, for audit
  "offset":     412,                    // byte offset in the assembled prompt
  "length":     11
}
```

> **Invariant P1.** No operation anywhere in the system may produce a span whose
> provenance is more trusted than the least-trusted input it derives from. There is no
> promotion path. There is no "sanitised, therefore trusted".

### 2.2 `Capability` and `Envelope`

See [Extreme Architecture §10](02X-ARCHITECTURE-EXTREME.md#10-the-monotonic-capability-envelope).

```jsonc
// Capability — one operation class.
"READ"              // observe only
"WRITE"             // create or modify, non-destructive
"MKDIR"
"MOVE"
"DELETE_SCOPED"     // delete, restricted to a stated scope
"EXEC_BUILD"        // run build tooling
"EXEC_PKG_MGR"      // run the package manager
"PROC_SIGNAL"       // signal a process
```

```jsonc
// Envelope — the set permitted for this turn.
{
  "caps": ["READ", "WRITE", "DELETE_SCOPED"],
  "scopes": {
    "DELETE_SCOPED": {
      "roots":    ["/var/tmp/build"],   // canonical, symlinks resolved
      "patterns": ["*.log"],
      "max_items": 500,
      "max_bytes": 2147483648
    }
  },
  "derived_from": "USER_SPEECH",        // MUST be USER_SPEECH. No other value is legal.
  "utterance_conf": 0.94,
  "contracted": [                       // append-only contraction history
    {"step": 2, "removed": ["DELETE_SCOPED"], "reason": "injection_detected"}
  ]
}
```

> **Invariant E1 (monotonicity).** For any turn, `caps(step n+1) ⊆ caps(step n)`.
> The gate rejects any envelope update that adds a capability. This is checked on every
> message, not merely on transitions.
>
> **Invariant E2 (derivation).** `derived_from` must be `USER_SPEECH`. An envelope derived
> from anything else is a protocol violation and terminates the turn.

### 2.3 `RiskTier`

```jsonc
"READ"          // cannot alter state           → no confirmation
"WRITE"         // alters state, recoverable    → batch confirmation
"DESTRUCTIVE"   // irreversible or high impact  → per-command spoken gate
"FORBIDDEN"     // never executed, no override
```

### 2.4 `ErrorEnvelope`

Every failure response in the system uses this shape. There is no other error format.

```jsonc
{
  "code":       "GATE_TAINT_VIOLATION",   // stable, machine-readable
  "message":    "Command verb originates solely from untrusted output.",
  "component":  "gate",
  "turn_id":    "01J8Q2...",
  "step":       2,
  "retryable":  false,
  "user_facing":"I won't run that — the instruction came from a file, not from you.",
  "detail":     { }                       // code-specific, never shown to the user
}
```

**Error code registry** (exhaustive; adding a code requires a contract version bump):

| Code | Component | Retryable | Meaning |
|---|---|---|---|
| `AUDIO_DEVICE_LOST` | audio | yes | Microphone disappeared |
| `AUDIO_OVERRUN` | audio | yes | Ring buffer overrun; frames dropped |
| `ASR_LOW_CONFIDENCE` | asr | yes | Below threshold; ask the user to repeat |
| `ASR_TRUNCATED` | asr | yes | Endpoint fired mid-utterance |
| `ASR_BACKEND_DOWN` | asr | yes | Engine crashed; supervisor restarting |
| `ROUTE_OUT_OF_SCOPE` | planner | no | Not a machine-control request |
| `ROUTE_AMBIGUOUS` | planner | yes | Needs clarification |
| `CONTEXT_BUDGET_EXCEEDED` | planner | no | Curation failed to fit the budget |
| `PLAN_ALL_TIERS_ABSTAINED` | planner | no | No tier was confident enough |
| `PLAN_MODEL_UNAVAILABLE` | planner | yes | Model process down; degraded mode |
| `GATE_PARSE_FAILURE` | gate | no | Unparseable — **fails closed to FORBIDDEN** |
| `GATE_FORBIDDEN` | gate | no | Matched a forbidden rule |
| `GATE_PATH_ESCAPE` | gate | no | Path resolves outside the workspace root |
| `GATE_TAINT_VIOLATION` | gate | no | Provenance rule T1/T2/T3 fired |
| `GATE_ENVELOPE_VIOLATION` | gate | no | Operation outside the turn envelope |
| `GATE_ENVELOPE_GROWTH` | gate | no | **Protocol violation** — someone tried to widen an envelope |
| `CONFIRM_DENIED` | gate | no | User said no |
| `CONFIRM_TIMEOUT` | gate | no | No response within the window → cancel |
| `CONFIRM_AMBIGUOUS` | gate | no | Response was not a clear yes → cancel |
| `EXEC_TIMEOUT` | exec | no | Wall-clock limit hit; process group killed |
| `EXEC_NO_SANDBOX` | exec | no | **Fail-closed: no sandbox, no execution** |
| `EXEC_POOL_EXHAUSTED` | exec | yes | All workers busy |
| `EXEC_OOM` | exec | no | cgroup memory limit hit |
| `SANITISE_INJECTION_DETECTED` | exec | no | Payload quarantined; envelope contracts |
| `AUDIT_UNAVAILABLE` | audit | no | **Fail-closed: no log, no execution** |
| `AUDIT_CHAIN_BROKEN` | audit | no | Integrity verification failed — halt everything |

---

## 3. Message schemas

### 3.1 `AudioSegment` — audio → asr

```jsonc
{
  "kind": "AudioSegment",
  "payload": {
    "session":     "01J8Q2...",
    "seq":         14,                  // monotonic within a session
    "final":       false,               // true on the endpoint frame
    "sample_rate": 16000,               // always 16 kHz mono
    "encoding":    "pcm_s16le",
    "pcm_ref":     "/dev/shm/vs-aud-01J8Q2",  // shared memory, NOT inline
    "byte_offset": 51200,
    "byte_len":    5120,
    "vad": {
      "speech_prob":   0.97,
      "silence_ms":    0,
      "endpoint_conf": 0.12             // adaptive endpointer's P(complete)
    },
    "aec_active": true                  // TTS is playing; echo cancellation engaged
  }
}
```

> Audio travels in shared memory, never inline. A 30-second utterance is 960 KB; copying
> it through the socket four times would cost more than the ASR.

### 3.2 `PartialTranscript` — asr-stream → planner

Emitted every ~80 ms. **This is what makes speculation possible.**

```jsonc
{
  "kind": "PartialTranscript",
  "payload": {
    "session":    "01J8Q2...",
    "seq":        7,
    "text":       "show me the biggest files in",
    "stable_len": 24,                   // bytes unlikely to change; safe to speculate on
    "conf":       0.88,
    "endpoint_prediction": {
      "p_complete":   0.09,
      "recommend_wait_ms": 620
    }
  }
}
```

> **Contract rule S1.** A consumer may speculate only on the first `stable_len` bytes.
> Speculating past `stable_len` is a bug, and the divergence rate will show it.

### 3.3 `FinalTranscript` — asr-rescore → planner

```jsonc
{
  "kind": "FinalTranscript",
  "payload": {
    "turn_id":  "01J8Q2...",
    "raw":      "show me the biggest files in downloads",
    "normalised": "show me the biggest files in ~/Downloads",
    "normalisation_trace": [
      {"from": "downloads", "to": "~/Downloads",
       "rule": "path_ground_snap", "edit_distance": 0, "case_corrected": true}
    ],
    "words": [
      {"w": "show",     "conf": 0.99, "t0": 0.00, "t1": 0.21},
      {"w": "downloads","conf": 0.87, "t0": 1.42, "t1": 1.98}
    ],
    "mean_conf":     0.94,
    "min_word_conf": 0.87,
    "audio_ms":      2140,
    "asr_ms":        34,
    "matched_partial_seq": 7,           // which partial this confirms
    "diverged_at":   null,              // byte offset of divergence, or null
    "provenance":    "USER_SPEECH"      // ALWAYS. This is the trust root.
  }
}
```

> **Contract rule S2.** `provenance` on a `FinalTranscript` is always `USER_SPEECH` and is
> the *only* place that label originates. No other component may mint it.

### 3.4 `ContextBundle` — planner internal, and logged

```jsonc
{
  "kind": "ContextBundle",
  "payload": {
    "turn_id": "01J8Q2...",
    "step":    0,
    "assembled_at": 1757001600123456,
    "segments": {                       // mutation-ordered; see Extreme Arch §7.1
      "A_system":   {"tokens": 780, "hash": "sha256:a1b2…", "provenance": "SYSTEM"},
      "B_session":  {"tokens": 140, "hash": "sha256:c3d4…", "provenance": "SYSTEM"},
      "C_slow":     {"tokens":  90, "hash": "sha256:e5f6…", "provenance": "VERIFIED_FS"},
      "D_volatile": {"tokens": 400, "hash": "sha256:0718…", "provenance": "UNTRUSTED_METADATA"},
      "E_untrusted":{"tokens":   0, "hash": null,           "provenance": "UNTRUSTED_OUTPUT"},
      "F_utterance":{"tokens":  25, "hash": "sha256:99aa…", "provenance": "USER_SPEECH"}
    },
    "spans": [ /* array of ProvenanceSpan, see §2.1 — the taint map */ ],
    "cwd":   "/home/kiran/Downloads",
    "budget": {"limit": 1150, "used": 1435, "dropped": 285, "truncated": ["D_volatile"]},
    "collectors": {
      "cwd":     {"ok": true,  "ms": 8,  "entries": 47},
      "history": {"ok": true,  "ms": 2,  "entries": 15},
      "proc":    {"ok": true,  "ms": 10},
      "env":     {"ok": true,  "ms": 1,  "allowlisted_only": true},
      "os":      {"ok": true,  "ms": 0,  "cached": true},
      "entity":  {"ok": true,  "ms": 5,  "entries": 3},
      "error":   {"ok": true,  "ms": 0,  "present": false}
    },
    "speculative": true,                // assembled before the final transcript
    "kv_prefix_reused_tokens": 1010
  }
}
```

> **Contract rule C1.** `segments` must appear in the order A→F. The order is a cache
> optimisation *and* a security property: untrusted content (E) never precedes stable
> content, so it can never enter a reusable KV prefix.

### 3.5 `PlanProposal` — planner → gate

**The most safety-critical message in the system.**

```jsonc
{
  "kind": "PlanProposal",
  "payload": {
    "turn_id": "01J8Q2...",
    "step":    0,
    "tier":    2,                       // which cascade tier produced this: 0|1|2|3
    "speculative": false,               // true = do NOT execute if WRITE or worse

    "reasoning": "list biggest in Downloads",   // ≤ 20 tokens, grammar-enforced
    "command":   "du -ah ~/Downloads | sort -rh | head -20",
    "done":      true,

    "arg_provenance": [                 // REQUIRED. Gate refuses without it.
      {"arg": "~/Downloads", "span_id": "ctx.F.utterance[5]",
       "provenance": "USER_SPEECH", "match": "exact"},
      {"arg": "20",          "span_id": null,
       "provenance": "MODEL",   "match": "none"}
    ],

    "envelope":  { /* Envelope, §2.2 */ },

    "router": {
      "tier_attempted": [0, 1, 2],
      "abstentions": [
        {"tier": 0, "reason": "slot_unresolved", "conf": 0.71},
        {"tier": 1, "reason": "intent_shape_unknown", "conf": 0.62}
      ],
      "chosen_conf":  0.91,
      "calibrated":   true
    },

    "gen": {
      "model":  "qwen2.5-coder-7b-instruct-q4_k_m",
      "draft":  "qwen2.5-coder-0.5b-q4_k_m",
      "grammar_sha": "sha256:44ff…",
      "tokens_generated": 41,
      "spec_accept_rate": 0.84,
      "prefill_ms": 41, "gen_ms": 327,
      "seed": 20260904            // deterministic replay
    }
  }
}
```

> **Contract rule G1.** The gate **rejects** any `PlanProposal` lacking `arg_provenance`
> or `envelope`. There is no default and no inference. A proposal that does not state its
> provenance cannot be evaluated for safety, so it is refused.
>
> **Contract rule G2.** `risk` is **not** a field. The model never states risk
> ([ADR-01](02-SAD-HLD.md#2-key-architectural-decisions)). A proposal containing a risk
> field is a protocol violation and is logged as a possible compromise of the planner.

### 3.6 `RiskVerdict` — gate → planner / exec

```jsonc
{
  "kind": "RiskVerdict",
  "payload": {
    "turn_id": "01J8Q2...", "step": 0,
    "command": "du -ah ~/Downloads | sort -rh | head -20",
    "command_sha": "sha256:7c1e…",      // binds the verdict to EXACTLY this string

    "tier": "READ",
    "decision": "ALLOW",                // ALLOW | CONFIRM | REFUSE

    "checks": {
      "parse":     {"ok": true, "ast_nodes": 11},
      "rules":     {"ok": true, "matched": ["read.du", "read.sort", "read.head"]},
      "paths":     {"ok": true, "resolved": ["/home/kiran/Downloads"],
                    "escapes": []},
      "taint":     {"ok": true, "verb_provenance": "USER_SPEECH",
                    "worst_arg_provenance": "USER_SPEECH"},
      "envelope":  {"ok": true, "required": "READ", "permitted": ["READ","WRITE"]}
    },

    "confirmation": null,               // populated when decision = CONFIRM
    "refusal": null,                    // ErrorEnvelope when decision = REFUSE

    "gate_ms": 15,
    "gate_version": "1.4.2",
    "ruleset_sha": "sha256:be31…"       // which rules produced this verdict
  }
}
```

**When `decision = CONFIRM`:**

```jsonc
"confirmation": {
  "mode": "spoken_per_command",         // spoken_per_command | batch | none
  "preview_method": "shadow_execution", // shadow_execution | enumeration
  "effect": {
    "deletes":  {"count": 12, "bytes": 356515840},
    "modifies": {"count": 0,  "bytes": 0},
    "creates":  {"count": 0,  "bytes": 0},
    "roots":    ["/var/tmp/build"],
    "notable":  [
      {"path": "/var/tmp/build/link.log", "note": "symlink outside root; not followed"},
      {"path": "/var/tmp/build/app.log",  "note": "modified today"}
    ],
    "exact": true                       // true = shadow-executed, this IS what happens
  },
  "prompt_text": "That will permanently delete 12 files, 340 megabytes, in /var/tmp/build. One is a symlink pointing outside the folder, which I will not follow. Shall I proceed?",
  "timeout_ms": 20000,
  "barge_in_locked_ms": 400
}
```

> **Contract rule V1.** `command_sha` binds the verdict to the exact command string.
> The executor **recomputes it** and refuses on mismatch. A verdict cannot be transplanted
> onto a different command — this closes the time-of-check-to-time-of-use gap.
>
> **Contract rule V2.** `"exact": false` means the preview is an estimate, and the spoken
> prompt **must** say so.

### 3.7 `ExecutionRequest` — gate → exec

**Only the gate may send this. The planner cannot reach the executor's socket** —
enforced by socket permissions and verified in CI.

```jsonc
{
  "kind": "ExecutionRequest",
  "payload": {
    "turn_id": "01J8Q2...", "step": 0,
    "command":     "du -ah ~/Downloads | sort -rh | head -20",
    "command_sha": "sha256:7c1e…",      // MUST match; executor recomputes
    "verdict_ref": "01J8Q2VERDICT…",    // the RiskVerdict that authorised this
    "audit_ref":   "01J8Q2AUDIT…",      // the audit record written BEFORE this send

    "mode": "normal",                   // normal | shadow | speculative
    "cwd":  "/home/kiran/Downloads",

    "sandbox": {
      "workspace_root": "/home/kiran",
      "writable":       ["/home/kiran/Downloads"],
      "readonly":       ["/usr", "/bin", "/lib", "/lib64", "/etc/alternatives"],
      "network":        false,          // ALWAYS false. No exceptions exist.
      "seccomp_profile":"default-v3",
      "cgroup": {"memory_max": 2147483648, "pids_max": 256, "cpu_max": "200000 100000"}
    },
    "timeout_ms":  30000,
    "max_output":  4194304,
    "worker_hint": "pool"               // pool | shadow | speculative
  }
}
```

> **Contract rule X1.** The executor **refuses** a request whose `audit_ref` does not
> resolve to a committed audit record. This mechanises invariant I-2: nothing runs
> unlogged, and it is the executor — not the caller — that verifies it.
>
> **Contract rule X2.** `mode: "shadow"` and `mode: "speculative"` force an overlay whose
> upper layer is **always discarded**. The executor rejects any attempt to commit one.

### 3.8 `ExecutionResult` — exec → gate → planner

```jsonc
{
  "kind": "ExecutionResult",
  "payload": {
    "turn_id": "01J8Q2...", "step": 0,
    "exit_code":  0,
    "signal":     null,
    "duration_ms": 108,
    "timed_out":  false,
    "truncated":  false,
    "worker": {"id": "pool-2", "prewarmed": true, "retired_after": false},
    "raw_ref":    "/dev/shm/vs-out-01J8Q2",   // pre-sanitisation, for audit only
    "raw_bytes":  1840,
    "fs_diff":    null                        // populated in shadow mode
  }
}
```

**In shadow mode, `fs_diff` carries the ground truth:**

```jsonc
"fs_diff": {
  "deleted":  [{"path": "…/a.log", "bytes": 40213, "mtime": 1756900000}],
  "created":  [],
  "modified": [],
  "total": {"deleted": 12, "bytes_freed": 356515840},
  "anomalies": ["symlink_outside_root:/var/tmp/build/link.log"]
}
```

### 3.9 `Observation` — exec → planner

**The output of the injection defence. This is the message that must never carry an
instruction.**

```jsonc
{
  "kind": "Observation",
  "payload": {
    "turn_id": "01J8Q2...", "step": 0,
    "source_command": "cat notes.txt",
    "exit_code": 0,

    "fence_nonce": "a7f3e91c4b20d8e5",  // fresh per turn; content cannot forge it
    "content": "<<<UNTRUSTED_OUTPUT nonce=\"a7f3e91c4b20d8e5\">>>\nMeeting notes.\n[REDACTED: 94 bytes matched injection pattern \"role_marker\"]\nMore notes.\n<<<END_UNTRUSTED_OUTPUT nonce=\"a7f3e91c4b20d8e5\">>>",

    "provenance": "UNTRUSTED_OUTPUT",   // ALWAYS. Never anything else.

    "sanitisation": {
      "ansi_stripped":   12,
      "control_stripped": 3,
      "bidi_stripped":    0,
      "invalid_utf8_replaced": 0,
      "original_bytes": 4021,
      "kept_bytes":     3900,
      "elided_middle":  true,
      "suspicious":     true,
      "findings": [
        {"class": "PI-1", "pattern": "role_marker",
         "offset": 118, "length": 94, "action": "redacted"}
      ]
    },

    "envelope_effect": {
      "contract_to": ["READ"],          // injection detected → envelope contracts
      "reason": "injection_detected"
    }
  }
}
```

> **Contract rule O1.** `provenance` is always `UNTRUSTED_OUTPUT`. There is no code path
> that produces an `Observation` with any other label.
>
> **Contract rule O2.** When `sanitisation.suspicious` is true, `envelope_effect` **must**
> be present and must contract. The planner applies the contraction before its next
> proposal; the gate independently verifies it was applied. Two components must agree, so
> a single compromised one cannot skip it.

### 3.10 `ConfirmationRequest` / `ConfirmationResponse`

```jsonc
// gate → voice
{
  "kind": "ConfirmationRequest",
  "payload": {
    "turn_id": "01J8Q2...", "step": 1,
    "prompt_text": "That will permanently delete 12 files, 340 megabytes, in /var/tmp/build. Shall I proceed?",
    "verdict_ref": "01J8Q2VERDICT…",
    "timeout_ms":  20000,
    "barge_in_locked_ms": 400,
    "accept": ["yes", "yeah", "go ahead", "do it", "confirm", "proceed"],
    "reject": ["no", "stop", "cancel", "wait", "don't", "nevermind"]
  }
}
```

```jsonc
// voice → gate
{
  "kind": "ConfirmationResponse",
  "payload": {
    "turn_id": "01J8Q2...", "step": 1,
    "verdict_ref": "01J8Q2VERDICT…",    // MUST match; a stale response is discarded
    "outcome": "APPROVED",              // APPROVED | DENIED | AMBIGUOUS | TIMEOUT
    "heard":   "yes",
    "asr_conf": 0.97,
    "elapsed_ms": 2140
  }
}
```

> **Contract rule F1.** Only `outcome: "APPROVED"` with `asr_conf ≥ 0.85` permits
> execution. `AMBIGUOUS`, `TIMEOUT`, `DENIED`, **and `APPROVED` below the confidence
> threshold all cancel.** The default is always cancel; approval must be affirmative and
> confident.
>
> **Contract rule F2.** `verdict_ref` must match the pending verdict. A response arriving
> after a different verdict has been raised is discarded, not applied. This prevents a
> "yes" intended for one prompt from authorising another.

### 3.11 `AuditRecord` — everything → audit

```jsonc
{
  "kind": "AuditRecord",
  "payload": {
    "chain_index": 48291,
    "prev_hash":   "sha256:be31…",
    "record_hash": "sha256:7c1e…",      // SHA256(prev_hash || canonical(body))
    "body": {
      "turn_id": "01J8Q2...", "step": 0,
      "event":   "EXECUTION_AUTHORISED",
      "ts":      1757001600123456,
      "component": "gate",
      "data": {
        "command":     "du -ah ~/Downloads | sort -rh | head -20",
        "command_sha": "sha256:7c1e…",
        "tier": "READ", "decision": "ALLOW",
        "envelope": ["READ", "WRITE"],
        "taint": {"verb": "USER_SPEECH", "worst_arg": "USER_SPEECH"},
        "ruleset_sha": "sha256:be31…",
        "gate_version": "1.4.2"
      }
    }
  }
}
```

**Event registry** (exhaustive):

```
TURN_STARTED           WAKE_DETECTED          UTTERANCE_CAPTURED
TRANSCRIPT_FINAL       INTENT_ROUTED          CONTEXT_ASSEMBLED
TIER_ABSTAINED         PLAN_PROPOSED          RISK_CLASSIFIED
TAINT_VIOLATION        ENVELOPE_CONTRACTED    ENVELOPE_VIOLATION
CONFIRMATION_ASKED     CONFIRMATION_ANSWERED  EXECUTION_AUTHORISED
EXECUTION_STARTED      EXECUTION_COMPLETED    OUTPUT_SANITISED
INJECTION_DETECTED     RESULT_REPORTED        TURN_ENDED
DEGRADED_MODE_ENTERED  TRAINER_TEMPLATE_ADDED TRAINER_LORA_ACTIVATED
POLICY_CHANGED         CHAIN_VERIFIED
```

> **Contract rule A1.** `EXECUTION_AUTHORISED` must be **committed and acknowledged**
> before the corresponding `ExecutionRequest` is sent. The executor verifies `audit_ref`
> independently (rule X1). Two components enforce it.
>
> **Contract rule A2.** If the audit service is unreachable, the gate emits
> `AUDIT_UNAVAILABLE` and **refuses all execution**. This is fail-closed and there is no
> configuration flag to disable it.

---

## 4. Versioning and compatibility

### Version semantics

```
  v = MAJOR only in the wire envelope.
  Full version tracked in the repository as MAJOR.MINOR.PATCH.

  PATCH  documentation, comments                       — no code change
  MINOR  new OPTIONAL field, or a new enum value in a
         non-safety-critical position                  — old readers keep working
  MAJOR  removed field, renamed field, changed type,
         changed semantics, ANY change to a
         safety-critical field                         — lockstep upgrade required
```

### Safety-critical fields

Changing any of these is **always** a MAJOR bump, even to add an optional field:

```
  PlanProposal.arg_provenance        PlanProposal.envelope
  RiskVerdict.tier                   RiskVerdict.decision
  RiskVerdict.command_sha            RiskVerdict.confirmation.effect
  ExecutionRequest.command_sha       ExecutionRequest.audit_ref
  ExecutionRequest.sandbox.*         Observation.provenance
  Observation.fence_nonce            ConfirmationResponse.outcome
  AuditRecord.*                      Envelope.caps / .scopes / .derived_from
```

### Compatibility rules

1. **Unknown fields are rejected, not ignored** (`extra="forbid"` in Pydantic,
   `deny_unknown_fields` in serde). An unexpected field means a version mismatch, and
   silently ignoring it is how safety fields get dropped.
2. **Unknown enum values are rejected.** Never coerce to a default. A gate that sees an
   unrecognised risk tier must refuse, not guess.
3. **The supervisor refuses to start** if any component reports a mismatched contract
   major version. Partial upgrades are not permitted.
4. **Generated artefacts are committed** and CI verifies they match the Pydantic source.
   A drifted generated struct fails the build.

---

## 5. Component ownership and socket permissions

The socket topology *is* the security boundary. It is enforced by the operating system,
not by convention.

| Socket | Owner | May connect | Enforcement |
|---|---|---|---|
| `audio.sock` | audio | asr-stream, asr-rescore | mode 0600, same uid |
| `asr.sock` | asr | planner | mode 0600 |
| `planner.sock` | planner | asr, gate, exec (results only) | mode 0600 |
| **`gate.sock`** | gate | **planner only** | mode 0600 + `SO_PEERCRED` pid check |
| **`exec.sock`** | exec-pool | **gate only** | mode 0600 + `SO_PEERCRED` pid check |
| `voice.sock` | voice | gate, planner | mode 0600 |
| `audit.sock` | audit | all | mode 0600, append-only protocol |
| `memory.sock` | memory | planner, gate (read-only) | mode 0600 |

> **The two bold rows are the architecture's safety boundary made physical.**
> The planner cannot open `exec.sock` — not because it chooses not to, but because the
> executor verifies the peer's process identity via `SO_PEERCRED` and rejects anyone but
> the gate. A fully compromised planner still cannot execute anything. It can only
> propose, and proposals go to the gate.

### CI enforcement

```
  ✓ import-linter : voiceshell.gate imports nothing from voiceshell.planner.llm
  ✓ linker audit  : vsd-gate links no inference library
  ✓ seccomp check : every process denies socket(AF_INET|AF_INET6)
  ✓ peercred test : planner attempting exec.sock connection is REFUSED
  ✓ schema drift  : generated Rust/JSON Schema match the Pydantic source
  ✓ contract test : every message type round-trips Python → Rust → Python identically
```

---

## 6. Worked trace — one complete turn

Every message for a single destructive turn, in order. This is the reference example; new
team members should read it before writing any code.

```
 1.  audio  → asr      AudioSegment        seq 0..26, final=true
 2.  asr    → planner  PartialTranscript   seq 5  "delete all the log"  stable_len=18
 3.  planner internal  ContextBundle       speculative=true (assembly begins early)
 4.  asr    → planner  FinalTranscript     "delete all the log files in here"
                                            mean_conf=0.94  provenance=USER_SPEECH
 5.  planner internal  Envelope derived    caps=[READ, DELETE_SCOPED]
                                            scope: roots=[/var/tmp/build] patterns=[*.log]
                                            derived_from=USER_SPEECH
 6.  planner internal  Router              tier 0 abstains (destructive — structurally
                                            cannot emit), tier 1 abstains, tier 2 selected
 7.  planner → gate    PlanProposal        tier=2  command="rm -f *.log"
                                            arg_provenance=[{"*.log", USER_SPEECH}]
 8.  gate   internal   parse               ast_nodes=4  ok
 9.  gate   internal   classify            tier=DESTRUCTIVE  rules=[destructive.rm]
10.  gate   internal   paths               resolved=[/var/tmp/build]  escapes=[]
11.  gate   internal   taint               verb=USER_SPEECH  worst_arg=USER_SPEECH  ok
12.  gate   internal   envelope            need DELETE_SCOPED ∈ caps  ok
                                            scope check: 12 items ≤ 500, 340 MB ≤ 2 GB  ok
13.  gate   → exec     ExecutionRequest    mode=shadow  (preview, overlay discarded)
14.  exec   → gate     ExecutionResult     fs_diff: 12 deleted, 340 MB,
                                            anomaly: symlink outside root
15.  gate   → audit    AuditRecord         CONFIRMATION_ASKED             [committed]
16.  gate   → voice    ConfirmationRequest "That will permanently delete 12 files,
                                            340 megabytes, in /var/tmp/build. One is a
                                            symlink pointing outside the folder, which I
                                            will not follow. Shall I proceed?"
17.  voice  → gate     ConfirmationResponse outcome=APPROVED  heard="yes"  conf=0.97
18.  gate   → audit    AuditRecord         EXECUTION_AUTHORISED           [committed, acked]
19.  gate   → exec     ExecutionRequest    mode=normal  audit_ref=<18>
20.  exec   internal   verify audit_ref committed ✓   verify command_sha matches ✓
21.  exec   → gate     ExecutionResult     exit=0  duration=41 ms  worker=pool-5
                                            worker retired (ran DESTRUCTIVE)
22.  exec   → planner  Observation         provenance=UNTRUSTED_OUTPUT  suspicious=false
23.  planner→ voice    (summary)           "Done. Deleted 12 files, freed 340 megabytes."
24.  all    → audit    AuditRecord         EXECUTION_COMPLETED, TURN_ENDED
```

**Note steps 13–14.** The confirmation prompt at step 16 is not an estimate. It is a
report of what a real execution actually did in a discarded overlay. The user is told the
truth because the system measured it.

---

## Appendix A — Quick reference

| Message | From → To | Safety-critical fields |
|---|---|---|
| `AudioSegment` | audio → asr | — |
| `PartialTranscript` | asr → planner | `stable_len` |
| `FinalTranscript` | asr → planner | `provenance` |
| `ContextBundle` | planner internal | `spans`, segment order |
| `PlanProposal` | planner → gate | `arg_provenance`, `envelope` |
| `RiskVerdict` | gate → planner/exec | `tier`, `decision`, `command_sha` |
| `ExecutionRequest` | **gate → exec only** | `command_sha`, `audit_ref`, `sandbox` |
| `ExecutionResult` | exec → gate | `fs_diff` |
| `Observation` | exec → planner | `provenance`, `fence_nonce` |
| `ConfirmationRequest` | gate → voice | `verdict_ref`, `timeout_ms` |
| `ConfirmationResponse` | voice → gate | `outcome`, `verdict_ref` |
| `AuditRecord` | all → audit | everything |

## Appendix B — The eight rules a new engineer must know

```
  1.  Schemas are generated from contracts/, never hand-written.
  2.  Invalid message → drop and log. Never handle leniently.
  3.  Provenance never increases. There is no path to more trust.
  4.  Envelopes never grow. Only shrink.
  5.  The model never states risk. The gate decides.
  6.  Nothing executes without a committed audit record.
  7.  Only the gate may talk to the executor. Verified by peercred.
  8.  A missing safety field is a refusal, not a default.
```

## Document Change Log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-09-04 | Initial contract, aligned to the extreme architecture |
