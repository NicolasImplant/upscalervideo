from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Entorno
    app_env: str = Field("production", pattern="^(production|development)$")
    log_level: str = Field("INFO", pattern="^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    log_format: str = Field("json", pattern="^(json|console)$")

    # GCP
    gcp_project_id: str
    gcs_bucket_input: str
    gcs_bucket_output: str
    gcs_input_prefix: str = "input/"
    gcs_output_prefix: str = "output/"
    gcs_upload_timeout_seconds: int = Field(300, gt=0)
    gcs_download_timeout_seconds: int = Field(300, gt=0)
    gcs_max_retry_attempts: int = Field(3, ge=1, le=10)

    # Video
    video_name: str
    video_target_scale: int = Field(2, ge=2, le=4)
    video_source_fps: float | None = None   # None = auto-detect via ffprobe
    video_output_fps: int = Field(30, gt=0)
    video_output_crf: int = Field(18, ge=0, le=51)
    video_output_preset: str = "slow"
    video_output_codec: str = "libx264"
    video_output_audio_bitrate: str = "192k"
    video_output_audio_codec: str = "aac"

    # Real-ESRGAN
    esrgan_model_name: str = "RealESRGAN_x2plus"
    esrgan_model_path: Path = Path("/models/RealESRGAN_x2plus.pth")
    esrgan_tile_size: int = Field(256, gt=0)
    esrgan_tile_pad: int = Field(10, ge=0)
    esrgan_pre_pad: int = Field(0, ge=0)
    esrgan_device: str = Field("cuda", pattern="^(cuda|cpu)$")
    esrgan_num_feat: int = Field(64, gt=0)
    esrgan_num_block: int = Field(23, gt=0)
    esrgan_num_grow_ch: int = Field(32, gt=0)

    # Audio
    audio_enable_enhancement: bool = True
    audio_denoiser_strength: int = Field(7, ge=1, le=15)
    audio_denoiser_patch_radius: float = Field(0.002, gt=0)
    audio_eq_frequency: int = Field(100, gt=0)
    audio_eq_gain_db: int = 3
    audio_eq_width: int = Field(200, gt=0)

    # FFmpeg / FFprobe
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    ffmpeg_threads: int = Field(0, ge=0)
    ffmpeg_loglevel: str = "error"

    # Paths temporales
    tmp_base_dir: Path = Path("/tmp/upscaler")
    frames_subdir: str = "frames"
    frames_upscaled_subdir: str = "frames_up"
    frames_format: str = "png"
    audio_raw_filename: str = "audio_raw.aac"
    audio_clean_filename: str = "audio_clean.aac"
    input_filename: str = "input.mp4"

    # Storage backend
    storage_backend: str = Field("gcs", pattern="^(gcs|local)$")
    local_storage_input_dir: Path = Path("/data/input")
    local_storage_output_dir: Path = Path("/data/output")

    @field_validator("esrgan_model_path", mode="before")
    @classmethod
    def validate_model_path(cls, v: str | Path) -> Path:
        return Path(v)

    @property
    def job_tmp_dir(self) -> Path:
        return self.tmp_base_dir / self.video_name.replace(".", "_")

    @property
    def frames_dir(self) -> Path:
        return self.job_tmp_dir / self.frames_subdir

    @property
    def frames_up_dir(self) -> Path:
        return self.job_tmp_dir / self.frames_upscaled_subdir

    @property
    def input_video_path(self) -> Path:
        return self.job_tmp_dir / self.input_filename

    @property
    def audio_raw_path(self) -> Path:
        return self.job_tmp_dir / self.audio_raw_filename

    @property
    def audio_clean_path(self) -> Path:
        return self.job_tmp_dir / self.audio_clean_filename

    @property
    def output_video_path(self) -> Path:
        return self.job_tmp_dir / f"{Path(self.video_name).stem}_upscaled.mp4"

    @property
    def gcs_input_blob(self) -> str:
        return f"{self.gcs_input_prefix}{self.video_name}"

    @property
    def gcs_output_blob(self) -> str:
        return f"{self.gcs_output_prefix}{Path(self.video_name).stem}_upscaled.mp4"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"
