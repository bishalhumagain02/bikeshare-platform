"""
Tests for src/storage.py

Two properties matter: (1) with no B2 env vars set, upload is a
complete no-op — this is what keeps every other test in this suite
credential-free — and (2) when configured, it calls boto3 correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.storage import upload_if_configured


def test_noop_without_credentials(tmp_path, monkeypatch):
    for var in ["B2_ENDPOINT_URL", "B2_KEY_ID", "B2_APPLICATION_KEY", "B2_BUCKET_NAME"]:
        monkeypatch.delenv(var, raising=False)

    f = tmp_path / "sample.parquet"
    f.write_bytes(b"not real parquet, just testing the no-op path")
    result = upload_if_configured(f, "some/key.parquet")
    assert result is False


def test_partial_config_is_still_a_noop(tmp_path, monkeypatch):
    """All four env vars are required — three out of four should not
    attempt an upload with missing credentials."""
    monkeypatch.setenv("B2_ENDPOINT_URL", "https://example.com")
    monkeypatch.setenv("B2_KEY_ID", "fake")
    monkeypatch.setenv("B2_APPLICATION_KEY", "fake")
    monkeypatch.delenv("B2_BUCKET_NAME", raising=False)

    f = tmp_path / "sample.parquet"
    f.write_bytes(b"data")
    assert upload_if_configured(f, "key.parquet") is False


def test_uploads_when_fully_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("B2_ENDPOINT_URL", "https://s3.us-west-004.backblazeb2.com")
    monkeypatch.setenv("B2_KEY_ID", "fake-key-id")
    monkeypatch.setenv("B2_APPLICATION_KEY", "fake-app-key")
    monkeypatch.setenv("B2_BUCKET_NAME", "my-test-bucket")

    f = tmp_path / "sample.parquet"
    f.write_bytes(b"data")

    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client) as mock_boto:
        result = upload_if_configured(f, "station_status/dt=2026-09-03/x.parquet")

    assert result is True
    mock_boto.assert_called_once()
    mock_client.upload_file.assert_called_once_with(
        str(f), "my-test-bucket", "station_status/dt=2026-09-03/x.parquet"
    )


def test_upload_failure_is_caught_not_raised(tmp_path, monkeypatch):
    """A network hiccup on upload must never crash the ingestion job —
    the data is already safe on local disk regardless."""
    monkeypatch.setenv("B2_ENDPOINT_URL", "https://example.com")
    monkeypatch.setenv("B2_KEY_ID", "fake")
    monkeypatch.setenv("B2_APPLICATION_KEY", "fake")
    monkeypatch.setenv("B2_BUCKET_NAME", "bucket")

    f = tmp_path / "sample.parquet"
    f.write_bytes(b"data")

    from botocore.exceptions import ClientError

    mock_client = MagicMock()
    mock_client.upload_file.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "boom"}}, "upload_file"
    )
    with patch("boto3.client", return_value=mock_client):
        result = upload_if_configured(f, "key.parquet")  # should not raise

    assert result is False
