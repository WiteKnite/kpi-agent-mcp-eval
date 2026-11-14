# Forecast study: decisions

This file was written before any of the study's experiments were run. It fixes the data split,
the candidate models, and the rule for choosing among them. Results are appended below each step.

## Data split

- Data: 24 months, 2025-01 to 2026-12. Automated first response starts in 2025-07 (index 6).
- **Development window: 2025-01 to 2026-06** (indices 0 to 17). Used to compare and choose.
- **Holdout: 2026-07 to 2026-12** (indices 18 to 23). Evaluated **once**, after the choice is made.
  `eval/forecast_study.py --holdout` refuses to run a second time.

## Evaluation

- Development: rolling origin, horizon 3, origins 9 to 15 (training always includes at least 3
  post-launch months). Every candidate uses the same origins and the same actual values.
- Holdout: one forecast made at the end of the development window, horizon 6, scored on 2026-07
  to 2026-12.
- Measures: MAE and MAPE, pooled over all series in the step. Bootstrap 95% CI (2000 resamples,
  seed 42) on the MAE difference from the naive baseline, using paired point errors.
- Series: `total`; then per channel (4) and per rep (5) in step 3.

## Candidates

1. `naive`: last value repeats.
2. `ma3`: mean of the last 3 months.
3. `drift`: last value plus the average change across the training history.
4. `trend6_all`: linear trend over the last 6 months, using all history. This is the current
   `forecast_kpi` model and the reference.
5. `trend6_post`: linear trend over the last 6 months, training only on post-launch months.
   Reason: automation changed the response process, so pre-launch months are not a fair guide.
6. `trend6_post_log`: as 5, fitted on log values. Applied to response time only. Reason: response
   times are right-skewed.
7. `holt` (conditional, see below).

Holt's smoothing is not run unless, after step 3, the chosen candidate for some metric still has
a dev-window MAE above the naive baseline. If so, it is run once on the development window and
its result is recorded here before the holdout.

## Choice rule

For each metric, choose the candidate with the lowest pooled development MAE across the step's
series. Ties go to the simpler model. The choice is recorded automatically in
`eval/results/dev_choice.json`.

## Noise floor

Expected absolute error of an observed monthly value around its true value, computed from the
development data: 0.8 times the standard error (conversion rate and response time), or 0.8 times
the standard deviation of monthly counts (leads, an approximation). No model can reliably beat
this floor on the same data.

## Results

(Appended below as each step is run.)
