"""用量計算コアロジック — 体重→投与量→錠数/ml数"""

import math
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class DoseResult:
    dose_min_mg: float
    dose_max_mg: float
    indication: str
    frequency: str
    route: str
    duration: str
    notes: str


@dataclass
class ProductAmount:
    brand: str
    strength: float
    strength_unit: str
    amount: float
    unit_label: str  # "錠", "ml", "カプセル", etc.
    rounded_amount: Optional[float]  # min_division で丸めた値


def parse_dose_range(dose_str: str) -> tuple[float, float]:
    """'12.5-25' → (12.5, 25.0), '1' → (1.0, 1.0)"""
    dose_str = str(dose_str).strip()
    match = re.match(r"^([\d.]+)\s*-\s*([\d.]+)$", dose_str)
    if match:
        return float(match.group(1)), float(match.group(2))
    try:
        v = float(dose_str)
        return v, v
    except ValueError:
        raise ValueError(f"用量をパースできません: '{dose_str}'")


def calculate_dose(weight_kg: float, dose_mg_per_kg: str, indication: str = "",
                   frequency: str = "", route: str = "", duration: str = "",
                   notes: str = "") -> DoseResult:
    """体重と用量/kgから必要量を計算"""
    if weight_kg <= 0:
        raise ValueError(f"体重は正の値でなければなりません: {weight_kg}")
    if weight_kg > 200:
        raise ValueError(f"体重が異常値です: {weight_kg}kg")

    dose_min, dose_max = parse_dose_range(dose_mg_per_kg)
    return DoseResult(
        dose_min_mg=round(dose_min * weight_kg, 2),
        dose_max_mg=round(dose_max * weight_kg, 2),
        indication=indication,
        frequency=frequency,
        route=route,
        duration=duration,
        notes=notes,
    )


def round_to_division(amount: float, min_division: float) -> float:
    """min_divisionの倍数に切り上げ丸め。
    例: round_to_division(1.3, 0.5) → 1.5
        round_to_division(1.3, 0.25) → 1.5
    """
    if min_division <= 0:
        return amount
    return math.ceil(amount / min_division) * min_division


def calculate_product_amount(required_mg: float, product: dict) -> ProductAmount:
    """必要量(mg)から商品の投与量（錠数/ml数等）を計算"""
    strength = product["strength"]
    unit = product["strength_unit"]
    brand = product.get("brand", "不明")
    divisible = product.get("divisible", False)
    min_division = product.get("min_division")

    if strength <= 0:
        raise ValueError(f"商品 '{brand}' の strength が不正: {strength}")

    # 単位ごとの計算
    if unit in ("mg/tab", "mg/cap", "mg/packet", "mcg/tab"):
        amount = required_mg / strength
        labels = {"mg/tab": "錠", "mg/cap": "カプセル", "mg/packet": "包", "mcg/tab": "錠"}
        unit_label = labels[unit]
    elif unit == "mg/ml":
        amount = required_mg / strength
        unit_label = "ml"
    elif unit == "percent":
        # percent = g/100ml = mg/0.1ml → strength% = strength * 10 mg/ml
        amount = required_mg / (strength * 10)
        unit_label = "ml"
    elif unit == "iu/ml":
        amount = required_mg / strength  # required_mg は実際にはIU
        unit_label = "ml"
    elif unit == "mg/vial":
        amount = required_mg / strength
        unit_label = "バイアル"
    elif unit == "mg/pump":
        amount = required_mg / strength
        unit_label = "プッシュ"
    elif unit == "mg/pipette":
        # ピペットは体重帯マッチング — 単純除算ではない
        amount = required_mg / strength
        unit_label = "本"
    else:
        raise ValueError(f"未対応の strength_unit: '{unit}'")

    amount = round(amount, 3)

    # 分割可能な製剤の場合、min_divisionで丸め
    rounded = None
    if divisible and min_division and min_division > 0:
        rounded = round_to_division(amount, min_division)

    return ProductAmount(
        brand=brand,
        strength=strength,
        strength_unit=unit,
        amount=amount,
        unit_label=unit_label,
        rounded_amount=rounded,
    )
