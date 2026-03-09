"""registration_flow — suggest結果からDB登録する対話フロー

suggest_engine の SuggestResult を受け取り、ユーザーとの対話で
drugs.yaml / products.yaml への登録を行う。
"""

from .suggest_engine import SuggestResult, Suggestion
from .drug_registry import add_drug, find_drug
from .product_registry import add_product, VALID_STRENGTH_UNITS


def run_registration(result: SuggestResult) -> dict:
    """suggest結果からDB登録フローを実行

    Args:
        result: SuggestResult（suggest_engine.suggest() の戻り値）

    Returns:
        {"drugs_added": int, "products_added": int, "skipped": list[str]}
    """
    if not result.suggestions:
        print("登録可能な候補がありません。")
        return {"drugs_added": 0, "products_added": 0, "skipped": []}

    # 選択
    selected = _select_candidates(result.suggestions)
    if not selected:
        return {"drugs_added": 0, "products_added": 0, "skipped": []}

    drugs_added = 0
    products_added = 0
    skipped = []

    for s in selected:
        drug_ok = _register_drug(s, result)
        if drug_ok:
            drugs_added += 1
            prod_count = _register_products(s)
            products_added += prod_count
        else:
            skipped.append(s.drug_name_ja)

    return {"drugs_added": drugs_added, "products_added": products_added, "skipped": skipped}


def _select_candidates(suggestions: list[Suggestion]) -> list[Suggestion]:
    """ユーザーに候補を選択させる"""
    print()
    print("DBに登録しますか？")
    for i, s in enumerate(suggestions):
        print(f"  [{i + 1}] {s.drug_name_ja} ({s.drug_name_en})")
    print(f"  [all] 全て / [none] 登録しない")

    choice = input("選択: ").strip().lower()

    if choice == "none" or choice == "":
        return []
    if choice == "all":
        return list(suggestions)

    selected = []
    for part in choice.replace(",", " ").split():
        try:
            idx = int(part) - 1
            if 0 <= idx < len(suggestions):
                selected.append(suggestions[idx])
        except ValueError:
            pass

    return selected


def _register_drug(s: Suggestion, result: SuggestResult) -> bool:
    """1つの薬剤をDBに登録"""
    existing = find_drug(s.drug_name_ja)
    if existing:
        print(f"  ⚠️ '{s.drug_name_ja}' は既に登録済みです。スキップします。")
        return False

    print()
    print(f"[{s.drug_name_ja}] を薬剤マスタに登録します:")
    print(f"  名前: {s.drug_name_ja}")
    print(f"  エイリアス: [{s.drug_name_en}]")
    print(f"  カテゴリ: {s.category}")
    print(f"  用量: {s.dose_mg_per_kg} mg/kg {s.frequency} {s.route}")
    print(f"  登録元: AI提案（suggest経由）")

    # 根拠URL表示
    refs = s.references
    grounding = result.grounding_urls
    if refs:
        print("  根拠:")
        for r in refs[:3]:
            print(f"    - {r.title}: {r.url}")
    elif grounding:
        print("  根拠 (Search Grounding):")
        for g in grounding[:3]:
            print(f"    - {g.get('title', '')}: {g.get('uri', '')}")

    confirm = input("確認 [y/n/edit]: ").strip().lower()
    if confirm == "n":
        return False

    # 編集
    aliases = [s.drug_name_en]
    dose = s.dose_mg_per_kg
    frequency = s.frequency
    route = s.route
    duration = s.duration

    if confirm == "edit":
        aliases_input = input(f"  エイリアス [{', '.join(aliases)}]: ").strip()
        if aliases_input:
            aliases = [a.strip() for a in aliases_input.split(",") if a.strip()]
        dose_input = input(f"  用量 mg/kg [{dose}]: ").strip()
        if dose_input:
            dose = dose_input
        freq_input = input(f"  頻度 [{frequency}]: ").strip()
        if freq_input:
            frequency = freq_input
        route_input = input(f"  投与経路 [{route}]: ").strip()
        if route_input:
            route = route_input
        dur_input = input(f"  投与期間 [{duration}]: ").strip()
        if dur_input:
            duration = dur_input

    # 根拠URLリスト
    ref_list = []
    for r in s.references:
        ref_list.append({"title": r.title, "url": r.url})
    for g in result.grounding_urls:
        if g.get("uri") and not any(r["url"] == g["uri"] for r in ref_list):
            ref_list.append({"title": g.get("title", ""), "url": g["uri"]})

    drug = {
        "name": s.drug_name_ja,
        "aliases": aliases,
        "category": s.category,
        "source": "suggested_approved",
        "species_data": {
            s.species: {
                "indications": [{
                    "indication": s.indication,
                    "dose_mg_per_kg": dose,
                    "frequency": frequency,
                    "route": route,
                    "duration": duration,
                    "notes": "",
                }],
                "warnings": list(s.warnings),
            }
        },
        "safety_flags": {
            "cat_contraindicated": False,
            "narrow_therapeutic_index": False,
        },
        "references": ref_list,
    }

    try:
        add_drug(drug)
        print(f"  ✅ 薬剤マスタに登録しました。")
        return True
    except ValueError as e:
        print(f"  ❌ 登録エラー: {e}")
        return False


def _register_products(s: Suggestion) -> int:
    """提案に含まれる商品をDBに登録"""
    if not s.products:
        return 0

    print()
    print("  商品も登録しますか？")
    for i, p in enumerate(s.products):
        print(f"    [{i + 1}] {p.brand} ({p.strength}{p.strength_unit})")
    print(f"    [all] 全て / [none] 登録しない")

    choice = input("  選択: ").strip().lower()
    if choice == "none" or choice == "":
        return 0

    if choice == "all":
        targets = list(s.products)
    else:
        targets = []
        for part in choice.replace(",", " ").split():
            try:
                idx = int(part) - 1
                if 0 <= idx < len(s.products):
                    targets.append(s.products[idx])
            except ValueError:
                pass

    count = 0
    for p in targets:
        # strength_unit バリデーション
        unit = p.strength_unit if p.strength_unit in VALID_STRENGTH_UNITS else "mg/tab"

        product = {
            "brand": p.brand,
            "drug": s.drug_name_ja,
            "strength": p.strength,
            "strength_unit": unit,
            "form": _guess_form(unit),
            "divisible": unit in ("mg/tab", "mg/cap"),
            "min_division": 0.5 if unit in ("mg/tab", "mg/cap") else None,
            "source": "suggested_approved",
            "notes": "",
        }

        try:
            add_product(product)
            print(f"    ✅ '{p.brand}' を登録しました。")
            count += 1
        except ValueError as e:
            print(f"    ❌ '{p.brand}' 登録エラー: {e}")

    return count


def _guess_form(strength_unit: str) -> str:
    """strength_unitから剤形を推測"""
    form_map = {
        "mg/tab": "tablet",
        "mg/cap": "capsule",
        "mg/packet": "powder",
        "mg/ml": "liquid",
        "percent": "liquid",
        "iu/ml": "injection",
        "mcg/tab": "tablet",
        "mg/vial": "injection",
        "mg/pipette": "spot_on",
        "mg/pump": "gel",
    }
    return form_map.get(strength_unit, "tablet")
