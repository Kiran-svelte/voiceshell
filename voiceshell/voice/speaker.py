"""P1 Identity & trust (deck slide 9): recognise WHO is speaking and map the voice to a trust level.

Enrolment stores only a 256-number voice fingerprint (d-vector, Resemblyzer encoder, runs offline on CPU) —
never the recording. An unrecognised voice gets the policy's `unknown_voice_trust` (default: novice = read-only).
On Linux the deck maps speakers to Unix UIDs; on Windows a speaker maps to a VoiceShell profile with a trust level.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SR = 16000
THRESHOLD = 0.75          # same voice ≈ 0.93–0.95, different voices ≈ 0.51–0.57 in our measurements


@dataclass
class Identity:
    name: str | None
    trust: str
    score: float

    def describe(self) -> str:
        return f"{self.name} ({self.trust})" if self.name else f"an unrecognised voice ({self.trust})"


class SpeakerID:
    def __init__(self, path: Path, unknown_trust: str = "novice"):
        self.path = path
        self.unknown_trust = unknown_trust
        self._enc = None
        self.profiles = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @property
    def enabled(self) -> bool:
        return bool(self.profiles)

    def _encoder(self):
        if self._enc is None:
            import warnings
            warnings.filterwarnings("ignore")
            from resemblyzer import VoiceEncoder
            self._enc = VoiceEncoder("cpu", verbose=False)
        return self._enc

    def embed(self, audio) -> np.ndarray:
        from resemblyzer import preprocess_wav
        wav = preprocess_wav(Path(audio)) if isinstance(audio, (str, Path)) else preprocess_wav(np.asarray(audio), SR)
        return self._encoder().embed_utterance(wav)

    def enrol(self, name: str, trust: str, samples: list) -> float:
        """Average several utterances into one fingerprint. Returns how consistent the samples were."""
        embs = [self.embed(s) for s in samples]
        mean = np.mean(embs, axis=0)
        mean = mean / np.linalg.norm(mean)
        consistency = float(np.mean([np.dot(e, mean) / np.linalg.norm(e) for e in embs]))
        self.profiles[name] = {"trust": trust, "embedding": [round(float(x), 6) for x in mean],
                               "enrolled": time.strftime("%Y-%m-%d %H:%M"), "samples": len(samples)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.profiles, indent=1), encoding="utf-8")
        return consistency

    def identify(self, audio) -> Identity:
        if not self.profiles:
            return Identity(None, "admin", 1.0)        # speaker ID not set up: no voice-based restriction
        e = self.embed(audio)
        e = e / np.linalg.norm(e)
        best, best_score = None, -1.0
        for name, p in self.profiles.items():
            s = float(np.dot(e, np.asarray(p["embedding"])))
            if s > best_score:
                best, best_score = name, s
        if best_score >= THRESHOLD:
            return Identity(best, self.profiles[best]["trust"], round(best_score, 3))
        return Identity(None, self.unknown_trust, round(best_score, 3))
