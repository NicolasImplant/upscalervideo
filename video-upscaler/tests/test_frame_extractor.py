from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from src.processors.frame_extractor import FrameExtractorProcessor
from src.exceptions import FrameExtractionError
from src.metrics import JobMetrics


def _make_completed_process(returncode=0, stdout="", stderr=""):
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


class TestDetectFps:
    def test_parses_fraction_from_ffprobe(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(stdout="30000/1001\n")):
            fps = proc._detect_fps()
        assert fps == pytest.approx(29.97, abs=0.01)

    def test_parses_integer_fps(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(stdout="30/1\n")):
            fps = proc._detect_fps()
        assert fps == 30.0

    def test_fallback_when_ffprobe_fails(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(returncode=1, stdout="")):
            fps = proc._detect_fps()
        assert fps == float(settings.video_output_fps)

    def test_fallback_when_stdout_empty(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(returncode=0, stdout="")):
            fps = proc._detect_fps()
        assert fps == float(settings.video_output_fps)

    def test_uses_config_fps_when_set(self, tmp_path):
        from tests.conftest import make_settings
        s = make_settings(tmp_path, video_source_fps=24.0)
        proc = FrameExtractorProcessor(s)
        fps = proc._detect_fps()
        assert fps == 24.0


class TestHasAudioStream:
    def test_returns_true_when_stream_found(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(stdout="audio\n")):
            assert proc._has_audio_stream() is True

    def test_returns_false_when_no_output(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(stdout="")):
            assert proc._has_audio_stream() is False

    def test_returns_false_when_ffprobe_fails(self, settings):
        proc = FrameExtractorProcessor(settings)
        with patch("subprocess.run", return_value=_make_completed_process(returncode=1, stdout="")):
            assert proc._has_audio_stream() is False


class TestExtractAudio:
    def test_skips_gracefully_when_no_audio_stream(self, settings):
        proc = FrameExtractorProcessor(settings)
        no_audio = _make_completed_process(stdout="")
        ffmpeg_ok = _make_completed_process()

        with patch("subprocess.run", side_effect=[no_audio, ffmpeg_ok]) as mock_run:
            proc._extract_audio()

        # Solo debería haberse llamado una vez (el ffprobe de detección)
        assert mock_run.call_count == 1

    def test_runs_ffmpeg_when_audio_stream_exists(self, settings):
        proc = FrameExtractorProcessor(settings)
        has_audio = _make_completed_process(stdout="audio\n")
        ffmpeg_ok = _make_completed_process()

        with patch("subprocess.run", side_effect=[has_audio, ffmpeg_ok]) as mock_run:
            proc._extract_audio()

        assert mock_run.call_count == 2


class TestProcessMethod:
    def test_raises_frame_extraction_error_on_ffmpeg_failure(self, settings, tmp_path):
        settings.frames_dir.mkdir(parents=True, exist_ok=True)
        proc = FrameExtractorProcessor(settings)

        ffprobe_fps = _make_completed_process(stdout="30/1\n")
        ffmpeg_fail = _make_completed_process(returncode=1, stderr="error msg")
        no_audio = _make_completed_process(stdout="")

        with patch("subprocess.run", side_effect=[ffprobe_fps, ffmpeg_fail, no_audio]):
            with pytest.raises(FrameExtractionError):
                proc.process(JobMetrics(video_name="v.mp4"))
