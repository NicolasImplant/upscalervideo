from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from src.config import Settings
from src.metrics import JobMetrics


@dataclass
class ProcessorResult:
    success: bool
    message: str
    metadata: dict | None = None


class ProcessorPort(ABC):
    """Interfaz común para todos los procesadores de video."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def process(self, metrics: JobMetrics) -> ProcessorResult:
        ...