from __future__ import annotations
import time
from pathlib import Path
from google.cloud import storage as gcs
from google.api_core.exceptions import GoogleAPIError
from src.storage.port import StoragePort
from src.exceptions import StorageDownloadError, StorageUploadError
from src.logger import get_logger
from src.config import Settings

logger = get_logger(__name__)


class GCSStorageAdapter(StoragePort):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = gcs.Client(project=settings.gcp_project_id)

    def download(self, remote_path: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        bucket_name = self._settings.gcs_bucket_input
        attempts = self._settings.gcs_max_retry_attempts

        for attempt in range(1, attempts + 1):
            try:
                logger.info(
                    "storage_download_start",
                    bucket=bucket_name,
                    blob=remote_path,
                    attempt=attempt,
                )
                bucket = self._client.bucket(bucket_name)
                bucket.blob(remote_path).download_to_filename(
                    str(local_path),
                    timeout=self._settings.gcs_download_timeout_seconds,
                )
                logger.info("storage_download_ok", blob=remote_path)
                return
            except GoogleAPIError as exc:
                logger.warning(
                    "storage_download_attempt_failed",
                    blob=remote_path,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == attempts:
                    raise StorageDownloadError(
                        f"Fallo al descargar '{remote_path}' tras {attempts} intentos.",
                        context={"blob": remote_path, "error": str(exc)},
                    ) from exc
                time.sleep(2 ** attempt)

    def upload(self, local_path: Path, remote_path: str) -> None:
        bucket_name = self._settings.gcs_bucket_output
        attempts = self._settings.gcs_max_retry_attempts

        for attempt in range(1, attempts + 1):
            try:
                logger.info(
                    "storage_upload_start",
                    bucket=bucket_name,
                    blob=remote_path,
                    attempt=attempt,
                )
                bucket = self._client.bucket(bucket_name)
                bucket.blob(remote_path).upload_from_filename(
                    str(local_path),
                    timeout=self._settings.gcs_upload_timeout_seconds,
                )
                logger.info("storage_upload_ok", blob=remote_path)
                return
            except GoogleAPIError as exc:
                logger.warning(
                    "storage_upload_attempt_failed",
                    blob=remote_path,
                    attempt=attempt,
                    error=str(exc),
                )
                if attempt == attempts:
                    raise StorageUploadError(
                        f"Fallo al subir '{remote_path}' tras {attempts} intentos.",
                        context={"blob": remote_path, "error": str(exc)},
                    ) from exc
                time.sleep(2 ** attempt)