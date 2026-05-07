from __future__ import annotations
from pathlib import Path
import pytest
from tests.conftest import make_settings
from src.storage.local_adapter import LocalStorageAdapter
from src.exceptions import StorageDownloadError


class TestLocalDownload:
    def test_download_copies_file_to_local_path(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        src = input_dir / "video.mp4"
        src.write_bytes(b"fake video content")

        s = make_settings(tmp_path, local_storage_input_dir=input_dir)
        adapter = LocalStorageAdapter(s)

        dst = tmp_path / "job" / "input.mp4"
        dst.parent.mkdir(parents=True)
        adapter.download("input/video.mp4", dst)

        assert dst.exists()
        assert dst.read_bytes() == b"fake video content"

    def test_download_uses_only_filename_ignoring_prefix(self, tmp_path):
        """GCS prefix (input/) se descarta; solo importa el nombre del archivo."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "clip.mp4").write_bytes(b"data")

        s = make_settings(tmp_path, local_storage_input_dir=input_dir)
        adapter = LocalStorageAdapter(s)

        dst = tmp_path / "output.mp4"
        adapter.download("some/nested/prefix/clip.mp4", dst)
        assert dst.exists()

    def test_download_raises_when_source_missing(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        s = make_settings(tmp_path, local_storage_input_dir=input_dir)
        adapter = LocalStorageAdapter(s)

        with pytest.raises(StorageDownloadError, match="no encontrado"):
            adapter.download("nonexistent.mp4", tmp_path / "out.mp4")

    def test_download_creates_parent_dirs(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "v.mp4").write_bytes(b"x")

        s = make_settings(tmp_path, local_storage_input_dir=input_dir)
        adapter = LocalStorageAdapter(s)

        dst = tmp_path / "deep" / "nested" / "dir" / "v.mp4"
        adapter.download("v.mp4", dst)
        assert dst.exists()


class TestLocalUpload:
    def test_upload_copies_file_to_output_dir(self, tmp_path):
        output_dir = tmp_path / "output"
        src = tmp_path / "result.mp4"
        src.write_bytes(b"result data")

        s = make_settings(tmp_path, local_storage_output_dir=output_dir)
        adapter = LocalStorageAdapter(s)
        adapter.upload(src, "output/result.mp4")

        dst = output_dir / "result.mp4"
        assert dst.exists()
        assert dst.read_bytes() == b"result data"

    def test_upload_creates_output_dir_if_missing(self, tmp_path):
        output_dir = tmp_path / "output" / "subdir"
        src = tmp_path / "result.mp4"
        src.write_bytes(b"x")

        s = make_settings(tmp_path, local_storage_output_dir=output_dir)
        adapter = LocalStorageAdapter(s)
        adapter.upload(src, "output/result.mp4")

        assert (output_dir / "result.mp4").exists()
