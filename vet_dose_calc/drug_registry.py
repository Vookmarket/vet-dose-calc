"""薬剤マスタCRUD — drugs.yaml の読み書き"""

import os
from pathlib import Path
from typing import Optional

import yaml


def _default_path() -> Path:
    return Path(__file__).parent / "data" / "drugs.yaml"


def load_drugs(path: Optional[Path] = None) -> list[dict]:
    p = path or _default_path()
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("drugs", [])


def save_drugs(drugs: list[dict], path: Optional[Path] = None) -> None:
    p = path or _default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(
            {"drugs": drugs},
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


def find_drug(name: str, drugs: Optional[list[dict]] = None, path: Optional[Path] = None) -> Optional[dict]:
    """名前またはエイリアスで薬剤を検索（大文字小文字無視）"""
    if drugs is None:
        drugs = load_drugs(path)
    query = name.lower()
    for drug in drugs:
        if drug.get("name", "").lower() == query:
            return drug
        for alias in drug.get("aliases", []):
            if alias.lower() == query:
                return drug
    return None


def add_drug(drug: dict, path: Optional[Path] = None) -> None:
    drugs = load_drugs(path)
    existing = find_drug(drug["name"], drugs)
    if existing:
        raise ValueError(f"薬剤 '{drug['name']}' は既に登録されています")
    drugs.append(drug)
    save_drugs(drugs, path)


def list_drugs(path: Optional[Path] = None) -> list[dict]:
    return load_drugs(path)


def import_drugs(template_path: Path, target_path: Optional[Path] = None) -> int:
    """テンプレートYAMLからインポート。既存と重複するものはスキップ。"""
    with open(template_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    template_drugs = data.get("drugs", [])
    existing = load_drugs(target_path)
    added = 0
    for td in template_drugs:
        td["source"] = td.get("source", "template_imported")
        if not find_drug(td["name"], existing):
            existing.append(td)
            added += 1
    save_drugs(existing, target_path)
    return added
