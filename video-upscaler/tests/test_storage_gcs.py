from __future__ import annotations
import sys
from unittest.mock import MagicMock, patch
import pytest
from src.exceptions import StorageDownloadError, StorageUploadError


def _make_adapter(settings, mock_client):
    from src.storage.gcs_adapter import GCSStorageAdapter
    with patch("src.storage.gcs_adapter.gcs.Client", return_value=mock_client):
        return GCSStorageAdapter(settings)


class TestGCSDownload:
    def test_download_calls_correct_bucket_and_blob(self, settings, tmp_path):
        mock_client = MagicMock()
        adapter = _make_adapter(settings, mock_client)

        local = tmp_path / "out.mp4"
        adapter.download("input/video.mp4", local)

        mock_client.bucket.assert_called_once_with(settings.gcs_bucket_input)
        mock_client.bucket.return_value.blob.assert_called_once_with("input/video.mp4")
        mock_client.bucket.return_value.blob.return_value.download_to_filename.assert_called_once()

    def test_download_retries_on_google_api_error(self, settings, tmp_path, fake_google_api_error):
        mock_client = MagicMock()
        mock_blob = mock_client.bucket.return_value.blob.return_value
        mock_blob.download_to_filename.side_effect = [fake_google_api_error("transient"), None]

        adapter = _make_adapter(settings, mock_client)
        with patch("src.storage.gcs_adapter.time.sleep"):
            adapter.download("input/video.mp4", tmp_path / "out.mp4")

        assert mock_blob.download_to_filename.call_count == 2

    def test_download_raises_storage_error_after_max_retries(self, settings, tmp_path, fake_google_api_error):
        mock_client = MagicMock()
        mock_blob = mock_client.bucket.return_value.blob.return_value
        mock_blob.download_to_filename.side_effect = fake_google_api_error("persistent")

        adapter = _make_adapter(settings, mock_client)
        with patch("src.storage.gcs_adapter.time.sleep"):
            with pytest.raises(StorageDownloadError):
                adapter.download("input/video.mp4", tmp_path / "out.mp4")

        assert mock_blob.download_to_filename.call_count == settings.gcs_max_retry_attempts

    def test_download_exponential_backoff_sleeps(self, settings, tmp_path, fake_google_api_error):
        mock_client = MagicMock()
        mock_blob = mock_client.bucket.return_value.blob.return_value
        mock_blob.download_to_filename.side_effect = [
            fake_google_api_error("err"),
            fake_google_api_error("err"),
            None,
        ]
        adapter = _make_adapter(settings, mock_client)

        with patch("src.storage.gcs_adapter.time.sleep") as mock_sleep:
            adapter.download("input/v.mp4", tmp_path / "out.mp4")

        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        # Primer retry: 2^1=2, segundo retry: 2^2=4
        assert sleep_calls == [2, 4]


class TestGCSUpload:
    def test_upload_calls_correct_bucket_and_blob(self, settings, tmp_path):
        src = tmp_path / "result.mp4"
        src.write_bytes(b"data")
        mock_client = MagicMock()
        adapter = _make_adapter(settings, mock_client)

        adapter.upload(src, "output/result.mp4")

        mock_client.bucket.assert_called_once_with(settings.gcs_bucket_output)
        mock_client.bucket.return_value.blob.assert_called_once_with("output/result.mp4")
        mock_client.bucket.return_value.blob.return_value.upload_from_filename.assert_called_once()

    def test_upload_retries_on_google_api_error(self, settings, tmp_path, fake_google_api_error):
        src = tmp_path / "result.mp4"
        src.write_bytes(b"data")
        mock_client = MagicMock()
        mock_blob = mock_client.bucket.return_value.blob.return_value
        mock_blob.upload_from_filename.side_effect = [fake_google_api_error("transient"), None]

        adapter = _make_adapter(settings, mock_client)
        with patch("src.storage.gcs_adapter.time.sleep"):
            adapter.upload(src, "output/result.mp4")

        assert mock_blob.upload_from_filename.call_count == 2

    def test_upload_raises_storage_error_after_max_retries(self, settings, tmp_path, fake_google_api_error):
        src = tmp_path / "result.mp4"
        src.write_bytes(b"data")
        mock_client = MagicMock()
        mock_blob = mock_client.bucket.return_value.blob.return_value
        mock_blob.upload_from_filename.side_effect = fake_google_api_error("persistent")

        adapter = _make_adapter(settings, mock_client)
        with patch("src.storage.gcs_adapter.time.sleep"):
            with pytest.raises(StorageUploadError):
                adapter.upload(src, "output/result.mp4")

        assert mock_blob.upload_from_filename.call_count == settings.gcs_max_retry_attempts
