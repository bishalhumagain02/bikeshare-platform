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

The two workflow files are already set up. They do NOT use GitHub's
own `schedule:` cron trigger — that's documented by GitHub itself as
best-effort, and in practice can be delayed by hours on a new,
low-activity repo (confirmed on this project: 2-3 hour delays instead
of the requested 10 minutes). Instead they use `repository_dispatch`,
fired by an external service in step 4 below — this runs near-instantly
because it's a direct API call, not a request sitting in GitHub's
internal scheduling queue.

Push everything, including `.github/workflows/`. No server, no laptop,
no SSH required for this part.

## 4. Set up an external pinger (cron-job.org) — this is what makes timing reliable

1. Create a **GitHub Personal Access Token**: GitHub → Settings (your
   account, not the repo) → Developer settings → Personal access
   tokens → Tokens (classic) → Generate new token. Give it the `repo`
   scope. Copy the token — it's shown once.
2. Sign up free at **cron-job.org** (no credit card needed).
3. Create a new cron job for the station poller:
   - URL: `https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/dispatches`
   - Request method: `POST`
   - Headers:
     - `Authorization: Bearer YOUR_GITHUB_TOKEN`
     - `Accept: application/vnd.github+json`
     - `Content-Type: application/json`
   - Body: `{"event_type": "poll-station-status"}`
   - Schedule: every 10 minutes
4. Create a second cron job for the weather forecast, same setup except:
   - Body: `{"event_type": "archive-weather-forecast"}`
   - Schedule: once daily

## 5. Verify it's actually running

GitHub repo → "Actions" tab → you should now see runs appearing close
to every 10 minutes for the poller, not hours apart. Click one to see
its log output — it should show the same "wrote N stations -> ..." /
"uploaded -> s3://..." lines you saw running it locally.

You can also trigger a manual test run anytime without waiting:
Actions tab → select the workflow → "Run workflow".

## 6. Pull the accumulated data down locally, whenever you want to work

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

- Your GitHub Personal Access Token goes into cron-job.org's servers,
  not GitHub's — treat it like a password, and scope it to only what's
  needed (`repo` scope is already the minimum required for
  `dispatches`). If you're ever done with this project, revoke it from
  GitHub's token settings.
- GitHub automatically disables `repository_dispatch`/scheduled
  workflows after 60 days with **no repository activity at all** — any
  commit or push resets this, so as long as you're actively working on
  the repo across the 7 weeks, this won't trigger.
- cron-job.org's free tier has its own limits (checked at signup) —
  comfortably enough for two jobs at 10-min/daily cadence for a project
  this length, but worth a glance if you ever add more frequent jobs.
- B2's free tier has generous limits for a project this size (measured:
  ~300 MB over 7 weeks vs. a 10 GB allowance), but if you ever see
  upload failures in the Actions log, check your B2 account dashboard
  for usage before assuming it's a code bug.
