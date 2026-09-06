# Decisions and Findings Log

Real issues hit during this build, why they happened, and how each was
resolved. Kept as they were discovered rather than reconstructed later —
this is meant to be the source material for the Week 7 README and
interview stories, not a polished narrative.

---

## Architecture decisions

### City: Capital Bikeshare over Divvy
Compared live feed liveness, station count, and trip history depth for
both. Capital Bikeshare won on trip history depth (2010+, vs. Divvy's
shorter public history) and a lighter station count for local dev. Full
comparison: `city-selection.md`.

### Cloud data collection: GitHub Actions + Backblaze B2, not a personal machine
**Problem found:** running pollers on a personal laptop in Kathmandu
meant the local "daytime" (when the laptop is on and attended) is DC's
actual nighttime — a real selection-bias risk that would have
systematically under-sampled the city's actual peak usage hours.

**Fix:** moved collection to GitHub Actions (runs on GitHub's servers,
no timezone dependency), with each poll uploading to a free Backblaze B2
bucket via `src/storage.py` (fails soft / no-op without credentials, so
local dev and tests never need real cloud access).

### GitHub's own `schedule:` trigger is unreliable — switched to `repository_dispatch`
**Problem found:** GitHub Actions' documented `schedule:` cron trigger
is explicitly best-effort, and new/low-activity repositories get the
lowest scheduling priority. Measured on this repo: requested 10-minute
interval, actual delay was 2-3 hours between runs.

**Fix:** switched both workflows to `repository_dispatch`, fired by an
external free service (cron-job.org) making a direct API call to
GitHub's dispatch endpoint. This is a real HTTP request GitHub answers
immediately, not a request sitting in GitHub's internal scheduling
queue. Confirmed: runs now fire within seconds of the ping, not hours.

### Poll interval: 10 minutes, not the plan's default 5 minutes
Deliberate trade-off for lower data volume (measured: ~6MB/day vs.
~12MB/day at 5-min), still dense enough for the 15/30/60-min lag
features the Week 5 model needs. Storage was never actually the
constraint (B2's free 10GB tier comfortably covers either choice over
7 weeks) — this was a bandwidth/simplicity choice, not a necessity.

### `dim_trip_station`: a second station dimension, not a crosswalk fix
See "Live feed provides no station-ID crosswalk" below — this is the
most structurally important finding in the whole build so far.

---

## Real bugs found and fixed (ingestion)

### 1. Mixed timezone-aware/naive timestamps crash the trip-duration calculation
**Symptom:** `TypeError: Cannot subtract tz-naive and tz-aware
datetime-like objects` partway through a real month's backfill.

**Root cause:** some real Capital Bikeshare trip rows have
timezone-aware timestamps (`...T00:15:00-04:00`) mixed with
timezone-naive ones in the *same column*. Pandas can't build one
consistent datetime64 array from a mix, so subtracting `ended_at -
started_at` fails outright.

**Fix:** `pd.to_datetime(..., utc=True, ...)` on both timestamp columns,
forcing everything into one consistent timezone before any arithmetic.

### 2. Pandas date-format inference misfires on genuinely mixed formats
**Symptom:** after fixing #1, a *different* problem appeared — a
perfectly well-formed, ordinary timestamp was getting silently
coerced to `NaT` for no apparent reason.

