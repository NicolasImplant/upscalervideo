from __future__ import annotations
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generator
from src.logger import get_logger

logger = get_logger(__name__)


@dataclass
class JobMetrics:
    video_name: str
    timings: dict[str, float] = field(default_factory=dict)
    frame_count: int = 0
    source_fps: float = 0.0
    errors: list[str] = field(default_factory=list)

    def record_timing(self, step: str, elapsed: float) -> None:
        self.timings[step] = round(elapsed, 3)
        logger.info("step_completed", step=step, elapsed_seconds=elapsed)

    def record_error(self, step: str, error: str) -> None:
        self.errors.append(f"{step}: {error}")

    @property
    def total_elapsed(self) -> float:
        return round(sum(self.timings.values()), 3)

    def summary(self) -> dict:
        return {
            "video_name": self.video_name,
            "total_seconds": self.total_elapsed,
            "steps": self.timings,
            "frame_count": self.frame_count,
            "source_fps": self.source_fps,
            "errors": self.errors,
        }


@contextmanager
def timed_step(metrics: JobMetrics, step_name: str) -> Generator[None, None, None]:
    logger.info("step_started", step=step_name)
    start = time.perf_counter()
    try:
        yield
    finally:
        metrics.record_timing(step_name, time.perf_counter() - start)
