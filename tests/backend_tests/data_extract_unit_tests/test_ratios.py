from backend.data_extract import ratios


class TestComputeRatios:
    def test_success_basic_ratios(self):
        income = {"net_income_millions": 50, "total_revenue_millions": 1000,
                  "operating_income_millions": 250}
        # debt-to-equity is TOTAL LIABILITIES ÷ equity (the balance-sheet
        # definition), not long-term debt ÷ equity. 300 / 200 = 1.5.
        balance = {"total_liabilities_millions": 300, "long_term_debt_millions": 100,
                   "shareholders_equity_millions": 200,
                   "total_assets_millions": 500, "total_current_assets_millions": 300,
                   "total_current_liabilities": 150}
        cash_flow = {"free_cash_flow_millions": 200}
        r = ratios.compute_ratios(income, balance, cash_flow)
        assert r["debt_to_equity"] == 1.5
        assert r["return_on_equity_pct"] == 25.0
        assert r["return_on_assets_pct"] == 10.0
        assert r["current_ratio"] == 2.0
        assert r["fcf_margin_pct"] == 20.0
        assert r["operating_margin_pct"] == 25.0
        assert r["net_margin_pct"] == 5.0

    def test_failure_missing_inputs_returns_empty(self):
        assert ratios.compute_ratios({}, {}, {}) == {}

    def test_edge_zero_equity_no_divide_by_zero(self):
        r = ratios.compute_ratios({"net_income_millions": 50},
                                  {"total_liabilities_millions": 300,
                                   "shareholders_equity_millions": 0}, {})
        assert "debt_to_equity" not in r
        assert "return_on_equity_pct" not in r

    def test_edge_debt_to_equity_absent_when_liabilities_missing(self):
        # A missing total-liabilities value is a genuine gap: no D/E emitted
        # (never fabricated from long-term debt or coerced to 0).
        r = ratios.compute_ratios({}, {"long_term_debt_millions": 100,
                                        "shareholders_equity_millions": 200}, {})
        assert "debt_to_equity" not in r

    def test_edge_none_values_skipped(self):
        r = ratios.compute_ratios({"net_income_millions": None, "total_revenue_millions": None},
                                  {"shareholders_equity_millions": None}, {})
        assert r == {}
