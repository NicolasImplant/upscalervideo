from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from src.processors.video_assembler import VideoAssemblerProcessor
from src.exceptions import VideoAssemblyError
from src.metrics import JobMetrics


def _ok_process():
    m = MagicMock()
    m.returncode = 0
    return m


def _fail_process(stderr="error"):
    m = MagicMock()
    m.returncode = 1
    m.stderr = stderr
    return m


def _write_output(settings):
    """Crea el output_video_path para que stat() no falle tras el assembly mock."""
    settings.output_video_path.parent.mkdir(parents=True, exist_ok=True)
    settings.output_video_path.write_bytes(b"x" * 1024)


class TestAudioSourceSelection:
    def test_prefers_clean_audio_when_both_exist(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_raw_path.write_bytes(b"raw")
        settings.audio_clean_path.write_bytes(b"clean")
        _write_output(settings)

        proc = VideoAssemblerProcessor(settings)
        captured_cmd: list[str] = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 30.0
        with patch("subprocess.run", side_effect=capture_run):
            proc.process(metrics)

        assert str(settings.audio_clean_path) in captured_cmd

    def test_falls_back_to_raw_when_clean_missing(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_raw_path.write_bytes(b"raw")
        _write_output(settings)

        proc = VideoAssemblerProcessor(settings)
        captured_cmd: list[str] = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 30.0
        with patch("subprocess.run", side_effect=capture_run):
            proc.process(metrics)

        assert str(settings.audio_raw_path) in captured_cmd
        assert str(settings.audio_clean_path) not in captured_cmd

    def test_no_audio_input_when_neither_exists(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        _write_output(settings)

        proc = VideoAssemblerProcessor(settings)
        captured_cmd: list[str] = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 30.0
        with patch("subprocess.run", side_effect=capture_run):
            proc.process(metrics)

        assert str(settings.audio_raw_path) not in captured_cmd
        assert str(settings.audio_clean_path) not in captured_cmd


class TestAssemblyResult:
    def test_returns_success_with_size_mb(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        # ~1 MB de datos
        settings.output_video_path.write_bytes(b"x" * 1_048_576)

        proc = VideoAssemblerProcessor(settings)
        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 30.0

        with patch("subprocess.run", return_value=_ok_process()):
            result = proc.process(metrics)

        assert result.success is True
        assert result.metadata is not None
        assert result.metadata["size_mb"] == pytest.approx(1.0, abs=0.01)

    def test_uses_source_fps_from_metrics(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        _write_output(settings)

        proc = VideoAssemblerProcessor(settings)
        captured_cmd: list[str] = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 23.976

        with patch("subprocess.run", side_effect=capture_run):
            proc.process(metrics)

        fr_idx = captured_cmd.index("-framerate")
        assert captured_cmd[fr_idx + 1] == str(23.976)


class TestErrorHandling:
    def test_raises_video_assembly_error_on_ffmpeg_failure(self, settings):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)

        proc = VideoAssemblerProcessor(settings)
        metrics = JobMetrics(video_name="v.mp4")
        metrics.source_fps = 30.0

        with patch("subprocess.run", return_value=_fail_process(stderr="encode error")):
            with pytest.raises(VideoAssemblyError):
                proc.process(metrics)
