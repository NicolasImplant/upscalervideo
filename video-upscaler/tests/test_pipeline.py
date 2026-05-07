from __future__ import annotations
from unittest.mock import MagicMock, patch, call
import pytest
from src.pipeline import VideoPipeline
from src.processors.port import ProcessorResult
from src.exceptions import VideoUpscalerError


def _make_mock_processor(name="mock_proc"):
    p = MagicMock()
    p.name = name
    p.process.return_value = ProcessorResult(success=True, message="ok")
    return p


class TestPipelineOrdering:
    def test_build_pipeline_runs_before_download(self, settings):
        """Regresión: build_pipeline debe ejecutarse antes del download para validar
        recursos (modelo ESRGAN) sin gastar I/O en GCS innecesariamente."""
        call_order: list[str] = []

        mock_storage = MagicMock()
        mock_storage.download.side_effect = lambda *a, **kw: call_order.append("download")
        mock_storage.upload.side_effect = lambda *a, **kw: call_order.append("upload")

        mock_proc = _make_mock_processor()
        mock_proc.process.side_effect = lambda m: (call_order.append("process"), ProcessorResult(success=True, message="ok"))[1]

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.side_effect = lambda: (
                call_order.append("build_pipeline"),
                [mock_proc],
            )[1]

            pipeline = VideoPipeline(settings=settings, storage=mock_storage)
            pipeline.run()

        assert "build_pipeline" in call_order
        assert "download" in call_order
        build_idx = call_order.index("build_pipeline")
        download_idx = call_order.index("download")
        assert build_idx < download_idx, (
            f"build_pipeline (pos {build_idx}) debe ocurrir antes de download (pos {download_idx})"
        )

    def test_processors_run_before_upload(self, settings):
        call_order: list[str] = []

        mock_storage = MagicMock()
        mock_storage.upload.side_effect = lambda *a, **kw: call_order.append("upload")

        mock_proc = _make_mock_processor()
        mock_proc.process.side_effect = lambda m: (call_order.append("process"), ProcessorResult(success=True, message="ok"))[1]

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.return_value = [mock_proc]
            pipeline = VideoPipeline(settings=settings, storage=mock_storage)
            pipeline.run()

        process_idx = call_order.index("process")
        upload_idx = call_order.index("upload")
        assert process_idx < upload_idx


class TestWorkspaceCleanup:
    def test_workspace_cleaned_on_success(self, settings):
        mock_storage = MagicMock()
        mock_proc = _make_mock_processor()

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.return_value = [mock_proc]
            pipeline = VideoPipeline(settings=settings, storage=mock_storage)
            pipeline.run()

        assert not settings.job_tmp_dir.exists()

    def test_workspace_cleaned_on_upscaler_error(self, settings):
        mock_storage = MagicMock()
        mock_storage.download.side_effect = VideoUpscalerError("download failed")

        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.return_value = []
            pipeline = VideoPipeline(settings=settings, storage=mock_storage)

            with pytest.raises(VideoUpscalerError):
                pipeline.run()

        assert not settings.job_tmp_dir.exists()


class TestErrorPropagation:
    def test_re_raises_video_upscaler_error(self, settings):
        mock_storage = MagicMock()

        failing_proc = _make_mock_processor()
        failing_proc.process.side_effect = VideoUpscalerError("processor failed")

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.return_value = [failing_proc]
            pipeline = VideoPipeline(settings=settings, storage=mock_storage)

            with pytest.raises(VideoUpscalerError):
                pipeline.run()

    def test_re_raises_unexpected_exception(self, settings):
        mock_storage = MagicMock()
        mock_storage.download.side_effect = RuntimeError("unexpected")

        with patch("src.pipeline.ProcessorFactory") as MockFactory:
            MockFactory.return_value.build_pipeline.return_value = []
            pipeline = VideoPipeline(settings=settings, storage=mock_storage)

            with pytest.raises(RuntimeError):
                pipeline.run()
