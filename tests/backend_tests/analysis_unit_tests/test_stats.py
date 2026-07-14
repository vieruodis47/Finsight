"""Unit tests for the Analysis forecast model (backend/analysis/stats.py).

Guards the #54 fixes: geometric fit for growth series, trend-relative (not
global-mean) anomaly detection, and an anchored projection that stays on the
right side of the latest actual. All series here are synthetic and deterministic
— no network, no SEC access.
"""
import math

from backend.analysis import stats


def _series(values, start_year=2010, month_day="12-31"):
    """Build a {period-end -> value} dict the model expects (keys sorted by year)."""
    return {f"{start_year + i}-{month_day}": v for i, v in enumerate(values)}


class TestGeometricSelection:
    def test_strictly_positive_series_uses_geometric(self):
        assert stats._use_geometric([100.0, 115.0, 132.0]) is True

    def test_non_positive_series_stays_linear(self):
        # A net-margin loss year (negative) can't be logged -> linear space.
        assert stats._use_geometric([12.0, -3.0, 8.0]) is False

    def test_too_short_series_is_not_geometric(self):
        assert stats._use_geometric([100.0, 115.0]) is False


class TestAcceleratingGrowth:
    """The core #54 regression: an accelerating positive series must not project
    below its latest actual."""

    def setup_method(self):
        # Constant 15% growth -> perfectly log-linear (accelerating in dollars).
        self.values = [100.0 * (1.15 ** i) for i in range(10)]
        self.d = _series(self.values)

    def test_prediction_at_or_above_latest_actual(self):
        pred = stats.predict_next_value(self.d)
        assert pred is not None
        assert pred["geometric"] is True
        assert pred["predicted_value"] >= self.values[-1]

    def test_trend_is_improving(self):
        assert stats.predict_next_value(self.d)["trend"] == "improving"

    def test_projection_tracks_the_growth_rate(self):
        # Anchored + geometric: next ~= last * 1.15 for a clean 15% series.
        pred = stats.predict_next_value(self.d)
        assert math.isclose(pred["predicted_value"], self.values[-1] * 1.15, rel_tol=0.02)

    def test_next_label_is_year_after_latest(self):
        # Latest key is 2019-12-31 -> FY2020.
        assert stats.predict_next_value(self.d)["next_label"].startswith("FY2020")

    def test_clean_fit_has_high_reliability_and_no_anomalies(self):
        analysis = stats.analyze_metric(self.d, "revenue")
        assert analysis["prediction"]["reliability"] == "high"
        assert analysis["anomalies"] == {}


class TestTrendRelativeDenoising:
    """The bug behind #54: global-mean z-scores flagged the newest, largest value
    of a steep series as an outlier and flattened the forecast toward the mean."""

    def test_on_trend_endpoint_is_not_flagged(self):
        values = [100.0 * (1.15 ** i) for i in range(10)]
        _, anomalies = stats.denoise_series(_series(values))
        latest_year = max(_series(values))
        assert latest_year not in anomalies

    def test_genuine_outlier_is_flagged_and_replaced_with_trend(self):
        values = [100.0 * (1.12 ** i) for i in range(9)]
        values[3] *= 1.8  # inject a clear mid-series spike
        d = _series(values)
        denoised, anomalies = stats.denoise_series(d)
        spike_year = sorted(d)[3]
        assert spike_year in anomalies
        # Replaced toward the trend, i.e. pulled well below the raw spike.
        assert denoised[spike_year] < values[3]

    def test_outlier_does_not_drag_projection_below_latest(self):
        values = [100.0 * (1.12 ** i) for i in range(9)]
        values[3] *= 1.8
        pred = stats.analyze_metric(_series(values), "revenue")["prediction"]
        assert pred["predicted_value"] >= values[-1]


class TestLinearAndDeclining:
    def test_negative_bearing_series_uses_linear_space(self):
        # Margins that dip negative must not crash and must fit linearly.
        values = [10.0, 8.0, -2.0, 4.0, 9.0, 11.0]
        pred = stats.predict_next_value(_series(values))
        assert pred is not None
        assert pred["geometric"] is False

    def test_declining_series_projects_down_and_reads_declining(self):
        values = [200.0 * (0.9 ** i) for i in range(8)]  # steady decline
        pred = stats.predict_next_value(_series(values))
        assert pred["trend"] == "declining"
        assert pred["predicted_value"] <= values[-1]


class TestConfidenceInterval:
    def test_interval_brackets_the_point_estimate(self):
        values = [100.0 * (1.1 ** i) for i in range(8)]
        pred = stats.predict_next_value(_series(values))
        lo, hi = pred["confidence_interval"]
        assert lo <= pred["predicted_value"] <= hi

    def test_noisier_series_has_a_wider_relative_band(self):
        clean = [100.0 * (1.1 ** i) for i in range(10)]
        noisy = [v * (1.15 if i % 2 else 0.85) for i, v in enumerate(clean)]

        def rel_width(values):
            p = stats.predict_next_value(_series(values))
            lo, hi = p["confidence_interval"]
            return (hi - lo) / p["predicted_value"]

        assert rel_width(noisy) > rel_width(clean)


class TestGuards:
    def test_too_few_points_returns_none(self):
        assert stats.predict_next_value(_series([100.0, 120.0])) is None

    def test_none_values_are_ignored(self):
        d = _series([100.0, 110.0, 121.0, 133.0])
        d["2014-12-31"] = None
        pred = stats.predict_next_value(d)
        assert pred is not None
