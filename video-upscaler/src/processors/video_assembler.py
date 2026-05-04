from __future__ import annotations
import subprocess
from src.processors.port import ProcessorPort, ProcessorResult
from src.exceptions import VideoAssemblyError
from src.metrics import JobMetrics, timed_step
from src.logger import get_logger

logger = get_logger(__name__)


class VideoAssemblerProcessor(ProcessorPort):
    @property
    def name(self) -> str:
        return "video_assembler"

    def process(self, metrics: JobMetrics) -> ProcessorResult:
        s = self._settings
        audio_source = (
            s.audio_clean_path if s.audio_clean_path.exists()
            else s.audio_raw_path if s.audio_raw_path.exists()
            else None
        )

        fps = metrics.source_fps if metrics.source_fps > 0 else s.video_output_fps
        cmd = [
            s.ffmpeg_binary,
            "-loglevel", s.ffmpeg_loglevel,
            "-framerate", str(fps),
            "-i", str(s.frames_up_dir / f"%06d.{s.frames_format}"),
        ]

        if audio_source:
            cmd += ["-i", str(audio_source)]
            logger.info("assembler_using_audio", source=str(audio_source))
        else:
            logger.warning("assembler_no_audio")

        cmd += [
            "-c:v", s.video_output_codec,
            "-crf", str(s.video_output_crf),
            "-preset", s.video_output_preset,
            "-threads", str(s.ffmpeg_threads),
        ]

        if audio_source:
            cmd += ["-c:a", s.video_output_audio_codec, "-b:a", s.video_output_audio_bitrate]

        cmd += ["-y", str(s.output_video_path)]

        with timed_step(metrics, self.name):
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise VideoAssemblyError(
                    f"FFmpeg ensamblado falló con código {result.returncode}",
                    processor_name=self.name,
                    context={"stderr": result.stderr[-500:]},
                )

        size_mb = round(s.output_video_path.stat().st_size / 1_048_576, 2)
        logger.info("video_assembled", output=str(s.output_video_path), size_mb=size_mb)
        return ProcessorResult(
            success=True,
            message=f"Video ensamblado: {size_mb} MB",
            metadata={"size_mb": size_mb},
        )