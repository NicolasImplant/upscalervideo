from __future__ import annotations
import sys
from unittest.mock import MagicMock
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Mock de dependencias pesadas — deben estar en sys.modules ANTES de que
# cualquier módulo src.* sea importado por los test files.
# ---------------------------------------------------------------------------

class _FakeGoogleAPIError(Exception):
    """Reemplazo real de GoogleAPIError para testear la lógica de retry."""


_google_api_core_exceptions = MagicMock()
_google_api_core_exceptions.GoogleAPIError = _FakeGoogleAPIError

_heavy_mocks: dict[str, object] = {
    "cv2": MagicMock(),
    "torch": MagicMock(),
    "basicsr": MagicMock(),
    "basicsr.archs": MagicMock(),
    "basicsr.archs.rrdbnet_arch": MagicMock(),
    "realesrgan": MagicMock(),
    "google": MagicMock(),
    "google.cloud": MagicMock(),
    "google.cloud.storage": MagicMock(),
    "google.api_core": MagicMock(),
    "google.api_core.exceptions": _google_api_core_exceptions,
    "google.auth": MagicMock(),
    "google.resumable_media": MagicMock(),
}
for _mod, _mock in _heavy_mocks.items():
    sys.modules.setdefault(_mod, _mock)  # type: ignore[arg-type]

from src.config import Settings  # noqa: E402  (después de los mocks)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(tmp_path: Path, **overrides) -> Settings:
    kwargs: dict = dict(
        gcp_project_id="test-project",
        gcs_bucket_input="test-input",
        gcs_bucket_output="test-output",
        video_name="test_video.mp4",
        tmp_base_dir=tmp_path / "upscaler",
    )
    kwargs.update(overrides)
    return Settings(**kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def settings_with_model(tmp_path: Path) -> Settings:
    model = tmp_path / "model.pth"
    model.touch()
    return make_settings(tmp_path, esrgan_model_path=model)


@pytest.fixture
def fake_google_api_error():
    """Clase de excepción usable en side_effect para simular GoogleAPIError."""
    return _FakeGoogleAPIError
