from __future__ import annotations
import cv2
import torch
from pathlib import Path
from basicsr.archs.rrdbnet_arch import RRDBNet
from realesrgan import RealESRGANer
from src.config import Settings
from src.processors.port import ProcessorPort, ProcessorResult
from src.exceptions import UpscalingError
from src.metrics import JobMetrics, timed_step
from src.logger import get_logger

logger = get_logger(__name__)


class VideoUpscalerProcessor(ProcessorPort):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        if not settings.esrgan_model_path.exists():
            raise UpscalingError(
                f"Modelo no encontrado: {settings.esrgan_model_path}",
                processor_name="video_upscaler",
                context={"model_path": str(settings.esrgan_model_path)},
            )

    @property
    def name(self) -> str:
        return "video_upscaler"

    def _build_upsampler(self) -> RealESRGANer:
        s = self._settings
        model = RRDBNet(
            num_in_ch=3, num_out_ch=3,
            num_feat=s.esrgan_num_feat,
            num_block=s.esrgan_num_block,
            num_grow_ch=s.esrgan_num_grow_ch,
            scale=s.video_target_scale,
        )
        return RealESRGANer(
            scale=s.video_target_scale,
            model_path=str(s.esrgan_model_path),
            model=model,
            tile=s.esrgan_tile_size,
            tile_pad=s.esrgan_tile_pad,
            pre_pad=s.esrgan_pre_pad,
            device=torch.device(s.esrgan_device),
        )

    def process(self, metrics: JobMetrics) -> ProcessorResult:
        s = self._settings
        s.frames_up_dir.mkdir(parents=True, exist_ok=True)
        frames = sorted(s.frames_dir.glob(f"*.{s.frames_format}"))

        if not frames:
            raise UpscalingError(
                "No se encontraron frames para procesar.",
                processor_name=self.name,
            )

        upsampler = self._build_upsampler()
        logger.info("upscaling_start", frame_count=len(frames), device=s.esrgan_device)

        with timed_step(metrics, self.name):
            for i, frame_path in enumerate(frames, 1):
                self._upscale_frame(upsampler, frame_path, s.frames_up_dir / frame_path.name)
                if i % 50 == 0 or i == len(frames):
                    logger.info("upscaling_progress", done=i, total=len(frames))

        return ProcessorResult(
            success=True,
            message=f"{len(frames)} frames escalados a {s.video_target_scale}x",
        )

    def _upscale_frame(
        self, upsampler: RealESRGANer, src: Path, dst: Path
    ) -> None:
        img = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if img is None:
            raise UpscalingError(
                f"No se pudo leer el frame: {src}",
                processor_name=self.name,
                context={"frame": str(src)},
            )
        try:
            output, _ = upsampler.enhance(img, outscale=self._settings.video_target_scale)
            cv2.imwrite(str(dst), output)
        except RuntimeError as exc:
            raise UpscalingError(
                f"Error de GPU en frame {src.name}: {exc}",
                processor_name=self.name,
                context={"frame": str(src), "error": str(exc)},
            ) from exc