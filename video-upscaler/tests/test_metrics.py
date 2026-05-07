from __future__ import annotations
import time
import pytest
from src.metrics import JobMetrics, timed_step


class TestJobMetrics:
    def test_initial_state(self):
        m = JobMetrics(video_name="v.mp4")
        assert m.frame_count == 0
        assert m.source_fps == 0.0
        assert m.timings == {}
        assert m.errors == []

    def test_record_timing_stores_rounded_value(self):
        m = JobMetrics(video_name="v.mp4")
        m.record_timing("download", 1.23456789)
        assert m.timings["download"] == pytest.approx(1.235, abs=0.001)

    def test_total_elapsed_sums_all_steps(self):
        m = JobMetrics(video_name="v.mp4")
        m.record_timing("step_a", 1.0)
        m.record_timing("step_b", 2.0)
        assert m.total_elapsed == pytest.approx(3.0)

    def test_total_elapsed_zero_when_no_steps(self):
        m = JobMetrics(video_name="v.mp4")
        assert m.total_elapsed == 0.0

    def test_record_error_appends(self):
        m = JobMetrics(video_name="v.mp4")
        m.record_error("download", "timeout")
        m.record_error("upload", "403")
        assert len(m.errors) == 2
        assert "download: timeout" in m.errors

    def test_summary_contains_required_keys(self):
        m = JobMetrics(video_name="v.mp4")
        m.record_timing("step_a", 1.0)
        s = m.summary()
        assert "video_name" in s
        assert "total_seconds" in s
        assert "steps" in s
        assert "frame_count" in s
        assert "source_fps" in s
        assert "errors" in s

    def test_summary_video_name(self):
        m = JobMetrics(video_name="my_video.mp4")
        assert m.summary()["video_name"] == "my_video.mp4"


class TestTimedStep:
    def test_records_elapsed_time(self):
        m = JobMetrics(video_name="v.mp4")
        with timed_step(m, "my_step"):
            time.sleep(0.01)
        assert "my_step" in m.timings
        assert m.timings["my_step"] >= 0.01

    def test_records_timing_even_on_exception(self):
        m = JobMetrics(video_name="v.mp4")
        with pytest.raises(ValueError):
            with timed_step(m, "failing_step"):
                raise ValueError("oops")
        assert "failing_step" in m.timings

    def test_multiple_steps_independent(self):
        m = JobMetrics(video_name="v.mp4")
        with timed_step(m, "step_1"):
            pass
        with timed_step(m, "step_2"):
            pass
        assert "step_1" in m.timings
        assert "step_2" in m.timings
