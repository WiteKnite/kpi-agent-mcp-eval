"""Forecast study, as pre-registered in DECISIONS.md.

  python eval/forecast_study.py --step 1    development window, step 1 (total series, baselines)
  python eval/forecast_study.py --step 2    adds post-launch training and log response time
  python eval/forecast_study.py --step 3    adds per-channel and per-rep series
  python eval/forecast_study.py --holdout   holdout, once; uses the choice from the last dev run

Development results are re-runnable. The holdout refuses to run twice.
"""
import argparse
import json
import math
import pathlib
import random
import sqlite3
import statistics
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kpi_agent import tools  # noqa: E402  (reuses the trend fit that forecast_kpi uses)

DB = ROOT / "data" / "sales.db"
RESULTS = ROOT / "eval" / "results"
LAUNCH = "2025-07"
DEV_LAST = "2026-06"
H_DEV = 3
DEV_ORIGINS = range(9, 16)  # last actual month is index 17 (2026-06)
HOLDOUT_START = 18  # 2026-07
HOLDOUT_H = 6
METRICS = ["conversion_rate_pct", "leads", "avg_first_response_minutes"]
CHANNELS = ["web_form", "whatsapp", "phone", "email"]
REPS = ["Amira", "Bruno", "Chen", "Dana", "Eli"]
SEED = 42
BOOT = 2000


# ---------- data ----------

def load_rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT month, channel, rep, first_response_minutes, converted FROM leads"
        ).fetchall()
    finally:
        con.close()


def monthly(rows, metric):
    by = {}
    for month, _ch, _rep, resp, conv in rows:
        by.setdefault(month, []).append((resp, conv))
    months = sorted(by)
    vals = []
    for m in months:
        items = by[m]
        if metric == "conversion_rate_pct":
            vals.append(100 * sum(c for _, c in items) / len(items))
        elif metric == "leads":
            vals.append(float(len(items)))
        else:
            vals.append(statistics.fmean(r for r, _ in items))
    return months, vals


def segments(rows, step):
    out = {"total": rows}
    if step >= 3:
        for ch in CHANNELS:
            out[f"channel={ch}"] = [r for r in rows if r[1] == ch]
        for rep in REPS:
            out[f"rep={rep}"] = [r for r in rows if r[2] == rep]
    return out


# ---------- models (each takes history months, history values, horizon) ----------

def naive(m, v, h):
    return [v[-1]] * h


def ma3(m, v, h):
    return [statistics.fmean(v[-3:])] * h


def drift(m, v, h):
    slope = (v[-1] - v[0]) / (len(v) - 1)
    return [v[-1] + slope * k for k in range(1, h + 1)]


def trend6_all(m, v, h):
    return tools._trend_forecast(v, h)


def _post_launch(m, v):
    start = next(i for i, mm in enumerate(m) if mm >= LAUNCH)
    if len(v) - start < 3:
        raise ValueError("fewer than 3 post-launch months")
    return v[start:]


def trend6_post(m, v, h):
    return tools._trend_forecast(_post_launch(m, v), h)


def trend6_post_log(m, v, h):
    logs = [math.log(x) for x in _post_launch(m, v)]
    return [math.exp(x) for x in tools._trend_forecast(logs, h)]


def candidates(metric, step):
    c = {"naive": naive, "ma3": ma3, "drift": drift, "trend6_all": trend6_all}
    if step >= 2:
        c["trend6_post"] = trend6_post
        if metric == "avg_first_response_minutes":
            c["trend6_post_log"] = trend6_post_log
    return c


# ---------- scoring ----------

def points(series_list, model, origins, h):
    pts = []
    for months, vals in series_list:
        for t in origins:
            pred = model(months[:t], vals[:t], h)
            pts += list(zip(vals[t : t + h], pred))
    return pts


def mae(pts):
    return statistics.fmean(abs(a - p) for a, p in pts)


def mape(pts):
    errs = [abs(a - p) / abs(a) for a, p in pts if a]
    return 100 * statistics.fmean(errs)


def bootstrap_gap(model_pts, naive_pts):
    """Mean of (model abs error - naive abs error); negative means the model is better."""
    diffs = [abs(a - pm) - abs(a - pn) for (a, pm), (_, pn) in zip(model_pts, naive_pts)]
    rng = random.Random(SEED)
    n = len(diffs)
    means = sorted(statistics.fmean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(BOOT))
    return statistics.fmean(diffs), means[int(0.025 * BOOT)], means[int(0.975 * BOOT)]


def noise_floor(dev_rows, metric):
    """0.8 x standard error of a monthly value (about the expected absolute deviation)."""
    by = {}
    for month, _c, _r, resp, conv in dev_rows:
        by.setdefault(month, []).append((resp, conv))
    groups = list(by.values())
    if metric == "conversion_rate_pct":
        ses = []
        for items in groups:
            n = len(items)
            p = sum(c for _, c in items) / n
            ses.append(100 * math.sqrt(p * (1 - p) / n))
        return 0.8 * statistics.fmean(ses)
    if metric == "avg_first_response_minutes":
        ses = [statistics.stdev(r for r, _ in items) / math.sqrt(len(items)) for items in groups]
        return 0.8 * statistics.fmean(ses)
    # Leads: no true-rate model to measure against, so use the spread of monthly counts.
    return 0.8 * statistics.stdev(len(items) for items in groups)


