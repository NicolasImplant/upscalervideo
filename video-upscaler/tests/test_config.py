from __future__ import annotations
from pathlib import Path
import pytest
from tests.conftest import make_settings


class TestOutputNaming:
    """El output debe derivar del stem del video para evitar colisiones entre runs."""

    def test_output_video_path_uses_stem(self, settings):
        assert settings.output_video_path.name == "test_video_upscaled.mp4"

    def test_gcs_output_blob_uses_stem(self, settings):
        assert settings.gcs_output_blob == "output/test_video_upscaled.mp4"

    def test_output_path_is_under_job_tmp_dir(self, settings):
        assert settings.output_video_path.parent == settings.job_tmp_dir

    def test_output_path_video_with_dots_in_name(self, tmp_path):
        s = make_settings(tmp_path, video_name="my.video.v2.mp4")
        assert s.output_video_path.name == "my.video.v2_upscaled.mp4"

    def test_output_path_video_without_extension(self, tmp_path):
        s = make_settings(tmp_path, video_name="videosinext")
        assert s.output_video_path.name == "videosinext_upscaled.mp4"

    def test_gcs_output_blob_respects_custom_prefix(self, tmp_path):
        s = make_settings(tmp_path, gcs_output_prefix="processed/2024/")
        assert s.gcs_output_blob.startswith("processed/2024/")


class TestJobTmpDir:
    def test_dots_in_video_name_replaced(self, settings):
        assert "." not in settings.job_tmp_dir.name

    def test_job_tmp_dir_under_tmp_base(self, settings):
        assert settings.job_tmp_dir.parent == settings.tmp_base_dir

    def test_frames_dir_under_job_tmp(self, settings):
        assert settings.frames_dir.parent == settings.job_tmp_dir

    def test_frames_up_dir_under_job_tmp(self, settings):
        assert settings.frames_up_dir.parent == settings.job_tmp_dir


class TestGCSBlobs:
    def test_gcs_input_blob_format(self, settings):
        assert settings.gcs_input_blob == "input/test_video.mp4"

    def test_gcs_input_blob_respects_custom_prefix(self, tmp_path):
        s = make_settings(tmp_path, gcs_input_prefix="raw/")
        assert s.gcs_input_blob == "raw/test_video.mp4"


class TestAudioPaths:
    def test_audio_raw_path_under_job_tmp(self, settings):
        assert settings.audio_raw_path.parent == settings.job_tmp_dir

    def test_audio_clean_path_under_job_tmp(self, settings):
        assert settings.audio_clean_path.parent == settings.job_tmp_dir

    def test_audio_paths_different(self, settings):
        assert settings.audio_raw_path != settings.audio_clean_path


class TestEnvFlag:
    def test_is_development_false_by_default(self, settings):
        assert settings.is_development is False

    def test_is_development_true_when_set(self, tmp_path):
        s = make_settings(tmp_path, app_env="development")
        assert s.is_development is True
