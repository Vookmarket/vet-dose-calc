#!/usr/bin/env python3
"""dose-calc — 薬用量クイック計算ツール v2

CLI エントリポイント。二層アーキテクチャ:
- calc: ルールベース層（登録済みDBから即時計算）
- suggest: LLM拡張層（Gemini API+Search Groundingで薬剤提案→DB登録）
- drug / product: マスタ管理
"""

import argparse
import sys
from pathlib import Path

from .input_parser import parse_calc_args
from .dosage_calc import calculate_dose, calculate_product_amount
from .drug_registry import load_drugs, add_drug, list_drugs, import_drugs, find_drug
from .product_registry import (
    load_products, add_product, list_products, find_products_for_drug,
    VALID_STRENGTH_UNITS, VALID_FORMS,
)
from .output_formatter import (
    format_calc_result, format_drug_list, format_product_list, format_drug_detail,
    format_suggest_result,
)
from .suggest_engine import suggest
from .registration_flow import run_registration


def cmd_calc(args):
    """用量計算"""
    try:
        species, weight, drug = parse_calc_args(args.species, args.weight, args.drug_name)
    except ValueError as e:
        print(str(e))
        return 1

    # 猫禁忌チェック（適応症の有無に関わらず先に表示）
    safety_flags = drug.get("safety_flags", {})
    if safety_flags.get("cat_contraindicated") and species == "cat":
        print(f"🚫 薬剤 '{drug['name']}' は猫に禁忌として登録されています。")
        print("使用しないでください。")
        return 0

    sp_data = drug.get("species_data", {}).get(species)
    if not sp_data:
        print(f"薬剤 '{drug['name']}' に {species} のデータがありません。")
        return 1

    indications = sp_data.get("indications", [])
    if not indications:
        print(f"薬剤 '{drug['name']}' ({species}) に適応症データがありません。")
        return 1

    # 全適応症について計算
    dose_results = []
    product_amounts_list = []

    products = find_products_for_drug(drug["name"])

    for ind in indications:
        dr = calculate_dose(
            weight_kg=weight,
            dose_mg_per_kg=str(ind.get("dose_mg_per_kg", "0")),
            indication=ind.get("indication", ""),
            frequency=ind.get("frequency", ""),
            route=ind.get("route", ""),
            duration=ind.get("duration", ""),
            notes=ind.get("notes", ""),
        )
        dose_results.append(dr)

        # 商品別投与量（最小用量ベース）
        pa_list = []
        for p in products:
            try:
                pa = calculate_product_amount(dr.dose_min_mg, p)
                pa_list.append(pa)
            except (ValueError, ZeroDivisionError):
                pass
        product_amounts_list.append(pa_list)

    output = format_calc_result(
        drug_name=drug["name"],
        species=species,
        weight_kg=weight,
        dose_results=dose_results,
        product_amounts=product_amounts_list,
        safety_flags=drug.get("safety_flags", {}),
    )
    print(output)
    return 0


def cmd_suggest(args):
    """LLM薬剤提案"""
    species = args.species.lower()
    if species not in ("dog", "cat"):
        print("動物種は dog/cat を指定してください。")
        return 1

    symptoms = args.symptoms
    weight = getattr(args, "weight", None)

    print(f"🔍 {species} / 症状: {', '.join(symptoms)} で検索中...")
    print("（Gemini API + Google Search で情報収集中。最大5分かかります）")

    try:
        result = suggest(species, symptoms, weight_kg=weight)
    except RuntimeError as e:
        print(f"\n❌ オンライン検索が利用できません: {e}")
        print("drug add で手動登録してください。")
        return 1
    except ValueError as e:
        print(str(e))
        return 1

    output = format_suggest_result(
        species=species,
        symptoms=symptoms,
        weight_kg=weight,
        suggestions=result.suggestions,
        grounding_urls=result.grounding_urls,
    )
    print(output)

    if not result.suggestions:
        return 0

    # DB登録フロー
    reg = run_registration(result)
    if reg["drugs_added"] > 0:
        print(f"\n📋 登録結果: 薬剤 {reg['drugs_added']}件、商品 {reg['products_added']}件")
    return 0


def cmd_drug_list(args):
    drugs = list_drugs()
    print(format_drug_list(drugs))
    return 0


def cmd_drug_show(args):
    drug = find_drug(args.name)
    if not drug:
        print(f"薬剤 '{args.name}' は未登録です。")
        return 1
    print(format_drug_detail(drug))
    return 0


