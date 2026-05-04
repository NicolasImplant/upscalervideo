from __future__ import annotations
import subprocess
from src.processors.port import ProcessorPort, ProcessorResult
from src.exceptions import AudioEnhancementError
from src.metrics import JobMetrics, timed_step
from src.logger import get_logger

logger = get_logger(__name__)


class AudioEnhancerProcessor(ProcessorPort):
    @property
    def name(self) -> str:
        return "audio_enhancer"

    def process(self, metrics: JobMetrics) -> ProcessorResult:
        s = self._settings

        if not s.audio_raw_path.exists():
            logger.warning("audio_raw_not_found", path=str(s.audio_raw_path))
            return ProcessorResult(success=True, message="Sin audio, omitido.")

        af_filter = (
            f"anlmdn=s={s.audio_denoiser_strength}:p={s.audio_denoiser_patch_radius},"
            f"equalizer=f={s.audio_eq_frequency}:t=o:w={s.audio_eq_width}:g={s.audio_eq_gain_db}"
        )

        cmd = [
            s.ffmpeg_binary,
            "-i", str(s.audio_raw_path),
            "-af", af_filter,
            "-loglevel", s.ffmpeg_loglevel,
            "-y", str(s.audio_clean_path),
        ]

        logger.debug("audio_filter", af=af_filter)

        with timed_step(metrics, self.name):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise AudioEnhancementError(
                    f"FFmpeg audio falló con código {result.returncode}",
                    processor_name=self.name,
                    context={"stderr": result.stderr[-500:], "filter": af_filter},
                )

        return ProcessorResult(success=True, message="Audio mejorado correctamente.")