from __future__ import annotations
import pytest
from src.processors.video_upscaler import VideoUpscalerProcessor
from src.exceptions import UpscalingError


class TestInit:
    def test_raises_when_model_file_missing(self, settings):
        """Validación temprana: falla antes de descargar o procesar frames."""
        with pytest.raises(UpscalingError, match="Modelo no encontrado"):
            VideoUpscalerProcessor(settings)

    def test_raises_with_correct_context(self, settings):
        with pytest.raises(UpscalingError) as exc_info:
            VideoUpscalerProcessor(settings)
        assert "model_path" in exc_info.value.context

    def test_succeeds_when_model_exists(self, settings_with_model):
        proc = VideoUpscalerProcessor(settings_with_model)
        assert proc.name == "video_upscaler"

    def test_processor_name(self, settings_with_model):
        proc = VideoUpscalerProcessor(settings_with_model)
        assert proc.name == "video_upscaler"
