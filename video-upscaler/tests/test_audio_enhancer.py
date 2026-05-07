from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest
from src.processors.audio_enhancer import AudioEnhancerProcessor
from src.processors.port import ProcessorResult
from src.exceptions import AudioEnhancementError
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


class TestSkipWhenNoAudio:
    def test_returns_success_when_audio_raw_missing(self, settings):
        proc = AudioEnhancerProcessor(settings)
        # audio_raw_path no existe en tmp_path
        result = proc.process(JobMetrics(video_name="v.mp4"))
        assert result.success is True
        assert "omitido" in result.message.lower() or "sin audio" in result.message.lower()

    def test_does_not_call_ffmpeg_when_audio_missing(self, settings):
        proc = AudioEnhancerProcessor(settings)
        with patch("subprocess.run") as mock_run:
            proc.process(JobMetrics(video_name="v.mp4"))
        mock_run.assert_not_called()


class TestAudioFilter:
    def test_filter_string_includes_anlmdn(self, settings, tmp_path):
        # Crear audio_raw para que el procesador lo intente
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_raw_path.write_bytes(b"fake audio")

        proc = AudioEnhancerProcessor(settings)
        captured_cmd = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        with patch("subprocess.run", side_effect=capture_run):
            proc.process(JobMetrics(video_name="v.mp4"))

        af_value = next(
            (captured_cmd[i + 1] for i, v in enumerate(captured_cmd) if v == "-af"),
            None,
        )
        assert af_value is not None
        assert "anlmdn" in af_value
        assert "equalizer" in af_value

    def test_filter_uses_config_params(self, tmp_path):
        from tests.conftest import make_settings
        s = make_settings(tmp_path, audio_denoiser_strength=10, audio_eq_gain_db=5)
        s.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        s.audio_raw_path.write_bytes(b"fake audio")

        proc = AudioEnhancerProcessor(s)
        captured_cmd = []

        def capture_run(cmd, **kwargs):
            captured_cmd.extend(cmd)
            return _ok_process()

        with patch("subprocess.run", side_effect=capture_run):
            proc.process(JobMetrics(video_name="v.mp4"))

        af_value = next(
            (captured_cmd[i + 1] for i, v in enumerate(captured_cmd) if v == "-af"),
            None,
        )
        assert "s=10" in af_value
        assert "g=5" in af_value


class TestErrorHandling:
    def test_raises_audio_enhancement_error_on_ffmpeg_failure(self, settings, tmp_path):
        settings.job_tmp_dir.mkdir(parents=True, exist_ok=True)
        settings.audio_raw_path.write_bytes(b"fake audio")

        proc = AudioEnhancerProcessor(settings)
        with patch("subprocess.run", return_value=_fail_process(stderr="ffmpeg error")):
            with pytest.raises(AudioEnhancementError):
                proc.process(JobMetrics(video_name="v.mp4"))
