from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path


class StoragePort(ABC):
    """Puerto abstracto de almacenamiento — nunca depender de GCS directamente."""

    @abstractmethod
    def download(self, remote_path: str, local_path: Path) -> None:
        ...

    @abstractmethod
    def upload(self, local_path: Path, remote_path: str) -> None:
        ...