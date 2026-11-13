"""Hold-to-talk: the microphone is on exactly while a key (Enter by default) is held down.

No pause-based cut-off: you can stop and think mid-sentence. Releasing the key ends the recording
(plus a short tail so the last word isn't clipped). Windows reads the key state with
GetAsyncKeyState, so nothing extra is installed.
"""
from __future__ import annotations

import sys
import time
from typing import Callable

import numpy as np

SR = 16000
BLOCK = int(SR * 0.03)
KEYS = {"enter": 0x0D, "space": 0x20, "ctrl": 0x11, "f8": 0x77}


def available() -> bool:
    return sys.platform == "win32"


def key_is_down(key: str = "enter") -> bool:
    import ctypes
    return bool(ctypes.windll.user32.GetAsyncKeyState(KEYS[key]) & 0x8000)


def drain_typed_keys() -> None:
    """Holding Enter auto-repeats newlines into the console; throw them away so they don't leak into
    the next prompt."""
    try:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    except Exception:  # noqa: BLE001
        pass


class _MicBlocks:
    def __enter__(self):
        import sounddevice as sd
        self.stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", blocksize=BLOCK)
        self.stream.start()
        return self

    def read(self) -> np.ndarray:
        b, _ = self.stream.read(BLOCK)
        return b[:, 0].copy()

    def __exit__(self, *exc):
        self.stream.stop()
        self.stream.close()


def record_while_held(key: str = "enter", max_s: float = 60.0, tail_s: float = 0.3,
                      wait_s: float | None = None, on_state: Callable[[str], None] | None = None,
                      is_down: Callable[[], bool] | None = None, mic_factory=None) -> np.ndarray:
    """Wait for the key to go down, record while it stays down, stop on release.
    Returns an empty array if the key was never pressed within `wait_s` (None = wait forever)."""
    is_down = is_down or (lambda: key_is_down(key))
    on_state = on_state or (lambda s: None)
    mic_factory = mic_factory or _MicBlocks
    t0 = time.time()
    while is_down():                                   # still held from before? wait for a clean press
        time.sleep(0.01)
    while not is_down():
        if wait_s is not None and time.time() - t0 > wait_s:
            return np.zeros(0, dtype=np.float32)
        time.sleep(0.01)
    frames: list[np.ndarray] = []
    on_state("recording")
    with mic_factory() as mic:
        t = 0.0
        while is_down() and t < max_s:
            frames.append(mic.read())
            t += BLOCK / SR
        for _ in range(int(tail_s / (BLOCK / SR))):    # catch the end of the last word
            frames.append(mic.read())
    on_state(f"stopped:{len(frames) * BLOCK / SR:.1f}")
    drain_typed_keys()
    if not frames:
        return np.zeros(0, dtype=np.float32)
    from .vad import denoise                        # deck L1: noise suppression before recognition
    return denoise(np.concatenate(frames))
