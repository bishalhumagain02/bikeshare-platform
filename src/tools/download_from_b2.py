"""
Pull everything (or everything new) from the B2 bucket down into the
local raw/ folder, so you can run dbt/Dagster/analysis against it.

This is the "get the data off the cloud and onto my laptop when I
actually sit down to work" step — the polling and archiving jobs run
on GitHub Actions continuously; this script is what you run locally,
whenever you want, to sync down what's accumulated since last time.

Usage:
    python -m src.tools.download_from_b2
"""

from __future__ import annotations

import os
import sys

import boto3
from dotenv import load_dotenv

from src.config import RAW_DIR

load_dotenv()  # picks up .env if present, so you don't retype credentials

REQUIRED_ENV = ["B2_ENDPOINT_URL", "B2_KEY_ID", "B2_APPLICATION_KEY", "B2_BUCKET_NAME"]


def main() -> None:
    missing = [v for v in REQUIRED_ENV if not os.environ.get(v)]
    if missing:
        print(f"Missing env vars: {missing}. Set them the same way the GitHub "
              f"Actions secrets are set (see README) before running this.", file=sys.stderr)
        sys.exit(1)

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["B2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
    )
    bucket = os.environ["B2_BUCKET_NAME"]

    downloaded = 0
    skipped = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            local_path = RAW_DIR / key
            if local_path.exists() and local_path.stat().st_size == obj["Size"]:
                skipped += 1
                continue  # already have this exact file, don't re-download
            local_path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(local_path))
            print(f"  downloaded {key}")
            downloaded += 1

    print(f"done — {downloaded} new files downloaded, {skipped} already up to date")


if __name__ == "__main__":
    main()
