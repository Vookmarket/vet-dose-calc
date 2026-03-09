"""テスト — suggest_engine + llm_client (mock)"""

import sys
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from vet_dose_calc.llm_client import extract_json, _sanitize_json, _parse_truncated, LLMResponse
from vet_dose_calc.suggest_engine import suggest, _parse_suggestions, Suggestion


# --- llm_client: JSONパーサーテスト ---

class TestExtractJson:
    def test_plain_json(self):
        text = '{"suggestions": [{"drug_name_ja": "テスト"}]}'
        result = extract_json(text)
        assert result["suggestions"][0]["drug_name_ja"] == "テスト"

    def test_code_block(self):
        text = '```json\n{"suggestions": [{"drug_name_ja": "テスト"}]}\n```'
        result = extract_json(text)
        assert result["suggestions"][0]["drug_name_ja"] == "テスト"

    def test_trailing_comma(self):
        text = '{"suggestions": [{"drug_name_ja": "テスト",}]}'
        result = extract_json(text)
        assert result["suggestions"][0]["drug_name_ja"] == "テスト"

    def test_invalid_returns_none(self):
        result = extract_json("これはJSONではありません")
        assert result is None

    def test_truncated_json(self):
        """切り詰めJSONの部分救済"""
        text = '{"suggestions": [{"drug_name_ja": "薬A", "category": "test"}, {"drug_name_ja": "薬B", "catego'
        result = extract_json(text)
        assert result is not None
        assert len(result["suggestions"]) == 1
        assert result["suggestions"][0]["drug_name_ja"] == "薬A"


class TestSanitizeJson:
    def test_trailing_comma_array(self):
        assert _sanitize_json("[1, 2, 3,]") == "[1, 2, 3]"

    def test_trailing_comma_object(self):
        assert _sanitize_json('{"a": 1,}') == '{"a": 1}'

    def test_comment_removal(self):
        result = _sanitize_json('{"a": 1} // comment')
        assert "comment" not in result


class TestParseTruncated:
    def test_complete_items(self):
        text = '"suggestions": [{"a": 1}, {"b": 2}, {"c":'
        result = _parse_truncated(text)
        assert result is not None
        assert len(result["suggestions"]) == 2

    def test_no_suggestions(self):
        result = _parse_truncated("random text")
        assert result is None


# --- suggest_engine: パース+バリデーションテスト ---

MOCK_LLM_RESPONSE_TEXT = json.dumps({
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
                {"brand": "セレニア注 10mg/ml", "strength": 10, "strength_unit": "mg/ml"},
            ],
            "warnings": ["SC投与時の疼痛に注意"],
            "references": [
                {"title": "Merck Vet Manual", "url": "https://www.merckvetmanual.com/antiemetics"}
            ],
            "confidence": "high",
        },
        {
            "drug_name_ja": "オンダンセトロン",
            "drug_name_en": "ondansetron",
            "category": "antiemetic",
            "indication": "嘔吐",
            "species": "dog",
            "dose_mg_per_kg": "0.1-0.2",
            "frequency": "BID",
            "route": "PO",
            "duration": "3-5日",
            "products": [],
            "warnings": [],
            "references": [],
            "confidence": "medium",
        },
    ]
}, ensure_ascii=False)