# ---------- runs ----------

def run_dev(step, rows):
    dev_rows = [r for r in rows if r[0] <= DEV_LAST]
    segs = segments(dev_rows, step)
    report, choice = {}, {}
    for metric in METRICS:
        series = [monthly(srows, metric) for srows in segs.values()]
        scored = {}
        for name, model in candidates(metric, step).items():
            pts = []
            for months, vals in series:
                pts += points([(months, vals)], model, DEV_ORIGINS, H_DEV)
            scored[name] = pts
        naive_pts = scored["naive"]
        rows_out = {}
        for name, pts in scored.items():
            entry = {"mae": round(mae(pts), 4), "mape_pct": round(mape(pts), 2)}
            if name != "naive":
                gap, lo, hi = bootstrap_gap(pts, naive_pts)
                entry["mae_gap_vs_naive"] = round(gap, 4)
                entry["gap_ci95"] = [round(lo, 4), round(hi, 4)]
            rows_out[name] = entry
        best = min(scored, key=lambda k: mae(scored[k]))  # dict order: simplest first on ties
        post_rows = [r for r in dev_rows if r[0] >= LAUNCH]  # the period the forecasts are scored on
        report[metric] = {
            "noise_floor": round(noise_floor(post_rows, metric), 4),
            "models": rows_out,
            "series_count": len(series),
            "points_per_model": len(naive_pts),
        }
        choice[metric] = best
    (RESULTS / f"dev_step{step}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (RESULTS / "dev_choice.json").write_text(
        json.dumps({"step": step, "choice": choice}, indent=2), encoding="utf-8"
    )
    print_report(f"Development, step {step}", report, choice)


def run_holdout(rows):
    guard = RESULTS / "holdout_result.json"
    if guard.exists():
        sys.exit("Holdout already run. It is evaluated once; see holdout_result.json.")
    choice = json.loads((RESULTS / "dev_choice.json").read_text(encoding="utf-8"))
    segs = segments(rows, 3)
    report = {}
    for metric in METRICS:
        series = [monthly(srows, metric) for srows in segs.values()]
        cands = candidates(metric, 3)
        names = ["naive", "trend6_all", choice["choice"][metric]]
        scored = {}
        for name in dict.fromkeys(names):  # unique, keeps order
            pts = []
            for months, vals in series:
                pts += points([(months, vals)], cands[name], [HOLDOUT_START], HOLDOUT_H)
            scored[name] = pts
        out = {}
        for name, pts in scored.items():
            entry = {"mae": round(mae(pts), 4), "mape_pct": round(mape(pts), 2)}
            if name != "naive":
                gap, lo, hi = bootstrap_gap(pts, scored["naive"])
                entry["mae_gap_vs_naive"] = round(gap, 4)
                entry["gap_ci95"] = [round(lo, 4), round(hi, 4)]
            out[name] = entry
        report[metric] = {"chosen_on_dev": choice["choice"][metric], "models": out}
    guard.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Holdout 2026-07 to 2026-12, horizon 6, pooled over all series")
    for metric, r in report.items():
        print(f"\n{metric} (chosen on dev: {r['chosen_on_dev']})")
        for name, e in r["models"].items():
            extra = ""
            if "mae_gap_vs_naive" in e:
                extra = f"  gap {e['mae_gap_vs_naive']:+.3f} CI [{e['gap_ci95'][0]:+.3f}, {e['gap_ci95'][1]:+.3f}]"
            print(f"  {name:16} MAE {e['mae']:>10}  MAPE {e['mape_pct']:>8}{extra}")


def print_report(title, report, choice):
    print(f"{title}  (dev window 2025-01 to {DEV_LAST}, origins 9-15, horizon 3)")
    for metric, r in report.items():
        print(f"\n{metric}  series={r['series_count']}  points/model={r['points_per_model']}  "
              f"noise floor MAE~{r['noise_floor']}")
        for name, e in r["models"].items():
            extra = ""
            if "mae_gap_vs_naive" in e:
                extra = f"  gap {e['mae_gap_vs_naive']:+.3f} CI [{e['gap_ci95'][0]:+.3f}, {e['gap_ci95'][1]:+.3f}]"
            print(f"  {name:16} MAE {e['mae']:>10}  MAPE {e['mape_pct']:>8}{extra}")
        print(f"  chosen by rule: {choice[metric]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, choices=[1, 2, 3], default=3)
    ap.add_argument("--holdout", action="store_true")
    args = ap.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    if args.holdout:
        run_holdout(rows)
    else:
        run_dev(args.step, rows)


if __name__ == "__main__":
    main()
