"""統合テスト — suggest CLI + suggest→登録→calc E2Eフロー"""

import sys
import json
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import pytest
from vet_dose_calc.llm_client import LLMResponse
from vet_dose_calc.drug_registry import find_drug, load_drugs
from vet_dose_calc.product_registry import load_products, find_products_for_drug

import vet_dose_calc
PKG_DIR = Path(vet_dose_calc.__file__).parent
FIXTURES = Path(__file__).parent / "fixtures"

# --- Mock LLM応答 ---

MOCK_SUGGEST_RESPONSE = json.dumps({
    "suggestions": [
        {
            "drug_name_ja": "マロピタント",
            "drug_name_en": "maropitant",
            "category": "antiemetic",
            "indication": "急性嘔吐",
            "species": "dog",
            "dose_mg_per_kg": "1",
            "frequency": "SID",
            "route": "SC",
            "duration": "最大5日間",
            "products": [
                {"brand": "セレニア錠 16mg", "strength": 16, "strength_unit": "mg/tab"},
            ],
            "warnings": ["SC投与時の疼痛に注意"],
            "references": [
                {"title": "Merck Vet Manual", "url": "https://www.merckvetmanual.com/antiemetics"}
            ],
            "confidence": "high",
        },
        {
            "drug_name_ja": "メトクロプラミド",
            "drug_name_en": "metoclopramide",
            "category": "antiemetic",
            "indication": "嘔吐・消化管運動促進",
            "species": "dog",
            "dose_mg_per_kg": "0.2-0.5",
            "frequency": "TID",
            "route": "PO",
            "duration": "3-5日",
            "products": [
                {"brand": "プリンペラン錠5", "strength": 5, "strength_unit": "mg/tab"},
            ],
            "warnings": ["錐体外路症状に注意"],
            "references": [],
            "confidence": "medium",
        },
    ]
}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def setup_data():
    """テスト用データをセットアップ・復元"""
    data_dir = PKG_DIR / "data"
    drugs_bak = None
    products_bak = None
    if (data_dir / "drugs.yaml").exists():
        drugs_bak = (data_dir / "drugs.yaml").read_text()
    if (data_dir / "products.yaml").exists():
        products_bak = (data_dir / "products.yaml").read_text()

    shutil.copy(FIXTURES / "drugs.yaml", data_dir / "drugs.yaml")
    shutil.copy(FIXTURES / "products.yaml", data_dir / "products.yaml")

    yield

    if drugs_bak is not None:
        (data_dir / "drugs.yaml").write_text(drugs_bak)
    else:
        (data_dir / "drugs.yaml").unlink(missing_ok=True)
    if products_bak is not None:
        (data_dir / "products.yaml").write_text(products_bak)
    else:
        (data_dir / "products.yaml").unlink(missing_ok=True)


# --- suggest CLI統合テスト ---

class TestSuggestCLI:
    """cmd_suggest を直接呼び出す統合テスト"""

    @patch("vet_dose_calc.tool.suggest")
    def test_suggest_basic(self, mock_suggest, capsys):
        """suggest dog 嘔吐 → 候補リスト表示"""
        from vet_dose_calc.suggest_engine import SuggestResult, Suggestion, SuggestProduct, SuggestReference
        from vet_dose_calc.tool import cmd_suggest

        mock_suggest.return_value = SuggestResult(
            suggestions=[
                Suggestion(
                    drug_name_ja="マロピタント",
                    drug_name_en="maropitant",
                    category="antiemetic",
                    indication="急性嘔吐",
                    species="dog",
                    dose_mg_per_kg="1",
                    frequency="SID",
                    route="SC",
                    duration="最大5日間",
                    products=[SuggestProduct("セレニア錠 16mg", 16, "mg/tab")],
                    warnings=["SC投与時の疼痛に注意"],
                    references=[SuggestReference("Merck", "https://example.com")],
                    confidence="high",
                ),
            ],
            grounding_urls=[{"uri": "https://example.com/grounding", "title": "Grounding"}],
        )

        args = SimpleNamespace(species="dog", symptoms=["嘔吐"], weight=5.0)

        with patch("vet_dose_calc.tool.run_registration", return_value={"drugs_added": 0, "products_added": 0, "skipped": []}):
            result = cmd_suggest(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "マロピタント" in out
        assert "maropitant" in out
        assert "AI提案" in out
        assert "1 mg/kg" in out

    @patch("vet_dose_calc.tool.suggest")
    def test_suggest_with_weight_calc(self, mock_suggest, capsys):
        """suggest dog 嘔吐 --weight 5 → 個体用量表示"""
        from vet_dose_calc.suggest_engine import SuggestResult, Suggestion
        from vet_dose_calc.tool import cmd_suggest

        mock_suggest.return_value = SuggestResult(
            suggestions=[
                Suggestion(
                    drug_name_ja="マロピタント",
                    drug_name_en="maropitant",
                    category="antiemetic",
                    indication="急性嘔吐",
                    species="dog",
                    dose_mg_per_kg="1",
                    frequency="SID",
                    route="SC",
                    duration="最大5日間",
                    confidence="high",
                ),
            ],
            grounding_urls=[],
        )

        args = SimpleNamespace(species="dog", symptoms=["嘔吐"], weight=5.0)

        with patch("vet_dose_calc.tool.run_registration", return_value={"drugs_added": 0, "products_added": 0, "skipped": []}):
            result = cmd_suggest(args)

        out = capsys.readouterr().out
        assert "5 mg" in out  # 1mg/kg * 5kg = 5mg

    @patch("vet_dose_calc.tool.suggest")
    def test_suggest_api_failure(self, mock_suggest, capsys):
        """API障害時 → フォールバックメッセージ"""
        from vet_dose_calc.tool import cmd_suggest

        mock_suggest.side_effect = RuntimeError("API key not set")
        args = SimpleNamespace(species="dog", symptoms=["嘔吐"], weight=None)
        result = cmd_suggest(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "オンライン検索が利用できません" in out
        assert "drug add" in out

    def test_suggest_invalid_species(self, capsys):
        """不正な動物種 → エラー"""
        from vet_dose_calc.tool import cmd_suggest

        args = SimpleNamespace(species="horse", symptoms=["嘔吐"], weight=None)
        result = cmd_suggest(args)

        assert result == 1
        out = capsys.readouterr().out
        assert "dog/cat" in out

    @patch("vet_dose_calc.tool.suggest")
    def test_suggest_no_results(self, mock_suggest, capsys):
        """候補0件 → 空メッセージ"""
        from vet_dose_calc.suggest_engine import SuggestResult
        from vet_dose_calc.tool import cmd_suggest

        mock_suggest.return_value = SuggestResult(
            suggestions=[], grounding_urls=[]
        )
        args = SimpleNamespace(species="dog", symptoms=["嘔吐"], weight=None)
        result = cmd_suggest(args)

        assert result == 0
        out = capsys.readouterr().out
        assert "候補が見つかりませんでした" in out


# --- E2Eフローテスト: suggest → 登録 → calc ---

class TestE2EFlow:
    """suggest結果をDB登録 → calcで確認するフルフロー"""

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    @patch("builtins.input")
    def test_suggest_register_then_calc(self, mock_input, mock_gemini, capsys):
        """suggest → 候補1を登録 → calc で計算確認"""
        from vet_dose_calc.suggest_engine import suggest as real_suggest
        from vet_dose_calc.registration_flow import run_registration
        from vet_dose_calc.tool import cmd_calc

        # Step 1: suggest
        mock_gemini.return_value = LLMResponse(
            text=MOCK_SUGGEST_RESPONSE,
            grounding_chunks=[{"uri": "https://example.com/ref", "title": "Reference"}],
        )
        result = real_suggest("dog", ["嘔吐"], weight_kg=5.0)
        assert len(result.suggestions) == 2
        assert result.suggestions[0].drug_name_ja == "マロピタント"

        capsys.readouterr()  # clear buffer

        # Step 2: 登録（候補1のみ、商品も）
        mock_input.side_effect = ["1", "y", "all"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 1
        assert reg["products_added"] == 1

        # Step 3: DB確認
        drug = find_drug("マロピタント")
        assert drug is not None
        assert drug["source"] == "suggested_approved"
        assert drug["species_data"]["dog"]["indications"][0]["dose_mg_per_kg"] == "1"

        products = find_products_for_drug("マロピタント")
        assert len(products) == 1
        assert products[0]["brand"] == "セレニア錠 16mg"

        capsys.readouterr()  # clear buffer

        # Step 4: calc で計算
        args = SimpleNamespace(species="dog", weight=5.0, drug_name="マロピタント")
        result = cmd_calc(args)
        assert result == 0

        out = capsys.readouterr().out
        assert "マロピタント" in out
        assert "5 mg" in out  # 1mg/kg * 5kg
        assert "セレニア錠" in out
        assert "登録データに基づく計算結果" in out

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    @patch("builtins.input")
    def test_suggest_register_with_edit_then_calc(self, mock_input, mock_gemini, capsys):
        """suggest → edit修正 → calc で修正値が反映"""
        from vet_dose_calc.suggest_engine import suggest as real_suggest
        from vet_dose_calc.registration_flow import run_registration
        from vet_dose_calc.tool import cmd_calc

        mock_gemini.return_value = LLMResponse(
            text=MOCK_SUGGEST_RESPONSE,
            grounding_chunks=[],
        )
        result = real_suggest("dog", ["嘔吐"])

        capsys.readouterr()

        # 登録（候補1、editで用量を2に変更、商品none）
        mock_input.side_effect = [
            "1", "edit",
            "",     # aliases (default)
            "2",    # dose → 2mg/kg
            "",     # frequency (default)
            "",     # route (default)
            "",     # duration (default)
            "none", # 商品は登録しない
        ]
        reg = run_registration(result)
        assert reg["drugs_added"] == 1
        assert reg["products_added"] == 0

        drug = find_drug("マロピタント")
        assert drug["species_data"]["dog"]["indications"][0]["dose_mg_per_kg"] == "2"

        capsys.readouterr()

        # calc
        args = SimpleNamespace(species="dog", weight=5.0, drug_name="マロピタント")
        cmd_calc(args)
        out = capsys.readouterr().out
        assert "10 mg" in out  # 2mg/kg * 5kg = 10mg

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    @patch("builtins.input")
    def test_suggest_reject_no_db_change(self, mock_input, mock_gemini, capsys):
        """suggest → none → DB変更なし"""
        from vet_dose_calc.suggest_engine import suggest as real_suggest
        from vet_dose_calc.registration_flow import run_registration

        mock_gemini.return_value = LLMResponse(
            text=MOCK_SUGGEST_RESPONSE,
            grounding_chunks=[],
        )
        result = real_suggest("dog", ["嘔吐"])

        drugs_before = load_drugs()
        products_before = load_products()

        mock_input.side_effect = ["none"]
        reg = run_registration(result)
        assert reg["drugs_added"] == 0

        # DB変更なし
        assert len(load_drugs()) == len(drugs_before)
        assert len(load_products()) == len(products_before)


# --- output_formatter テスト ---

class TestFormatSuggestResult:
    def test_format_with_suggestions(self):
        from vet_dose_calc.output_formatter import format_suggest_result
        from vet_dose_calc.suggest_engine import Suggestion, SuggestProduct, SuggestReference

        suggestions = [
            Suggestion(
                drug_name_ja="テスト薬",
                drug_name_en="test_drug",
                category="test",
                indication="テスト",
                species="dog",
                dose_mg_per_kg="5",
                frequency="BID",
                route="PO",
                duration="7日",
                products=[SuggestProduct("テスト錠", 50, "mg/tab")],
                warnings=["注意事項"],
                references=[SuggestReference("参考", "https://example.com")],
                confidence="high",
            ),
        ]
        out = format_suggest_result("dog", ["嘔吐"], 5.0, suggestions, [])
        assert "テスト薬" in out
        assert "test_drug" in out
        assert "25 mg" in out  # 5mg/kg * 5kg
        assert "AI提案" in out
        assert "テスト錠" in out

    def test_format_empty(self):
        from vet_dose_calc.output_formatter import format_suggest_result
        out = format_suggest_result("dog", ["嘔吐"], None, [], [])
        assert "候補が見つかりませんでした" in out
        assert "AI提案" in out

    def test_format_with_grounding(self):
        from vet_dose_calc.output_formatter import format_suggest_result
        from vet_dose_calc.suggest_engine import Suggestion
        grounding = [{"uri": "https://example.com", "title": "Source"}]
        # grounding URLsは候補がある場合のみ表示される
        suggestions = [
            Suggestion(
                drug_name_ja="テスト",
                drug_name_en="test",
                category="test",
                indication="テスト",
                species="cat",
                dose_mg_per_kg="1",
                frequency="SID",
                route="PO",
                duration="7日",
                confidence="medium",
            ),
        ]
        out = format_suggest_result("cat", ["血尿"], None, suggestions, grounding)
        assert "Google Search" in out
        assert "Source" in out
