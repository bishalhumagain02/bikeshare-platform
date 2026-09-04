# Cloud data collection setup (Backblaze B2 + GitHub Actions)

This replaces "keep my laptop on" with GitHub Actions polling on a
schedule and uploading to a free B2 bucket — solves the timezone
coverage gap (your local day being the source city's night).

## 1. Create a Backblaze B2 account and bucket

1. Sign up free at backblaze.com/b2 (no credit card required for the free tier)
2. Create a bucket — name it something like `bikeshare-platform-data`.
   Set it to **Private**.
3. Go to "Application Keys" → "Add a New Application Key". Restrict it
   to your new bucket. Save the **keyID** and **applicationKey** shown —
   the applicationKey is only shown once.
4. Note your bucket's **S3-compatible endpoint URL**, shown on the
   bucket details page — looks like
   `https://s3.us-west-004.backblazeb2.com`.

## 2. Add these as GitHub repo secrets

In your GitHub repo: Settings → Secrets and variables → Actions → New
repository secret. Add all four:

| Secret name | Value |
|---|---|
| `B2_ENDPOINT_URL` | the endpoint URL from step 1.4 |
| `B2_KEY_ID` | the keyID from step 1.3 |
| `B2_APPLICATION_KEY` | the applicationKey from step 1.3 |
| `B2_BUCKET_NAME` | your bucket name from step 1.2 |

## 3. Push this repo to GitHub

The two workflow files are already set up:
- `.github/workflows/poll-station-status.yml` — runs every 10 minutes
- `.github/workflows/archive-weather-forecast.yml` — runs once daily at 06:00 UTC

They activate automatically once pushed, using the secrets above.
No server, no laptop, no SSH required.

## 4. Verify it's actually running

GitHub repo → "Actions" tab → you should see runs appearing every ~10
minutes for the poller. Click one to see its log output — it should
show the same "wrote N stations -> ..." / "uploaded -> s3://..." lines
you saw running it locally.

You can also trigger a manual test run immediately without waiting for
the schedule: Actions tab → select the workflow → "Run workflow".

## 5. Pull the accumulated data down locally, whenever you want to work

Set the same four env vars locally (in PowerShell, for one terminal session):

```powershell
$env:B2_ENDPOINT_URL="https://s3.us-west-004.backblazeb2.com"
$env:B2_KEY_ID="your-key-id"
$env:B2_APPLICATION_KEY="your-application-key"
$env:B2_BUCKET_NAME="bikeshare-platform-data"
$env:PYTHONPATH="."
python -m src.tools.download_from_b2
```

This only downloads files you don't already have locally — safe to
run repeatedly, it won't re-download or duplicate anything.

## Known caveats, honestly

- GitHub Actions schedules can drift by a few minutes under load —
  expect "roughly every 10 minutes," not exact.
- GitHub automatically disables scheduled workflows after 60 days with
  **no repository activity at all** — any commit or push resets this,
  so as long as you're actively working on the repo across the 7
  weeks, this won't trigger.
- B2's free tier has generous limits for a project this size, but if
  you ever see upload failures in the Actions log, check your B2
  account dashboard for usage before assuming it's a code bug.
