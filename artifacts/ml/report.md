# Day-ahead quantile experiment — SA1 operational demand (our model, not AEMO's)

Generated 2026-09-23T07:59:29Z. Data 2025-08-01 → 2026-09-23, 19728 feature rows. Rolling-origin monthly folds: 2026-04, 2026-05, 2026-06, 2026-07, 2026-08, 2026-09.

| Model | MAE (MW) | RMSE (MW) | Pinball q10 | Pinball q50 | Pinball q90 | q10–q90 coverage (target 0.80) | Mean width (MW) | Test half-hours |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| quantile_linear | 159.748 | 243.193 | 35.573 | 79.874 | 39.964 | 0.796 | 530.148 | 8408 |
| seasonal_naive_7d | 173.618 | 270.346 | 57.402 | 86.809 | 53.873 | 0.894 | 847.797 | 8408 |
| persistence_2d | 185.279 | 271.885 | 53.682 | 92.64 | 56.515 | 0.873 | 813.075 | 8408 |

Leakage checks: every feature timestamp <= issue time (asserted per row); training targets limited to days <= first test day - 2, i.e. published before the first issue time (asserted: no train/test overlap per fold); no weather for the target day is used.

Quantiles and errors belong to this project's simple model. They are not AEMO POE forecasts and not a claim of operational suitability.
