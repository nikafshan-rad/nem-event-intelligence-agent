"""The separate quantile experiment: loss, fitting and leakage guards (SYNTHETIC series only)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from nem_agent.ml.experiment import build_rows, fit_quantile, pinball

pytestmark = pytest.mark.synthetic


def test_pinball_loss_values():
    y = np.array([10.0, 10.0])
    assert pinball(y, np.array([8.0, 12.0]), 0.9) == pytest.approx((0.9 * 2 + 0.1 * 2) / 2)
    assert pinball(y, y, 0.5) == 0.0


def test_quantile_fit_recovers_known_quantiles():
    rng = np.random.default_rng(1)
    x = np.column_stack([np.ones(4000), rng.uniform(0, 10, 4000)])
    y = 3 * x[:, 1] + rng.normal(0, 1, 4000)
    for q, z in ((0.1, -1.2816), (0.5, 0.0), (0.9, 1.2816)):
        w = fit_quantile(x, y, q, epochs=2500)
        assert w[1] == pytest.approx(3.0, abs=0.08)
        assert w[0] == pytest.approx(z, abs=0.15)


def test_features_never_postdate_issue_time():
    start = datetime(2099, 1, 1, tzinfo=UTC)
    y = {start + timedelta(minutes=30 * i): 1000.0 + (i % 48) for i in range(48 * 20)}
    temp = {start + timedelta(hours=h): 20.0 for h in range(24 * 21)}
    rows = build_rows(y, temp)
    assert rows
    for r in rows:
        assert r["t"] - timedelta(days=2) <= r["issue"] < r["t"]
