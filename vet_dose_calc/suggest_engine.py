"""suggest_engine — LLM薬剤提案エンジン

動物種+症状からGemini API（Search Grounding）で薬剤候補を取得し、
構造化された提案リストを返す。
"""

from dataclasses import dataclass, field

from .llm_client import call_gemini, extract_json, load_prompt, LLMResponse


SPECIES_JA = {"dog": "犬", "cat": "猫"}


@dataclass
class SuggestProduct:
    brand: str
    strength: float
    strength_unit: str


@dataclass
class SuggestReference:
    title: str
    url: str


@dataclass
class Suggestion:
    drug_name_ja: str
    drug_name_en: str
    category: str
    indication: str
    species: str
    dose_mg_per_kg: str
    frequency: str
    route: str
    duration: str
    products: list[SuggestProduct] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    references: list[SuggestReference] = field(default_factory=list)
    confidence: str = "medium"


@dataclass
class SuggestResult:
    suggestions: list[Suggestion]
    grounding_urls: list[dict]  # [{uri, title}, ...] from Search Grounding
    raw_text: str = ""


def suggest(
    species: str,
    symptoms: list[str],
    weight_kg: float | None = None,
) -> SuggestResult:
    """症状から薬剤候補を提案

    Args:
        species: 動物種 (dog/cat)
        symptoms: 症状キーワードのリスト
        weight_kg: 体重kg（任意）

    Returns:
        SuggestResult

    Raises:
        ValueError: 入力バリデーション失敗
        RuntimeError: API障害
    """
    if species not in SPECIES_JA:
        raise ValueError(f"動物種は {', '.join(SPECIES_JA.keys())} のいずれかを指定してください。")
    if not symptoms:
        raise ValueError("症状を1つ以上指定してください。")

    species_ja = SPECIES_JA[species]
    symptoms_str = ", ".join(symptoms)
    weight_line = f"- 体重: {weight_kg} kg" if weight_kg else ""

    prompt = load_prompt(
        "suggest",
        species=species,
        species_ja=species_ja,
        symptoms=symptoms_str,
        weight_line=weight_line,
    )

    llm_resp = call_gemini(prompt, use_search=True, timeout_sec=300)

    suggestions = _parse_suggestions(llm_resp)

    # Search Grounding URLをマージ
    grounding_urls = llm_resp.grounding_chunks

    return SuggestResult(
        suggestions=suggestions,
        grounding_urls=grounding_urls,
        raw_text=llm_resp.text,
    )


def _parse_suggestions(llm_resp: LLMResponse) -> list[Suggestion]:
    """LLM応答をパースしてSuggestionリストに変換"""
    data = extract_json(llm_resp.text)
    if not data:
        return []

    raw_suggestions = []
    if isinstance(data, dict):
        raw_suggestions = data.get("suggestions", [])
    elif isinstance(data, list):
        raw_suggestions = data

    results = []
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        try:
            s = _item_to_suggestion(item)
            results.append(s)
        except (KeyError, TypeError, ValueError):
            continue

    return results


def _item_to_suggestion(item: dict) -> Suggestion:
    """辞書を Suggestion に変換"""
    products = []
    for p in item.get("products", []):
        if isinstance(p, dict) and p.get("brand"):
            try:
                strength = float(p.get("strength", 0))
            except (ValueError, TypeError):
                strength = 0
            products.append(SuggestProduct(
                brand=str(p["brand"]),
                strength=strength,
                strength_unit=str(p.get("strength_unit", "")),
            ))

    references = []
    for r in item.get("references", []):
        if isinstance(r, dict) and r.get("title"):
            references.append(SuggestReference(
                title=str(r["title"]),
                url=str(r.get("url", "")),
            ))

    return Suggestion(
        drug_name_ja=str(item.get("drug_name_ja", "")),
        drug_name_en=str(item.get("drug_name_en", "")),
        category=str(item.get("category", "")),
        indication=str(item.get("indication", "")),
        species=str(item.get("species", "")),
        dose_mg_per_kg=str(item.get("dose_mg_per_kg", "")),
        frequency=str(item.get("frequency", "")),
        route=str(item.get("route", "")),
        duration=str(item.get("duration", "")),
        products=products,
        warnings=list(item.get("warnings", [])),
        references=references,
        confidence=str(item.get("confidence", "medium")),
    )
