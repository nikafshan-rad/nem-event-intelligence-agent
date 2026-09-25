"""Separate time-series experiment: day-ahead quantile forecasts of SA1 operational demand (OUR model, not AEMO's).

Setup (all choices are about avoiding leakage, not about maximising a score):

* **Target**: AEMO actual operational demand, next-day (`updated`) values, SA1, half-hourly, NEM time.
* **Issue time**: 12:00 NEM on day D-1 for all 48 half-hours of day D. The features use only data that ends
  >= 36 h before the earliest target: demand lags of 2 and 7 days, day D-2's mean, calendar terms, and NASA POWER
  temperature lagged 2 days (a reanalysis *proxy* for observed temperature). **No target-day weather** is used.
* **Models**: linear quantile regression (pinball loss, numpy, q = 0.1/0.5/0.9) vs **seasonal naive**
  (y(t-7d)) and **persistence** (y(t-2d)); baseline intervals use empirical training-residual quantiles.
* **Evaluation**: rolling origin with expanding training windows, monthly test folds; MAE/RMSE of the median,
  pinball loss per quantile, q10–q90 coverage and width. Quantiles here are this project's, never AEMO's POE.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import numpy as np

from .. import nemweb, paths, rawstore
from ..mmscsv import iter_csv_members, parse_mms_csv
from ..timeutil import NEM_TZ, iso_utc, parse_market

REGION = "SA1"
POINT = ("Adelaide", -34.9285, 138.6007)
QUANTILES = (0.1, 0.5, 0.9)
MIN_TRAIN_DAYS = 120


# ------------------------------------------------------------------------------------------------ data
def fetch_actuals(log: Any = print) -> tuple[dict[datetime, float], list[dict[str, Any]]]:
    """Next-day actual operational demand for REGION from every ACTUAL_DAILY file listed on NEMWeb."""
    manifest: list[dict[str, Any]] = []
    series: dict[datetime, float] = {}
    urls: list[str] = []
    cur, arc = nemweb.DATASET_DIRS["OPDEM_ACTUAL_DAILY"]
    for path in (arc, cur):
        if path is None:
            continue
        _res, entries = nemweb.list_dir(path)
        urls += [e.url for e in entries if not e.is_dir and e.name.upper().endswith(".ZIP")]
    for url in urls:
        rf = rawstore.get("OPDEM_ACTUAL_DAILY", url)
        if not rf.available:
            manifest.append({"url": url, "status": rf.status, "error": rf.error})
            continue
        n = 0
        for mp, csvb in iter_csv_members(Path(rf.local_path).read_bytes(), Path(rf.local_path).name):
            _mf, recs = parse_mms_csv(csvb, mp, wanted={("OPERATIONAL_DEMAND", "ACTUAL")})
            for r in recs:
                if r.values["REGIONID"] == REGION:
                    series[parse_market(r.values["INTERVAL_DATETIME"])] = float(r.values["OPERATIONAL_DEMAND"])
                    n += 1
        manifest.append({"url": url, "sha256": rf.sha256, "retrieved_at": rf.retrieved_at, "rows": n, "status": rf.status})
    log(f"[ml] actual half-hours for {REGION}: {len(series)} from {len(manifest)} files")
    return series, manifest


def fetch_temperature(start: date, end: date, log: Any = print) -> tuple[dict[datetime, float], list[dict[str, Any]]]:
    out: dict[datetime, float] = {}
    manifest = []
    cur = start
    while cur <= end:
        stop = min(end, date(cur.year, 12, 31))
        q = {"parameters": "T2M", "community": "RE", "longitude": POINT[2], "latitude": POINT[1],
             "start": cur.strftime("%Y%m%d"), "end": stop.strftime("%Y%m%d"), "format": "JSON", "time-standard": "UTC"}
        url = "https://power.larc.nasa.gov/api/temporal/hourly/point?" + urlencode(q, quote_via=quote)
        rf = rawstore.get("NASA_POWER_HOURLY", url, max_bytes=20_000_000, timeout=180)
        manifest.append({"url": url, "sha256": rf.sha256, "status": rf.status, "retrieved_at": rf.retrieved_at})
        if rf.available:
            doc = json.loads(Path(rf.local_path).read_text())
            fill = doc.get("header", {}).get("fill_value", -999)
            for stamp, v in doc["properties"]["parameter"]["T2M"].items():
                if v != fill:
                    out[datetime.strptime(stamp, "%Y%m%d%H").replace(tzinfo=UTC)] = float(v)
        cur = stop + timedelta(days=1)
    log(f"[ml] NASA POWER T2M hours: {len(out)}")
    return out, manifest


# ------------------------------------------------------------------------------------------------ features
def market_day(t: datetime) -> date:
    return (t - timedelta(minutes=30)).astimezone(NEM_TZ).date()  # interval-ending: 00:00 belongs to the previous day


def build_rows(y: dict[datetime, float], temp: dict[datetime, float]) -> list[dict[str, Any]]:
    by_day: dict[date, list[float]] = {}
    for t, v in y.items():
        by_day.setdefault(market_day(t), []).append(v)
    day_mean = {d: float(np.mean(v)) for d, v in by_day.items() if len(v) == 48}
    rows = []
    for t, v in sorted(y.items()):
        d = market_day(t)
        issue = datetime.combine(d - timedelta(days=1), datetime.min.time(), tzinfo=NEM_TZ) + timedelta(hours=12)
        lag2, lag7 = y.get(t - timedelta(days=2)), y.get(t - timedelta(days=7))
        m2 = day_mean.get(d - timedelta(days=2))
        th = (t - timedelta(days=2)).replace(minute=0)
        tmp = temp.get(th)
        if None in (lag2, lag7, m2, tmp):
            continue
        # leakage guard: every feature timestamp must be at or before the issue time
        latest_feature = max(t - timedelta(days=2), th + timedelta(hours=1))
        assert latest_feature <= issue, "feature after issue time"
        hh = int(((t - timedelta(minutes=30)).astimezone(NEM_TZ).hour * 60 + (t - timedelta(minutes=30)).astimezone(NEM_TZ).minute) / 30)
        dow = t.astimezone(NEM_TZ).weekday()
        rows.append({"t": t, "day": d, "issue": issue, "y": v, "lag2": lag2, "lag7": lag7, "mean_d2": m2, "temp_lag2": tmp,
                     "hh": hh, "dow": dow})
    return rows


def design(rows: list[dict[str, Any]]) -> np.ndarray:
    cols = []
    for r in rows:
        ang = 2 * math.pi * r["hh"] / 48
        harm = [f(k * ang) for k in (1, 2, 3) for f in (math.sin, math.cos)]
        dow = [1.0 if r["dow"] == k else 0.0 for k in range(6)]
        cols.append([1.0, r["lag2"], r["lag7"], r["mean_d2"], r["temp_lag2"], r["temp_lag2"] ** 2, *harm, *dow,
                     r["lag2"] * harm[0], r["lag7"] * harm[1]])
    return np.asarray(cols, dtype=float)


def fit_quantile(x: np.ndarray, y: np.ndarray, q: float, epochs: int = 1500, lr: float = 0.05, seed: int = 0) -> np.ndarray:
    """Linear quantile regression by Adam on the pinball loss (standardised features)."""
    mu, sd = x[:, 1:].mean(0), x[:, 1:].std(0) + 1e-9
    xs = np.hstack([x[:, :1], (x[:, 1:] - mu) / sd])
    ym, ysd = y.mean(), y.std() + 1e-9
    yt = (y - ym) / ysd
    rng = np.random.default_rng(seed)
    w: Any = rng.normal(0, 0.01, xs.shape[1])
    m = np.zeros_like(w)
    v = np.zeros_like(w)
    for i in range(1, epochs + 1):
        r = yt - xs @ w
        g = -(xs * np.where(r >= 0, q, q - 1)[:, None]).mean(0)
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        w -= lr * (m / (1 - 0.9 ** i)) / (np.sqrt(v / (1 - 0.999 ** i)) + 1e-8)
    # fold standardisation back into raw-feature weights
    raw = np.empty_like(w)
    raw[1:] = w[1:] / sd * ysd
    raw[0] = w[0] * ysd + ym - float((mu * raw[1:]).sum())
    return raw


def pinball(y: np.ndarray, p: np.ndarray, q: float) -> float:
    d = y - p
    return float(np.mean(np.maximum(q * d, (q - 1) * d)))


def evaluate(rows: list[dict[str, Any]], n_folds: int = 6) -> dict[str, Any]:
    months = sorted({(r["day"].year, r["day"].month) for r in rows})
    folds = months[-n_folds:]
    results: dict[str, list[dict[str, Any]]] = {"quantile_linear": [], "seasonal_naive_7d": [], "persistence_2d": []}
    for ym in folds:
        test = [r for r in rows if (r["day"].year, r["day"].month) == ym]
        first_day = min(r["day"] for r in test)
        # next-day actuals for day X are published ~04:40 on X+1, so at the first issue time (12:00 on first_day-1)
        # only targets up to day first_day-2 are known: train strictly on those
        train = [r for r in rows if r["day"] <= first_day - timedelta(days=2)]
        if len({r["day"] for r in train}) < MIN_TRAIN_DAYS or not test:
            continue
        assert max(r["t"] for r in train) < min(r["t"] for r in test), "train/test overlap"
        xtr, ytr = design(train), np.array([r["y"] for r in train])
        xte, yte = design(test), np.array([r["y"] for r in test])
        preds = {q: xte @ fit_quantile(xtr, ytr, q) for q in QUANTILES}
        preds[0.1], preds[0.9] = np.minimum(preds[0.1], preds[0.5]), np.maximum(preds[0.9], preds[0.5])  # no crossing
        base_fold = {"fold": f"{ym[0]}-{ym[1]:02d}", "n_train": len(train), "n_test": len(test),
                     "train_end_utc": iso_utc(max(r["t"] for r in train)), "test_start_utc": iso_utc(min(r["t"] for r in test))}
        results["quantile_linear"].append({**base_fold, **_metrics(yte, preds)})
        for name, key in (("seasonal_naive_7d", "lag7"), ("persistence_2d", "lag2")):
            ptr = np.array([r[key] for r in train])
            resid = ytr - ptr
            pt = np.array([r[key] for r in test])
            bp = {q: pt + np.quantile(resid, q) for q in QUANTILES}
            bp[0.5] = pt  # point baseline: the lag itself
            results[name].append({**base_fold, **_metrics(yte, bp)})
    summary = {}
    for name, fs in results.items():
        if not fs:
            continue
        w = np.array([f["n_test"] for f in fs], dtype=float)
        summary[name] = {k: round(float(np.average([f[k] for f in fs], weights=w)), 3)
                         for k in ("mae_mw", "rmse_mw", "pinball_q10", "pinball_q50", "pinball_q90", "coverage_q10_q90",
                                   "mean_interval_width_mw")}
        summary[name]["n_test_half_hours"] = int(w.sum())
    return {"folds": results, "summary": summary, "fold_months": [f"{y}-{m:02d}" for y, m in folds]}


def _metrics(y: np.ndarray, p: dict[float, np.ndarray]) -> dict[str, float]:
    return {"mae_mw": float(np.mean(np.abs(y - p[0.5]))), "rmse_mw": float(np.sqrt(np.mean((y - p[0.5]) ** 2))),
            "pinball_q10": pinball(y, p[0.1], 0.1), "pinball_q50": pinball(y, p[0.5], 0.5),
            "pinball_q90": pinball(y, p[0.9], 0.9),
            "coverage_q10_q90": float(np.mean((y >= p[0.1]) & (y <= p[0.9]))),
            "mean_interval_width_mw": float(np.mean(p[0.9] - p[0.1]))}


def run(out: Path, log: Any = print) -> dict[str, Any]:
    res: dict[str, Any]
    y, man_y = fetch_actuals(log)
    if len(y) < 48 * (MIN_TRAIN_DAYS + 60):
        res = {"status": "UNVERIFIED/DEFERRED", "reason": f"only {len(y)} half-hours of actuals available; need "
                                                           f">= {48 * (MIN_TRAIN_DAYS + 60)}", "sources": man_y}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, indent=2))
        return res
    days = sorted({market_day(t) for t in y})
    temp, man_t = fetch_temperature(days[0] - timedelta(days=8), days[-1], log)
    rows = build_rows(y, temp)
    ev = evaluate(rows)
    res = {
        "status": "measured", "generated_at": iso_utc(datetime.now(UTC)), "region": REGION,
        "target": "AEMO actual operational demand (next-day ACTUAL_DAILY values), half-hourly, MW",
        "issue_time": "12:00 NEM on D-1 for all half-hours of day D",
        "features": ["demand lag 2 days", "demand lag 7 days", "mean demand of day D-2",
                     "NASA POWER T2M at Adelaide lagged 2 days (reanalysis proxy; no target-day weather)",
                     "half-hour-of-day harmonics", "day-of-week"],
        "leakage_checks": ["every feature timestamp <= issue time (asserted per row)",
                           "training targets limited to days <= first test day - 2, i.e. published before the first "
                           "issue time (asserted: no train/test overlap per fold)",
                           "no weather for the target day is used"],
        "n_rows": len(rows), "date_range": [str(days[0]), str(days[-1])],
        "evaluation": ev, "sources": {"actuals": man_y, "weather": man_t},
        "disclaimer": "Quantiles and errors belong to this project's simple model. They are not AEMO POE forecasts and "
                      "not a claim of operational suitability.",
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str))
    (out.parent / "report.md").write_text(render(res))
    return res


def render(res: dict[str, Any]) -> str:
    s = res["evaluation"]["summary"]
    lines = [f"# Day-ahead quantile experiment — {res['region']} operational demand (our model, not AEMO's)", "",
             f"Generated {res['generated_at']}. Data {res['date_range'][0]} → {res['date_range'][1]}, {res['n_rows']} "
             f"feature rows. Rolling-origin monthly folds: {', '.join(res['evaluation']['fold_months'])}.", "",
             "| Model | MAE (MW) | RMSE (MW) | Pinball q10 | Pinball q50 | Pinball q90 | q10–q90 coverage (target 0.80) | Mean width (MW) | Test half-hours |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, m in s.items():
        lines.append(f"| {name} | {m['mae_mw']} | {m['rmse_mw']} | {m['pinball_q10']} | {m['pinball_q50']} | {m['pinball_q90']} | "
                     f"{m['coverage_q10_q90']} | {m['mean_interval_width_mw']} | {m['n_test_half_hours']} |")
    lines += ["", "Leakage checks: " + "; ".join(res["leakage_checks"]) + ".", "", res["disclaimer"], ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(paths.artifacts_dir() / "ml" / "experiment.json"))
    args = ap.parse_args()
    res = run(Path(args.out))
    print(json.dumps({"status": res["status"], "summary": res.get("evaluation", {}).get("summary"),
                      "reason": res.get("reason")}, indent=2))
    return 0 if res["status"] == "measured" else 3


if __name__ == "__main__":
    raise SystemExit(main())
