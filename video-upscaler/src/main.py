from __future__ import annotations
import sys
from src.config import Settings
from src.logger import configure_logging, get_logger
from src.pipeline import VideoPipeline
from src.exceptions import VideoUpscalerError


def build_storage(settings: Settings):
    if settings.storage_backend == "gcs":
        from src.storage.gcs_adapter import GCSStorageAdapter
        return GCSStorageAdapter(settings)
    from src.storage.local_adapter import LocalStorageAdapter
    return LocalStorageAdapter(settings)


def main() -> None:
    settings = Settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    logger = get_logger("main")

    logger.info(
        "app_start",
        video=settings.video_name,
        backend=settings.storage_backend,
        env=settings.app_env,
    )

    storage = build_storage(settings)
    pipeline = VideoPipeline(settings=settings, storage=storage)

    try:
        metrics = pipeline.run()
        logger.info("app_done", **metrics.summary())
        sys.exit(0)
    except VideoUpscalerError:
        sys.exit(1)
    except Exception:
        logger.critical("app_fatal", exc_info=True)
        sys.exit(2)


if __name__ == "__main__":
    main()