"""
Optional Slack/Discord webhook notification on asset failure. Fails
soft: with no WEBHOOK_URL configured, this is a silent no-op — exactly
the same pattern as src/storage.py's optional B2 upload, so local dev
and CI never need a real webhook.
"""

from __future__ import annotations

import os

import httpx

import dagster as dg


@dg.failure_hook
def notify_on_failure(context: dg.HookContext) -> None:
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        return  # no-op without configuration — same pattern as storage.py

    message = (
        f":x: Asset `{context.asset_key.to_user_string()}` failed: "
        f"{context.op_exception}"
    )
    try:
        httpx.post(webhook_url, json={"content": message}, timeout=10.0)
    except httpx.HTTPError as exc:
        context.log.warning(f"Failure notification itself failed to send: {exc}")