**Root cause:** pandas tries to infer *one* date format from a column
and cache it for speed. With genuinely mixed formats present (from
issue #1), that inference can misfire and wrongly reject valid rows
that don't match the guessed pattern.

**Fix:** `format="mixed"` — tells pandas to parse each row
independently instead of assuming one shared format.

**Verification:** both fixes stress-tested against 5,000 randomly
generated rows across 10 different injected garbage patterns before
trusting them.

### 3. Old-era and new-era trip files produce incompatible physical Parquet types
**Symptom:** `dbt`/DuckDB refused to read old (pre-2020) and new
(2020+) trip files together — `NULL type` vs `VARCHAR` for `trip_id`,
`int64` vs `float64` for `duration_seconds` — despite both having
"the same" canonical column names.

**Root cause:** old-era trips have no `trip_id` at all, so a column of
all-`None` gets written to Parquet as an ambiguous type with no
information about what it *would* be. Column NAMES matching across
schema-drift mappings isn't enough — physical dtypes have to match too.

**Fix:** explicit `CANONICAL_DTYPES` enforcement applied to both eras'
output before it's ever written, rather than relying on each column
assignment happening to agree.

### 4. `__MACOSX` junk files inside trip data zips
**Symptom:** confusing "unrecognized trip CSV schema" warnings on
every single month's backfill.

**Root cause:** zip files created on macOS include hidden
`__MACOSX/._*.csv` resource-fork metadata — not real data, but present
in every real Capital Bikeshare monthly zip.

**Fix:** explicit `_is_junk_zip_entry()` check skips these before
attempting to parse them at all.

### 5. Station IDs get a spurious trailing `.0`
**Symptom:** `start_station_id` values like `"32418.0"` instead of
`"32418"`.

**Root cause:** the Week 1 finding (~15-17% of trips have a missing
station ID) means the column has real `NaN`s mixed with real IDs —
which forces pandas to read the *entire* column as `float64` (a plain
integer column can't represent `NaN`). A bare `.astype(str)` on that
float column bakes the `.0` into every value permanently.

**Fix:** `_clean_station_id()` — converts whole-number floats back to
clean integer-looking strings, preserves real missing values as
actual nulls (not the literal string `"nan"`).

### 6. Wrong GBFS field name assumed for the legacy station code
**Symptom:** `dbt` error — `Referenced column "legacy_id" not found`.

**Root cause:** assumed the older GBFS spec's field name (`legacy_id`)
without checking the real live feed, which actually uses
`external_id`. GBFS field naming isn't fully consistent across spec
versions and feed implementations.

**Fix:** corrected the field reference. Left a comment flagging this
as a thing to re-check if the project ever swaps to a different city's
feed.

---

## The big structural finding: live feed provides no real station-ID crosswalk

**Symptom:** a `relationships` test checking that every trip's station
ID exists in the live station dimension failed for **~10 million of
~10 million rows** — essentially total failure, not a small data
quality issue.

**Investigation:** GBFS's `external_id` field exists specifically to
bridge a modern feed's UUID-style `station_id` back to a system's
legacy numeric station codes. Checked the real, current data: on this
feed, `external_id` is **identical to `station_id`** for every single
station — Capital Bikeshare's live feed no longer actually populates
that bridge field with the real legacy number. The crosswalk the GBFS
spec describes doesn't functionally exist in this feed anymore.

Trip data (all eras, including the current 2024-2025 backfill) has
always referenced stations by the *old* numeric scheme. There is
currently no live-data path from "numeric code in a trip record" to
"which live, real-time station is that."

**Resolution:** rather than force a join that structurally cannot
work, built `dim_trip_station` — a station reference table derived
directly from trip data's own self-reported station name and exact
coordinates (present on every trip, both start and end side). This
matches `fct_trip`'s ID scheme *by construction*, since it's built
from the same data. `dim_station` (the SCD2 snapshot from the live
feed) is kept as-is for what it's actually good for: real-time station
state (current capacity, current status) — not for joining to
historical trips.

**Result after the fix:** the relationship test went from ~10 million
mismatches to a full **PASS** — zero mismatches, verified on the real
~10M+ row dataset, not just a small sample.

**What this can't do:** tell you a *historical* trip's station's
*current* live capacity — that specific cross-reference (e.g., "this
station sees 500 trips/month but only has 15 docks today") isn't
reliably answerable without a real crosswalk, which doesn't exist in
the live data. Noted as a known limitation rather than papered over.

---

## Real, investigated data quality findings (not bugs — kept as warnings)

These all show up as `WARN`, not `ERROR`, in `dbt build` — each was
specifically investigated to confirm it's real-world messiness, not a
pipeline defect, before deciding to keep it visible-but-non-blocking
rather than either hiding it or breaking every build over it.

### ~15-17% of trips have a missing/null station ID
Found in Week 1. Most likely explanation: dockless e-bike trip
endpoints that don't correspond to a formal dock/station.

### 141 duplicate `trip_id` values across ~10M+ trips (2024-2025)
Investigated by comparing the true UTC start times of colliding pairs:
confirmed these are **genuinely different physical trips** (different
actual start times, different durations to the second) that happen to
share an identical `ride_id` string — a real, rare ID collision in
Capital Bikeshare's own public data. At this volume (~0.001-0.002%),
consistent with a large-but-not-cryptographically-designed ID space.

### 371 trips where `ended_at < started_at`
Concentrated around specific dates consistent with the US Daylight
Saving Time "fall back" transition. Source timestamps are naive local
(America/New_York) wall-clock strings; this pipeline currently treats
naive timestamps as literal UTC without DST-aware localization, so
trips spanning the one repeated hour each November can show a
negative duration. Real, bounded, well-understood phenomenon — not
worth blocking every build over, but a genuine, explainable finding.

### 10,072 trips with a negative or >24-hour duration
Consistent with the well-known "bike checked out and never properly
redocked" pattern common to every real-world bikeshare system (lost,
stolen, or a forgotten return). ~0.1-0.2% of total trips — a normal
rate for this kind of system.

---

## Process finding: stale incremental models after upstream fixes

**Symptom:** after fixing the station-ID crosswalk issue and rebuilding
`dim_trip_station` fresh, the relationship test *still* showed ~10
million mismatches — nearly unchanged from before the fix.

**Root cause:** `fct_trip` is materialized as `incremental` — it
doesn't fully rebuild on every run, only reprocessing a small recent
lookback window. Several upstream fixes had landed since `fct_trip`
was first built, but the bulk of its ~10M rows were still the *original*,
stale computation from before those fixes — while `dim_trip_station`
(a plain table, fully rebuilt every run) reflected the current, fixed
logic. Comparing fresh data against stale data looked identical to a
real mismatch.

**Fix:** `dbt build --full-refresh` — forces incremental models to
fully drop and rebuild from current logic rather than trusting
previously-computed rows. Resolved immediately: relationship test went
from ~10M mismatches to a clean PASS.

**Lesson for later weeks:** any time an upstream model's logic changes,
downstream incremental models need a full refresh to actually reflect
it — this is exactly the kind of thing Week 3's Dagster asset checks
and CI should catch automatically rather than relying on remembering
to run `--full-refresh` by hand.
