"""入力バリデーション、薬剤名エイリアス解決"""

from typing import Optional

from .drug_registry import find_drug, load_drugs

VALID_SPECIES = {"dog", "cat"}
WEIGHT_MIN = 0.1
WEIGHT_MAX = 200.0


def validate_species(species: str) -> str:
    s = species.lower().strip()
    if s not in VALID_SPECIES:
        raise ValueError(f"未対応の動物種: '{species}'. 対応: {sorted(VALID_SPECIES)}")
    return s


def validate_weight(weight: float) -> float:
    if weight < WEIGHT_MIN:
        raise ValueError(f"体重が小さすぎます: {weight}kg (最小: {WEIGHT_MIN}kg)")
    if weight > WEIGHT_MAX:
        raise ValueError(f"体重が大きすぎます: {weight}kg (最大: {WEIGHT_MAX}kg)")
    return weight


def resolve_drug(name: str, drugs_path=None) -> dict:
    """薬剤名またはエイリアスからマスタデータを解決"""
    drug = find_drug(name, path=drugs_path)
    if drug is None:
        raise ValueError(
            f"薬剤 '{name}' は未登録です。\n"
            f"  dose-calc drug add  で手動登録\n"
            f"  dose-calc suggest   でAI提案から登録"
        )
    return drug


def parse_calc_args(species: str, weight: float, drug_name: str,
                    drugs_path=None) -> tuple[str, float, dict]:
    """calcサブコマンドの引数をバリデーション+解決"""
    s = validate_species(species)
    w = validate_weight(weight)
    d = resolve_drug(drug_name, drugs_path)
    return s, w, d