class TestSuggestEngine:
    @patch("vet_dose_calc.suggest_engine.call_gemini")
    def test_basic_suggest(self, mock_gemini):
        mock_gemini.return_value = LLMResponse(
            text=MOCK_LLM_RESPONSE_TEXT,
            grounding_chunks=[
                {"uri": "https://example.com/vet", "title": "Vet Reference"}
            ],
        )
        result = suggest("dog", ["嘔吐"])
        assert len(result.suggestions) == 2
        assert result.suggestions[0].drug_name_ja == "マロピタント"
        assert result.suggestions[0].dose_mg_per_kg == "1"
        assert len(result.suggestions[0].products) == 2
        assert len(result.grounding_urls) == 1

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    def test_suggest_with_weight(self, mock_gemini):
        mock_gemini.return_value = LLMResponse(
            text=MOCK_LLM_RESPONSE_TEXT,
            grounding_chunks=[],
        )
        result = suggest("dog", ["嘔吐", "食欲不振"], weight_kg=5.0)
        assert len(result.suggestions) == 2
        # プロンプトに体重が含まれるか確認
        call_args = mock_gemini.call_args
        prompt = call_args[0][0]
        assert "5.0 kg" in prompt

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    def test_suggest_empty_response(self, mock_gemini):
        mock_gemini.return_value = LLMResponse(text="", grounding_chunks=[])
        result = suggest("dog", ["嘔吐"])
        assert len(result.suggestions) == 0

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    def test_suggest_api_failure(self, mock_gemini):
        mock_gemini.side_effect = RuntimeError("API error")
        with pytest.raises(RuntimeError, match="API error"):
            suggest("dog", ["嘔吐"])

    @patch("vet_dose_calc.suggest_engine.call_gemini")
    def test_suggest_malformed_json(self, mock_gemini):
        mock_gemini.return_value = LLMResponse(
            text="これはJSONではありません。薬剤候補はありません。",
            grounding_chunks=[],
        )
        result = suggest("dog", ["嘔吐"])
        assert len(result.suggestions) == 0

    def test_invalid_species(self):
        with pytest.raises(ValueError, match="動物種"):
            suggest("horse", ["嘔吐"])

    def test_empty_symptoms(self):
        with pytest.raises(ValueError, match="症状"):
            suggest("dog", [])


class TestParseSuggestions:
    def test_parse_normal(self):
        resp = LLMResponse(text=MOCK_LLM_RESPONSE_TEXT, grounding_chunks=[])
        results = _parse_suggestions(resp)
        assert len(results) == 2
        assert isinstance(results[0], Suggestion)
        assert results[0].drug_name_ja == "マロピタント"
        assert results[0].products[0].brand == "セレニア錠 16mg"
        assert results[0].references[0].url == "https://www.merckvetmanual.com/antiemetics"

    def test_parse_partial_data(self):
        """必須フィールドが欠けていても最低限パースできる"""
        text = json.dumps({"suggestions": [
            {"drug_name_ja": "テスト薬", "dose_mg_per_kg": "1"},
        ]})
        resp = LLMResponse(text=text, grounding_chunks=[])
        results = _parse_suggestions(resp)
        assert len(results) == 1
        assert results[0].drug_name_ja == "テスト薬"
        assert results[0].drug_name_en == ""


# --- リダイレクトURL解決テスト ---

class TestResolveRedirectUrls:
    def test_non_redirect_unchanged(self):
        from vet_dose_calc.llm_client import _resolve_redirect_urls
        chunks = [{"uri": "https://example.com/page", "title": "Normal"}]
        result = _resolve_redirect_urls(chunks)
        assert result[0]["uri"] == "https://example.com/page"

    @patch("vet_dose_calc.llm_client.urllib.request.urlopen")
    def test_redirect_resolved(self, mock_urlopen):
        from vet_dose_calc.llm_client import _resolve_redirect_urls
        mock_resp = MagicMock()
        mock_resp.url = "https://www.realsite.com/article"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        chunks = [{"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123", "title": "Source"}]
        result = _resolve_redirect_urls(chunks)
        assert result[0]["uri"] == "https://www.realsite.com/article"
        assert result[0]["title"] == "Source"

    @patch("vet_dose_calc.llm_client.urllib.request.urlopen")
    def test_redirect_failure_fallback(self, mock_urlopen):
        """解決失敗時は元URLを維持"""
        from vet_dose_calc.llm_client import _resolve_redirect_urls
        mock_urlopen.side_effect = Exception("timeout")

        chunks = [{"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/ABC123", "title": "Source"}]
        result = _resolve_redirect_urls(chunks)
        assert "vertexaisearch" in result[0]["uri"]  # 元URLのまま

    @patch("vet_dose_calc.llm_client.urllib.request.urlopen")
    def test_mixed_urls(self, mock_urlopen):
        """リダイレクトURLと通常URLが混在"""
        from vet_dose_calc.llm_client import _resolve_redirect_urls
        mock_resp = MagicMock()
        mock_resp.url = "https://resolved.com"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        chunks = [
            {"uri": "https://example.com/normal", "title": "Normal"},
            {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/XYZ", "title": "Redirect"},
        ]
        result = _resolve_redirect_urls(chunks)
        assert result[0]["uri"] == "https://example.com/normal"
        assert result[1]["uri"] == "https://resolved.com"
