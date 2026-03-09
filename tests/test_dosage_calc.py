"""ユニットテスト — dosage_calc.py"""

import sys
from pathlib import Path

import pytest
from vet_dose_calc.dosage_calc import (
    parse_dose_range,
    calculate_dose,
    calculate_product_amount,
    round_to_division,
)


class TestParseDoseRange:
    def test_range(self):
        assert parse_dose_range("12.5-25") == (12.5, 25.0)

    def test_single(self):
        assert parse_dose_range("1") == (1.0, 1.0)

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_dose_range("abc")


class TestCalculateDose:
    def test_normal(self):
        r = calculate_dose(5.0, "12.5")
        assert r.dose_min_mg == 62.5
        assert r.dose_max_mg == 62.5

    def test_range(self):
        r = calculate_dose(5.0, "12.5-25")
        assert r.dose_min_mg == 62.5
        assert r.dose_max_mg == 125.0

    def test_zero_weight(self):
        with pytest.raises(ValueError, match="正の値"):
            calculate_dose(0, "10")

    def test_negative_weight(self):
        with pytest.raises(ValueError, match="正の値"):
            calculate_dose(-1, "10")

    def test_excessive_weight(self):
        with pytest.raises(ValueError, match="異常値"):
            calculate_dose(300, "10")


class TestCalculateProductAmount:
    def test_mg_per_tab(self):
        p = {"brand": "Test", "strength": 62.5, "strength_unit": "mg/tab",
             "divisible": True, "min_division": 0.5}
        r = calculate_product_amount(62.5, p)
        assert r.amount == 1.0
        assert r.unit_label == "錠"

    def test_mg_per_ml(self):
        p = {"brand": "Test", "strength": 62.5, "strength_unit": "mg/ml",
             "divisible": False}
        r = calculate_product_amount(62.5, p)
        assert r.amount == 1.0
        assert r.unit_label == "ml"

    def test_iu_per_ml(self):
        p = {"brand": "Test", "strength": 100, "strength_unit": "iu/ml",
             "divisible": False}
        r = calculate_product_amount(50, p)
        assert r.amount == 0.5
        assert r.unit_label == "ml"

    def test_percent(self):
        p = {"brand": "Test", "strength": 2, "strength_unit": "percent",
             "divisible": False}
        r = calculate_product_amount(100, p)
        assert r.amount == 5.0
        assert r.unit_label == "ml"

    def test_rounding_with_division(self):
        p = {"brand": "Test", "strength": 250, "strength_unit": "mg/tab",
             "divisible": True, "min_division": 0.25}
        r = calculate_product_amount(62.5, p)
        assert r.amount == 0.25
        assert r.rounded_amount == 0.25

    def test_rounding_needs_ceil(self):
        p = {"brand": "Test", "strength": 250, "strength_unit": "mg/tab",
             "divisible": True, "min_division": 0.5}
        r = calculate_product_amount(62.5, p)
        assert r.amount == 0.25
        assert r.rounded_amount == 0.5  # ceil to 0.5


class TestRoundToDivision:
    def test_exact(self):
        assert round_to_division(1.0, 0.5) == 1.0

    def test_ceil_half(self):
        assert round_to_division(1.3, 0.5) == 1.5

    def test_ceil_quarter(self):
        assert round_to_division(1.3, 0.25) == 1.5

    def test_zero_division(self):
        assert round_to_division(1.3, 0) == 1.3
