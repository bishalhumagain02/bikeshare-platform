# Model Card: Bike Availability Predictor

## What it does

Predicts `bikes_available` at a given station **60 minutes** into the
future, using live station status, station capacity, a weather
forecast (not actuals — see Leakage Prevention below), and neighboring
station state at prediction time. LightGBM regression.

## How it was evaluated

**Rolling-origin backtest**, not a random train/test split — the plan
explicitly calls a random split on temporal data a leakage trap, since
it would let the model see patterns from timestamps chronologically
adjacent to training data, an advantage a real deployed model never
has. Each fold includes a 60-minute purge gap between train and test
so no training row sits within the prediction horizon of a test row.

**Baselines it must beat, computed on the exact same rows:**
- Persistence (current value, unchanged)
- Seasonal-naive (same value, same hour, 7 days earlier)
- Station-hour historical mean (computed from training data only)

## Results (development run, see caveat below)

On a controlled 5-day synthetic dataset built to mirror the real data
schema exactly:

| | MAE |
|---|---|
| **Model (LightGBM)** | **1.39** |
| Station-hour-mean baseline | 2.80 |
| Persistence baseline | 3.03 |
| Seasonal-naive baseline | 3.12 (only 2/4 folds — see below) |

The model beat every baseline by a wide margin in this controlled run.
Top features by importance: `neighbor_avg_bikes_ratio`,
`rolling_mean_60m`, `hour_sin`/`hour_cos` — consistent with the
intuition that nearby station state and recent trend matter most for
a 60-minute-ahead prediction.

**⚠️ These numbers are from synthetic development data, NOT yet from a
full run on real accumulated station_status history.** Re-run
`python -m src.ml.train` against the real warehouse once enough live
polling history has accumulated (see the honest data-volume caveat in
`docs/DECISIONS.md`) before treating any number here as a real result.

### First real-data run (~3 days of history, 371,514 rows)

| | MAE |
|---|---|
| Persistence baseline | **0.803** (best) |
| Seasonal-naive | 1.349 |
| **Model (LightGBM)** | 0.982 |
| Station-hour-mean baseline | 2.900 |

**The model did not beat the best baseline on this first real run** —
reported honestly, exactly per the plan's own warning that this is a
common, legitimate outcome, not something to hide. With only ~3 days
of real history, persistence (bike counts often don't change much in
60 minutes) is a genuinely hard baseline to beat; there isn't yet
enough variety in the training data for the model to learn much
beyond what persistence already captures. This result should be
re-checked once more weeks of real history accumulate.

A separate real bug was found and fixed during this run — the weather
forecast features initially showed 0% coverage due to a timezone bug
(DuckDB's session timezone defaulting to the host machine's local
setting rather than UTC — see `docs/DECISIONS.md` for the full story).
Re-run after that fix to get a trustworthy read on whether weather
genuinely helps or not; the 0-importance result before the fix was an
artifact of the bug, not a real finding about weather's predictive
value.

## Where it genuinely fails or shouldn't be trusted

- **Seasonal-naive baseline is undercomputed with limited history.**
  It needs a full 7 days of prior data per station; folds early in a
  short real dataset will have this baseline computed on fewer folds
  than the others (reported explicitly in training output, not hidden).
- **Real station_status history is currently thin** (continuous
  cloud polling only recently began — see `docs/DECISIONS.md`). A
  4-fold backtest spanning genuinely different weeks/seasons isn't yet
  possible on real data; the training script adapts to however many
  folds the actual data honestly supports and says so explicitly.
- **The model has not yet been evaluated broken out by station tier**
  (busy vs. quiet stations) as the plan recommends — a good average
  can hide poor performance on the quiet stations that matter most
  operationally. This is a real gap, not yet closed.
- **Weather forecast coverage depends on the forecast archiver having
  run daily without gaps** — any missed day (laptop off, a workflow
  failure) means some prediction rows will have a null forecast
  feature; LightGBM handles missing values natively, but a systematic
  gap (e.g. several consecutive missed days) would degrade the
  weather-related features for that period specifically.
- **Not evaluated for fairness or performance disparities** across
  neighborhoods/regions — a real deployment decision should check this
  before relying on the model to guide rebalancing resource allocation.

## Leakage prevention (see `src/features/build_features.py`)

- Weather **forecast**, not actuals, used for any feature describing
  the future — joined via the forecast's own `issued_at` timestamp,
  filtered to only forecasts that existed at or before prediction time.
  Proven with a deliberate adversarial test
  (`test_forecast_join_never_uses_a_future_issued_forecast`): a fake
  "leaked future" value planted in a forecast issued after prediction
  time is confirmed to never be used.
- All lag/rolling features are backward-looking only, verified by test.
- The station-hour-mean baseline is computed from training data only,
  verified by test (an eval-only extreme value cannot shift its own
  prediction).
- Rolling-origin backtest with an explicit purge gap, not a random split.

## Who shouldn't rely on this yet

Anyone making real operational rebalancing decisions — this is a
portfolio/learning project's model, evaluated so far on synthetic
data and a thin slice of real history. Treat every number in this
document as illustrative of the *pipeline's correctness*, not yet as
a production-ready forecast.
