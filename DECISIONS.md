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

**Correction (made before any holdout run):** the first step-1 run computed the floor over all
development months, including the pre-launch months. Response-time variation there is about 40
minutes, which made the floor 0.79 minutes, below the naive model's error of 0.09. A floor that a
model beats cannot be right. The floor is now computed over post-launch development months
(2025-07 to 2026-06), the same period the forecasts are scored on. The candidates and the choice
rule are unchanged.

## Results

Development window, origins 9 to 15, horizon 3. Full tables in `eval/results/dev_step*.json`.

**Step 1 (total series, baselines).** Conversion: `ma3` 1.31 vs naive 1.57 (gap -0.25, CI
[-0.59, +0.03]; not clearly different from zero). Leads: naive best. Response: `ma3` and naive tie
(0.087 vs 0.089). The tool's model (`trend6_all`) loses on leads and response.

**Step 2 (post-launch training, log response).** Post-launch training removes most of the response
failure: `trend6_post` 0.103 minutes vs `trend6_all` 36.5. Still not better than naive (0.089).
Log transform makes no difference (0.104). For conversion, `trend6_post` (1.47) is not better than
`ma3`.

**Step 3 (10 series: total, 4 channels, 5 reps; 210 points per model).**
- Conversion: `ma3` MAE 3.38 vs naive 4.30 (gap -0.92, CI [-1.27, -0.55]). Better on MAPE too
  (53% vs 73%).
- Leads: `ma3` MAE 8.16 vs naive 9.16 (gap -1.00, CI [-1.67, -0.30]). Better on MAPE too.
- Response: `ma3` MAE 0.126 vs naive 0.140 (gap -0.015, CI [-0.028, -0.002]). Statistically
  distinguishable from zero but tiny in practice.

**Choice by rule:** `ma3` for all three metrics.

**Holt (conditional).** Not run. The trigger is that the chosen model still has a dev MAE above
naive for some metric. Here it is below naive on all three, so the condition is not met.

**Caveat on the noise floor.** The floor reported in step 3 is still computed on the total
series. Channel and rep series have fewer leads per month, so their real floor is higher, and the
model-to-floor comparisons for segments are understated. The gaps versus naive are unaffected.

**Holdout:** choice recorded as `ma3` for every metric. The holdout (2026-07 to 2026-12) was
evaluated once (`eval/results/holdout_result.json`, commit `abc7af6`). Horizon 6, pooled over 10 series:
- Conversion: `ma3` MAE 3.35 vs naive 4.08, gap -0.73, CI [-1.33, -0.13]. Holds.
- Leads: `ma3` 8.57 vs naive 9.38, gap -0.81, CI [-1.64, +0.08]. Not clear.
- Response: `ma3` 0.146 vs naive 0.173, gap -0.027, CI [-0.052, -0.003]. Holds, small.
- The trend model used by `forecast_kpi` does worse on the holdout for all three metrics.

## Product change after the holdout

`forecast_kpi` now uses the 3-month average (`ma3`), the choice from the study. The switch was
made after the holdout had been seen, so the holdout is no longer a clean test of the tool going
forward. Future forecast changes need a new holdout period. The tool's backtest still starts at
origin 6, unlike the study's origin 9, which is why its response-time flag differs.
