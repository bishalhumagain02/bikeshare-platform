"""
Optional upload to Backblaze B2 (S3-compatible), so data can land
somewhere other than a personal laptop's disk — needed when polling
runs on GitHub Actions instead of locally.

Deliberately fails soft: if the required env vars aren't set, upload
is a silent no-op. This means every ingestion script keeps working
exactly as before for local development and for the test suite —
nothing here is required to run this project locally.

Required env vars (only needed for the GitHub Actions / cloud path):
    B2_ENDPOINT_URL       e.g. https://s3.us-west-004.backblazeb2.com
    B2_KEY_ID
    B2_APPLICATION_KEY
    B2_BUCKET_NAME
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Loads .env if present — one-time setup instead of retyping env vars
# every terminal session. Silently does nothing if .env doesn't exist,
# so this never breaks the GitHub Actions path (which uses real
# environment secrets, not a .env file).
load_dotenv()


def _b2_configured() -> bool:
    return all(
        os.environ.get(v)
        for v in ["B2_ENDPOINT_URL", "B2_KEY_ID", "B2_APPLICATION_KEY", "B2_BUCKET_NAME"]
    )


def upload_if_configured(local_path: Path, remote_key: str) -> bool:
    """Upload local_path to the configured B2 bucket under remote_key.
    Returns True if an upload happened, False if skipped (no config).
    Never raises on upload failure — logs and returns False instead,
    so a flaky network never crashes the ingestion job itself."""
    if not _b2_configured():
        return False

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["B2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
    )
    bucket = os.environ["B2_BUCKET_NAME"]
    try:
        client.upload_file(str(local_path), bucket, remote_key)
        print(f"  uploaded -> s3://{bucket}/{remote_key}")
        return True
    except (BotoCoreError, ClientError) as exc:
        print(f"  B2 upload failed (data still safe locally): {exc}", file=sys.stderr)
        return False
