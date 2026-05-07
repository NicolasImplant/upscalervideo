from __future__ import annotations
import pytest
from src.exceptions import (
    VideoUpscalerError,
    ConfigurationError,
    StorageError,
    StorageDownloadError,
    StorageUploadError,
    ProcessorError,
    FrameExtractionError,
    UpscalingError,
    AudioEnhancementError,
    VideoAssemblyError,
)


class TestHierarchy:
    def test_configuration_error_is_upscaler_error(self):
        assert issubclass(ConfigurationError, VideoUpscalerError)

    def test_storage_errors_inherit_from_storage_error(self):
        assert issubclass(StorageDownloadError, StorageError)
        assert issubclass(StorageUploadError, StorageError)
        assert issubclass(StorageError, VideoUpscalerError)

    def test_processor_errors_inherit_from_processor_error(self):
        for cls in [FrameExtractionError, UpscalingError, AudioEnhancementError, VideoAssemblyError]:
            assert issubclass(cls, ProcessorError), f"{cls} should inherit ProcessorError"
        assert issubclass(ProcessorError, VideoUpscalerError)


class TestContext:
    def test_base_error_stores_context(self):
        err = VideoUpscalerError("msg", context={"key": "val"})
        assert err.context == {"key": "val"}

    def test_base_error_default_context_is_empty_dict(self):
        err = VideoUpscalerError("msg")
        assert err.context == {}

    def test_processor_error_stores_processor_name(self):
        err = ProcessorError("msg", processor_name="video_upscaler")
        assert err.processor_name == "video_upscaler"

    def test_processor_error_stores_context(self):
        err = FrameExtractionError(
            "ffmpeg failed",
            processor_name="frame_extractor",
            context={"step": "audio_extraction", "returncode": 1},
        )
        assert err.context["step"] == "audio_extraction"
        assert err.processor_name == "frame_extractor"

    def test_upscaling_error_is_catchable_as_processor_error(self):
        with pytest.raises(ProcessorError):
            raise UpscalingError("cuda OOM", processor_name="video_upscaler")

    def test_storage_download_error_is_catchable_as_upscaler_error(self):
        with pytest.raises(VideoUpscalerError):
            raise StorageDownloadError("timeout", context={"blob": "input/v.mp4"})
