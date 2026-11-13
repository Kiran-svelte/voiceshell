"""L1 audio front end (deck slides 4, 6, 8): Silero VAD (neural voice-activity detection) + noise suppression.

Silero VAD v6 ships inside faster-whisper, so no download. It is run chunk by chunk (32 ms) on live audio.
Noise suppression: the deck names WebRTC NS, which needs a C++ compiler to install on Windows; spectral-gating
noise reduction (`noisereduce`) is used instead and applied gently, because heavy suppression hurts recognition.
"""
from __future__ import annotations

import os

import numpy as np

SR = 16000
CHUNK = 512            # Silero's window at 16 kHz (32 ms)
_CTX = 64


class StreamingVAD:
    def __init__(self):
        import faster_whisper
        import onnxruntime
        path = os.path.join(os.path.dirname(faster_whisper.__file__), "assets", "silero_vad_v6.onnx")
        opts = onnxruntime.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.log_severity_level = 4
        self.sess = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"], sess_options=opts)
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype="float32")
        self.c = np.zeros((1, 1, 128), dtype="float32")
        self.ctx = np.zeros(_CTX, dtype="float32")

    def prob(self, chunk: np.ndarray) -> float:
        """Speech probability for one 512-sample chunk (state carries across calls)."""
        chunk = np.asarray(chunk, dtype="float32").reshape(-1)[:CHUNK]
        if chunk.size < CHUNK:
            chunk = np.pad(chunk, (0, CHUNK - chunk.size))
        x = np.concatenate([self.ctx, chunk])[None, :]
        out, self.h, self.c = self.sess.run(None, {"input": x, "h": self.h, "c": self.c})
        self.ctx = chunk[-_CTX:]
        return float(np.asarray(out).reshape(-1)[0])


def denoise(audio: np.ndarray, strength: float = 0.6) -> np.ndarray:
    """Gentle stationary noise reduction before speech recognition. Returns the input if unavailable."""
    if audio.size < SR // 4:
        return audio
    try:
        import noisereduce as nr
        return nr.reduce_noise(y=audio, sr=SR, stationary=True, prop_decrease=strength).astype("float32")
    except Exception:  # noqa: BLE001
        return audio
