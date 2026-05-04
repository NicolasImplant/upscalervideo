from __future__ import annotations
import subprocess
from src.processors.port import ProcessorPort, ProcessorResult
from src.exceptions import FrameExtractionError
from src.metrics import JobMetrics, timed_step
from src.logger import get_logger

logger = get_logger(__name__)


class FrameExtractorProcessor(ProcessorPort):
    @property
    def name(self) -> str:
        return "frame_extractor"

    def process(self, metrics: JobMetrics) -> ProcessorResult:
        s = self._settings
        s.frames_dir.mkdir(parents=True, exist_ok=True)

        with timed_step(metrics, self.name):
            metrics.source_fps = self._detect_fps()
            self._extract_frames()
            self._extract_audio()

        frame_count = len(list(s.frames_dir.glob(f"*.{s.frames_format}")))
        metrics.frame_count = frame_count
        logger.info("frames_extracted", count=frame_count, fps=metrics.source_fps)
        return ProcessorResult(
            success=True,
            message=f"{frame_count} frames extraídos a {metrics.source_fps} fps",
        )

    def _detect_fps(self) -> float:
        s = self._settings
        if s.video_source_fps is not None:
            return s.video_source_fps
        cmd = [
            s.ffprobe_binary, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=r_frame_rate",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(s.input_video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            try:
                num, den = result.stdout.strip().split("/")
                return round(float(num) / float(den), 3)
            except (ValueError, ZeroDivisionError):
                pass
        logger.warning("fps_probe_failed", fallback=s.video_output_fps)
        return float(s.video_output_fps)

    def _extract_frames(self) -> None:
        s = self._settings
        cmd = [
            s.ffmpeg_binary,
            "-loglevel", s.ffmpeg_loglevel,
            "-i", str(s.input_video_path),
            "-threads", str(s.ffmpeg_threads),
            "-q:v", "1",
            "-y",
            str(s.frames_dir / f"%06d.{s.frames_format}"),
        ]
        self._run(cmd, "frame_extraction")

    def _extract_audio(self) -> None:
        s = self._settings
        cmd = [
            s.ffmpeg_binary,
            "-loglevel", s.ffmpeg_loglevel,
            "-i", str(s.input_video_path),
            "-vn",
            "-acodec", "copy",
            "-y",
            str(s.audio_raw_path),
        ]
        self._run(cmd, "audio_extraction")

    def _run(self, cmd: list[str], step: str) -> None:
        logger.debug("subprocess_start", step=step, cmd=cmd)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise FrameExtractionError(
                f"FFmpeg falló en '{step}' con código {result.returncode}",
                processor_name=self.name,
                context={"step": step, "stderr": result.stderr[-500:]},
            )
