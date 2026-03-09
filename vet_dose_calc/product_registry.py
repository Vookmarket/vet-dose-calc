"""商品マスタCRUD — products.yaml の読み書き"""

import os
from pathlib import Path
from typing import Optional

import yaml

VALID_STRENGTH_UNITS = {
    "mg/tab", "mg/cap", "mg/packet", "mg/ml", "percent",
    "iu/ml", "mcg/tab", "mg/vial", "mg/pipette", "mg/pump",
}

VALID_FORMS = {
    "tablet", "capsule", "liquid", "injection", "topical",
    "patch", "gel", "spot_on", "powder",
}


def _default_path() -> Path:
    return Path(__file__).parent / "data" / "products.yaml"


def load_products(path: Optional[Path] = None) -> list[dict]:
    p = path or _default_path()
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("products", [])


def save_products(products: list[dict], path: Optional[Path] = None) -> None:
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(
            {"products": products},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def find_products_for_drug(drug_name: str, products: Optional[list[dict]] = None, path: Optional[Path] = None) -> list[dict]:
    """指定薬剤に紐づく商品一覧を返す"""
    if products is None:
        products = load_products(path)
    query = drug_name.lower()
    return [p for p in products if p.get("drug", "").lower() == query]


def add_product(product: dict, path: Optional[Path] = None) -> None:
    unit = product.get("strength_unit", "")
    if unit not in VALID_STRENGTH_UNITS:
        raise ValueError(f"無効な strength_unit: '{unit}'. 有効値: {sorted(VALID_STRENGTH_UNITS)}")
    form = product.get("form", "")
    if form not in VALID_FORMS:
        raise ValueError(f"無効な form: '{form}'. 有効値: {sorted(VALID_FORMS)}")

    products = load_products(path)
    # 同一ブランド名の重複チェック
    brand = product.get("brand", "").lower()
    for p in products:
        if p.get("brand", "").lower() == brand:
            raise ValueError(f"商品 '{product['brand']}' は既に登録されています")
    products.append(product)
    save_products(products, path)


def list_products(path: Optional[Path] = None) -> list[dict]:
    return load_products(path)
