"""テスト — registration_flow (mock input/DB)"""

import sys
import shutil
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from vet_dose_calc.suggest_engine import (
    SuggestResult, Suggestion, SuggestProduct, SuggestReference,
)
from vet_dose_calc.registration_flow import run_registration, _guess_form
from vet_dose_calc.drug_registry import load_drugs, find_drug
from vet_dose_calc.product_registry import load_products


import vet_dose_calc
PKG_DIR = Path(vet_dose_calc.__file__).parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def setup_data():
    """テスト用 drugs.yaml / products.yaml をコピー"""
    data_dir = PKG_DIR / "data"
    drugs_bak = None
    products_bak = None
    if (data_dir / "drugs.yaml").exists():
        drugs_bak = (data_dir / "drugs.yaml").read_text(encoding="utf-8")
    if (data_dir / "products.yaml").exists():
        products_bak = (data_dir / "products.yaml").read_text(encoding="utf-8")

    shutil.copy(FIXTURES / "drugs.yaml", data_dir / "drugs.yaml")
    shutil.copy(FIXTURES / "products.yaml", data_dir / "products.yaml")

    yield

    if drugs_bak is not None:
        (data_dir / "drugs.yaml").write_text(drugs_bak, encoding="utf-8")
    else:
        (data_dir / "drugs.yaml").unlink(missing_ok=True)
    if products_bak is not None:
        (data_dir / "products.yaml").write_text(products_bak, encoding="utf-8")
    else:
        (data_dir / "products.yaml").unlink(missing_ok=True)


def _make_suggestion(name_ja="テスト薬", name_en="test_drug", **kwargs):
    defaults = {
        "drug_name_ja": name_ja,
        "drug_name_en": name_en,
        "category": "test",
        "indication": "テスト適応",
        "species": "dog",
        "dose_mg_per_kg": "5",
        "frequency": "BID",
        "route": "PO",
        "duration": "7日",
        "products": [],
        "warnings": [],
        "references": [],
        "confidence": "high",
    }
    defaults.update(kwargs)
    return Suggestion(**defaults)


def _make_result(suggestions=None, grounding_urls=None):
    return SuggestResult(
        suggestions=suggestions or [],
        grounding_urls=grounding_urls or [],
    )


class TestRegistrationDrug:
    @patch("builtins.input")
    def test_register_drug(self, mock_input):
        """候補選択→y → drugsに追加"""
        s = _make_suggestion()
        result = _make_result([s])
        # 選択: "1" → 確認: "y"
        mock_input.side_effect = ["1", "y"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 1
        drug = find_drug("テスト薬")
        assert drug is not None
        assert drug["source"] == "suggested_approved"

    @patch("builtins.input")
    def test_register_drug_with_products(self, mock_input):
        """候補選択→y→商品all → drugs+productsに追加"""
        s = _make_suggestion(
            products=[
                SuggestProduct(brand="テスト錠50", strength=50, strength_unit="mg/tab"),
                SuggestProduct(brand="テスト注10", strength=10, strength_unit="mg/ml"),
            ]
        )
        result = _make_result([s])
        # 選択: "1" → 確認: "y" → 商品選択: "all"
        mock_input.side_effect = ["1", "y", "all"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 1
        assert reg["products_added"] == 2
        products = load_products()
        brands = [p["brand"] for p in products]
        assert "テスト錠50" in brands
        assert "テスト注10" in brands

    @patch("builtins.input")
    def test_register_with_edit(self, mock_input):
        """候補選択→edit→修正→y"""
        s = _make_suggestion()
        result = _make_result([s])
        # 選択: "1" → 確認: "edit"
        # エイリアス, 用量, 頻度, 投与経路, 投与期間
        mock_input.side_effect = ["1", "edit", "custom_alias", "10", "SID", "IV", "14日"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 1
        drug = find_drug("テスト薬")
        assert drug is not None
        assert "custom_alias" in drug["aliases"]
        ind = drug["species_data"]["dog"]["indications"][0]
        assert ind["dose_mg_per_kg"] == "10"
        assert ind["frequency"] == "SID"

    @patch("builtins.input")
    def test_reject_all(self, mock_input):
        """none選択 → DB変更なし"""
        s = _make_suggestion()
        result = _make_result([s])
        mock_input.side_effect = ["none"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 0
        assert reg["products_added"] == 0
        assert find_drug("テスト薬") is None

    @patch("builtins.input")
    def test_skip_existing_drug(self, mock_input):
        """既存薬剤名で登録→スキップ"""
        s = _make_suggestion(name_ja="アモキシシリン/クラブラン酸", name_en="amoxicillin")
        result = _make_result([s])
        mock_input.side_effect = ["1", "y"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 0  # 既存なのでスキップ
        assert "アモキシシリン/クラブラン酸" in reg["skipped"]

    @patch("builtins.input")
    def test_register_all(self, mock_input):
        """all選択 → 全候補登録"""
        s1 = _make_suggestion(name_ja="薬A", name_en="drug_a")
        s2 = _make_suggestion(name_ja="薬B", name_en="drug_b")
        result = _make_result([s1, s2])
        # all → 各薬剤にy
        mock_input.side_effect = ["all", "y", "y"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 2


class TestGuessForm:
    def test_tablet(self):
        assert _guess_form("mg/tab") == "tablet"

    def test_liquid(self):
        assert _guess_form("mg/ml") == "liquid"

    def test_injection(self):
        assert _guess_form("iu/ml") == "injection"

    def test_spot_on(self):
        assert _guess_form("mg/pipette") == "spot_on"

    def test_unknown(self):
        assert _guess_form("unknown") == "tablet"
