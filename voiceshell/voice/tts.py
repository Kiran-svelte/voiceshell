"""Speech out (deck L7): Piper neural TTS (espeak-ng phonemes) + the CLI lexicon. Offline.
Falls back to the built-in Windows voices if the Piper model is missing."""
from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT
from .lexicon import speakable

PIPER_MODEL = PROJECT_ROOT / "models" / "piper" / "en_US-lessac-medium.onnx"
_piper = None


def _piper_voice():
    global _piper
    if _piper is None and PIPER_MODEL.exists():
        try:
            from piper import PiperVoice
            _piper = PiperVoice.load(str(PIPER_MODEL))
        except Exception:  # noqa: BLE001 — fall back to SAPI
            _piper = False
    return _piper or None


def engine_name() -> str:
    return "Piper (en_US-lessac-medium, espeak-ng phonemes)" if _piper_voice() else "Windows SAPI"


def _engine(rate: int = 185):
    import pyttsx3
    e = pyttsx3.init()
    e.setProperty("rate", rate)
    return e


def piper_audio(text: str):
    """Synthesise with Piper → (float32 mono array, sample rate). None if Piper isn't available."""
    import numpy as np
    voice = _piper_voice()
    if not voice:
        return None
    chunks = [c.audio_float_array for c in voice.synthesize(text)]
    if not chunks:
        return None
    return np.concatenate(chunks).astype("float32"), voice.config.sample_rate


def speak(text: str) -> None:
    if not text:
        return
    said = speakable(text)
    out = piper_audio(said)
    if out is not None:
        import sounddevice as sd
        audio, sr = out
        sd.play(audio, sr)
        sd.wait()
        return
    e = _engine()
    e.say(said)
    e.runAndWait()
    e.stop()


def save_wav(text: str, path: Path, voice_index: int = 0, rate: int = 175) -> Path:
    """Render speech to a wav file with the Windows voices (used to create TEST utterances with two different
    speakers; replies to the user go through speak())."""
    e = _engine(rate)
    voices = e.getProperty("voices")
    if voices:
        e.setProperty("voice", voices[voice_index % len(voices)].id)
    e.save_to_file(text, str(path))
    e.runAndWait()
    e.stop()
    return Path(path)
