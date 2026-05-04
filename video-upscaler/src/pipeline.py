from __future__ import annotations
import shutil
from src.config import Settings
from src.storage.port import StoragePort
from src.processors.factory import ProcessorFactory
from src.exceptions import VideoUpscalerError
from src.metrics import JobMetrics, timed_step
from src.logger import get_logger

logger = get_logger(__name__)


class VideoPipeline:
    """Orquestador principal. No sabe de GCS ni de ESRGAN: solo coordina."""

    def __init__(self, settings: Settings, storage: StoragePort) -> None:
        self._settings = settings
        self._storage = storage
        self._factory = ProcessorFactory(settings)

    def run(self) -> JobMetrics:
        s = self._settings
        metrics = JobMetrics(video_name=s.video_name)

        structlog_ctx = {
            "video": s.video_name,
            "env": s.app_env,
            "scale": s.video_target_scale,
        }
        logger.info("pipeline_start", **structlog_ctx)

        try:
            self._prepare_workspace()

            with timed_step(metrics, "download"):
                self._storage.download(s.gcs_input_blob, s.input_video_path)

            pipeline = self._factory.build_pipeline()

            for processor in pipeline:
                logger.info("processor_running", name=processor.name)
                result = processor.process(metrics)
                logger.info(
                    "processor_done",
                    name=processor.name,
                    message=result.message,
                    metadata=result.metadata,
                )

            with timed_step(metrics, "upload"):
                self._storage.upload(s.output_video_path, s.gcs_output_blob)

            logger.info("pipeline_success", **metrics.summary())

        except VideoUpscalerError as exc:
            metrics.record_error("pipeline", str(exc))
            logger.error(
                "pipeline_error",
                error=str(exc),
                context=exc.context,
                exc_info=True,
            )
            raise

        except Exception as exc:
            metrics.record_error("pipeline_unexpected", str(exc))
            logger.critical("pipeline_unexpected_error", error=str(exc), exc_info=True)
            raise

        finally:
            self._cleanup_workspace()

        return metrics

    def _prepare_workspace(self) -> None:
        s = self._settings
        for d in [s.frames_dir, s.frames_up_dir]:
            d.mkdir(parents=True, exist_ok=True)
        logger.debug("workspace_ready", path=str(s.job_tmp_dir))

    def _cleanup_workspace(self) -> None:
        tmp = self._settings.job_tmp_dir
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            logger.info("workspace_cleaned", path=str(tmp))