def cmd_drug_add(args):
    """対話式で薬剤追加"""
    print("━━━ 薬剤追加 ━━━")
    name = input("薬剤名: ").strip()
    if not name:
        print("薬剤名は必須です。")
        return 1

    aliases_str = input("別名 (カンマ区切り, 空欄可): ").strip()
    aliases = [a.strip() for a in aliases_str.split(",") if a.strip()] if aliases_str else []

    category = input("カテゴリ (例: antibiotics): ").strip()

    drug = {
        "name": name,
        "aliases": aliases,
        "category": category,
        "source": "user_registered",
        "species_data": {},
        "safety_flags": {
            "cat_contraindicated": False,
            "narrow_therapeutic_index": False,
        },
        "references": [],
    }

    for sp, label in [("dog", "犬"), ("cat", "猫")]:
        add_sp = input(f"{label}のデータを追加しますか？ [y/n]: ").strip().lower()
        if add_sp != "y":
            continue
        indications = []
        while True:
            ind_name = input(f"  適応症 (空欄で終了): ").strip()
            if not ind_name:
                break
            dose = input(f"  用量 mg/kg (例: 12.5-25): ").strip()
            freq = input(f"  頻度 (例: BID): ").strip()
            route = input(f"  投与経路 (例: PO): ").strip()
            duration = input(f"  投与期間 (例: 7-14日): ").strip()
            indications.append({
                "indication": ind_name,
                "dose_mg_per_kg": dose,
                "frequency": freq,
                "route": route,
                "duration": duration,
                "notes": "",
            })
        drug["species_data"][sp] = {"indications": indications, "warnings": []}

    try:
        add_drug(drug)
        print(f"✅ 薬剤 '{name}' を登録しました。")
        return 0
    except ValueError as e:
        print(f"エラー: {e}")
        return 1


def cmd_drug_import(args):
    try:
        count = import_drugs(Path(args.file))
        print(f"✅ {count}件の薬剤をインポートしました。")
        return 0
    except Exception as e:
        print(f"エラー: {e}")
        return 1


def cmd_product_list(args):
    products = list_products()
    print(format_product_list(products))
    return 0


def cmd_product_add(args):
    """対話式で商品追加"""
    print("━━━ 商品追加 ━━━")
    brand = input("商品名: ").strip()
    drug = input("薬剤名 (マスタ登録済み): ").strip()
    strength = input("含有量 (数値): ").strip()
    print(f"含有量単位の選択: {sorted(VALID_STRENGTH_UNITS)}")
    unit = input("含有量単位: ").strip()
    print(f"剤形の選択: {sorted(VALID_FORMS)}")
    form = input("剤形: ").strip()
    divisible = input("分割可能？ [y/n]: ").strip().lower() == "y"
    min_div = None
    if divisible:
        min_div_str = input("最小分割単位 (例: 0.5): ").strip()
        min_div = float(min_div_str) if min_div_str else None

    product = {
        "brand": brand,
        "drug": drug,
        "strength": float(strength),
        "strength_unit": unit,
        "form": form,
        "divisible": divisible,
        "min_division": min_div,
        "source": "user_registered",
        "notes": "",
    }

    try:
        add_product(product)
        print(f"✅ 商品 '{brand}' を登録しました。")
        return 0
    except ValueError as e:
        print(f"エラー: {e}")
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="dose-calc",
        description="薬用量クイック計算ツール v2",
    )
    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # suggest
    p_suggest = subparsers.add_parser("suggest", help="薬剤提案（AI検索）")
    p_suggest.add_argument("species", help="動物種 (dog/cat)")
    p_suggest.add_argument("symptoms", nargs="+", help="症状キーワード")
    p_suggest.add_argument("--weight", type=float, default=None, help="体重 (kg)")

    # calc
    p_calc = subparsers.add_parser("calc", help="用量計算")
    p_calc.add_argument("species", help="動物種 (dog/cat)")
    p_calc.add_argument("weight", type=float, help="体重 (kg)")
    p_calc.add_argument("drug_name", help="薬剤名")

    # drug
    p_drug = subparsers.add_parser("drug", help="薬剤マスタ管理")
    drug_sub = p_drug.add_subparsers(dest="drug_cmd")
    drug_sub.add_parser("list", help="一覧表示")
    p_show = drug_sub.add_parser("show", help="詳細表示")
    p_show.add_argument("name", help="薬剤名")
    drug_sub.add_parser("add", help="薬剤追加")
    p_import = drug_sub.add_parser("import", help="テンプレートインポート")
    p_import.add_argument("file", help="YAMLファイルパス")

    # product
    p_product = subparsers.add_parser("product", help="商品マスタ管理")
    prod_sub = p_product.add_subparsers(dest="product_cmd")
    prod_sub.add_parser("list", help="一覧表示")
    prod_sub.add_parser("add", help="商品追加")

    args = parser.parse_args()

    if args.command == "suggest":
        sys.exit(cmd_suggest(args))
    elif args.command == "calc":
        sys.exit(cmd_calc(args))
    elif args.command == "drug":
        if args.drug_cmd == "list":
            sys.exit(cmd_drug_list(args))
        elif args.drug_cmd == "show":
            sys.exit(cmd_drug_show(args))
        elif args.drug_cmd == "add":
            sys.exit(cmd_drug_add(args))
        elif args.drug_cmd == "import":
            sys.exit(cmd_drug_import(args))
        else:
            p_drug.print_help()
    elif args.command == "product":
        if args.product_cmd == "list":
            sys.exit(cmd_product_list(args))
        elif args.product_cmd == "add":
            sys.exit(cmd_product_add(args))
        else:
            p_product.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
