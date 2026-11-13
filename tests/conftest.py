import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voiceshell.config import Config  # noqa: E402
from voiceshell.fixtures import build  # noqa: E402


@pytest.fixture
def cfg(tmp_path) -> Config:
    ws = build(tmp_path / "workspace")
    return Config(workspace=ws, state_dir=tmp_path / "state")
