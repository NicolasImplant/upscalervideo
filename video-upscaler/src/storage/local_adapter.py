from __future__ import annotations
import shutil
from pathlib import Path
from src.storage.port import StoragePort
from src.exceptions import StorageDownloadError, StorageUploadError
from src.logger import get_logger
from src.config import Settings

logger = get_logger(__name__)


class LocalStorageAdapter(StoragePort):
    """Adaptador local para desarrollo y pruebas sin GCS."""

    def __init__(self, settings: Settings) -> None:
        self._input_dir = settings.local_storage_input_dir
        self._output_dir = settings.local_storage_output_dir

    def download(self, remote_path: str, local_path: Path) -> None:
        # remote_path puede incluir prefijos GCS (e.g. "input/video.mp4");
        # el adaptador local usa sólo el nombre de archivo.
        src = self._input_dir / Path(remote_path).name
        if not src.exists():
            raise StorageDownloadError(
                f"Archivo local no encontrado: {src}",
                context={"path": str(src)},
            )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_path)
        logger.info("local_download_ok", src=str(src), dst=str(local_path))

    def upload(self, local_path: Path, remote_path: str) -> None:
        dst = self._output_dir / Path(remote_path).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dst)
        logger.info("local_upload_ok", src=str(local_path), dst=str(dst))