from __future__ import annotations
from src.config import Settings
from src.processors.port import ProcessorPort
from src.processors.frame_extractor import FrameExtractorProcessor
from src.processors.video_upscaler import VideoUpscalerProcessor
from src.processors.audio_enhancer import AudioEnhancerProcessor
from src.processors.video_assembler import VideoAssemblerProcessor
from src.logger import get_logger

logger = get_logger(__name__)


class ProcessorFactory:
    """
    Construye el pipeline de procesadores desde la configuración.
    Agregar un nuevo procesador = agregar una línea aquí.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def build_pipeline(self) -> list[ProcessorPort]:
        processors: list[ProcessorPort] = [
            FrameExtractorProcessor(self._settings),
            VideoUpscalerProcessor(self._settings),
        ]

        if self._settings.audio_enable_enhancement:
            processors.append(AudioEnhancerProcessor(self._settings))
            logger.info("factory_audio_enhancement_enabled")
        else:
            logger.info("factory_audio_enhancement_disabled")

        processors.append(VideoAssemblerProcessor(self._settings))

        logger.info(
            "factory_pipeline_built",
            steps=[p.name for p in processors],
        )
        return processors