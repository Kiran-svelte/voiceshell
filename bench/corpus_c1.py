"""C1 — CLI-domain speech corpus (deck slide 7; test plan §10).

Phase 1 SYNTHETIC BOOTSTRAP (built here): spoken forms of shell requests → synthesised with Piper + two Windows
voices → augmented (noise at SNR 10 dB, speed ±10%) → manifest marked TRAIN ONLY.
Baseline: Whisper small.en on the synthetic set, with and without VoiceShell's CLI vocabulary prompt, scored with
the plan's metrics: WER, PTER (path-token error rate), CVER (command-verb error rate).

The plan is explicit: evaluating on synthetic speech measures the TTS, not people. These baseline numbers are a
pipeline check and a bias-prompt comparison, NOT the published result. Published numbers must come from the
consented human held-out set (Phase 2: `python -m voiceshell corpus-record`).
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "bench" / "out" / "corpus"
SR = 16000

FILES = ["notes dot T X T", "report dash old dot T X T", "todo dot M D", "budget dot C S V",
         "setup dash installer dot zip", "holiday dash video dot M P four", "app dot log", "main