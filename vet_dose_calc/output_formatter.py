"""用量テーブル表示、商品別錠数表示、提案リスト表示、免責事項付加"""

from .dosage_calc import DoseResult, ProductAmount


SPECIES_LABELS = {"dog": "犬", "cat": "猫"}

DISCLAIMER_CALC = (
    "✅ 登録データに基づく計算結果です。\n"
    "臨床判断は必ず獣医師が行ってください。"
)

DISCLAIMER_SUGGEST = (
    "⚠️ AI提案です（参考情報）。臨床判断は獣医師が行ってください。\n"
    "根拠URLで内容を確認することを推奨します。"
)

WARNING_NTI = "⚠️ 治療域が狭い薬剤です。用量を慎重に確認してください。"
WARNING_CAT_CONTRA = "🚫 この薬剤は猫に禁忌として登録されています。"


def _fmt_dose(dose_min: float, dose_max: float) -> str:
    if dose_min == dose_max:
        return f"{dose_min:g} mg"
    return f"{dose_min:g}-{dose_max:g} mg"


def _fmt_amount(pa: ProductAmount) -> str:
    if pa.rounded_amount is not None and pa.rounded_amount != pa.amount:
        return f"{pa.rounded_amount:g} {pa.unit_label} (計算値: {pa.amount:g})"
    return f"{pa.amount:g} {pa.unit_label}"


def _strength_label(pa: ProductAmount) -> str:
    return f"{pa.strength:g}{pa.strength_unit.split('/')[0]}/{pa.strength_unit.split('/')[1]}"


def format_calc_result(
    drug_name: str,
    species: str,
    weight_kg: float,
    dose_results: list[DoseResult],
    product_amounts: list[list[ProductAmount]],
    safety_flags: dict,
) -> str:
    """calcコマンドの出力をフォーマット"""
    lines = []
    species_label = SPECIES_LABELS.get(species, species)

    lines.append("━━━ 薬用量計算結果 ━━━")
    lines.append(f"薬剤: {drug_name}")
    lines.append(f"動物: {species_label} / {weight_kg:g} kg")
    lines.append("")

    # 安全警告（最上部）
    if safety_flags.get("cat_contraindicated") and species == "cat":
        lines.append(WARNING_CAT_CONTRA)
        lines.append("")
    if safety_flags.get("narrow_therapeutic_index"):
        lines.append(WARNING_NTI)
        lines.append("")

    for i, dr in enumerate(dose_results):
        dose_str = _fmt_dose(dr.dose_min_mg, dr.dose_max_mg)
        lines.append(f"[{dr.indication or '一般'}] {dose_str}")
        meta_parts = []
        if dr.frequency:
            meta_parts.append(dr.frequency)
        if dr.route:
            meta_parts.append(dr.route)
        if dr.duration:
            meta_parts.append(f"期間: {dr.duration}")
        if meta_parts:
            lines.append(f"  {' | '.join(meta_parts)}")

        # 商品別投与量
        if i < len(product_amounts) and product_amounts[i]:
            for pa in product_amounts[i]:
                lines.append(f"  → {pa.brand} ({_strength_label(pa)}): {_fmt_amount(pa)}")

        if dr.notes:
            lines.append(f"  注: {dr.notes}")
        lines.append("")

    # 警告
    warnings = []
    for dr in dose_results:
        # warnings は species_data 側に入っているので外から渡す
        pass

    lines.append(DISCLAIMER_CALC)
    return "\n".join(lines)


def format_drug_list(drugs: list[dict]) -> str:
    if not drugs:
        return "登録薬剤はありません。"
    lines = ["━━━ 登録薬剤一覧 ━━━"]
    for i, d in enumerate(drugs, 1):
        aliases = ", ".join(d.get("aliases", [])[:3])
        source = d.get("source", "user_registered")
        source_mark = {"user_registered": "✅", "suggested_approved": "⚠️", "template_imported": "📋"}.get(source, "")
        lines.append(f"  {i}. {d['name']} {source_mark}")
        if aliases:
            lines.append(f"     別名: {aliases}")
    return "\n".join(lines)


def format_product_list(products: list[dict]) -> str:
    if not products:
        return "登録商品はありません。"
    lines = ["━━━ 登録商品一覧 ━━━"]
    for i, p in enumerate(products, 1):
        lines.append(f"  {i}. {p['brand']} ({p['drug']})")
        lines.append(f"     {p['strength']:g} {p['strength_unit']} / {p['form']}")
    return "\n".join(lines)


def format_suggest_result(
    species: str,
    symptoms: list[str],
    weight_kg: float | None,
    suggestions: list,
    grounding_urls: list[dict],
) -> str:
    """suggestコマンドの出力をフォーマット"""
    lines = []
    species_label = SPECIES_LABELS.get(species, species)

    lines.append("━━━ 薬剤提案（AI検索結果） ━━━")
    weight_str = f" / {weight_kg:g} kg" if weight_kg else ""
    lines.append(f"動物: {species_label}{weight_str}")
    lines.append(f"症状: {', '.join(symptoms)}")
    lines.append("")

    if not suggestions:
        lines.append("候補が見つかりませんでした。")
        lines.append("")
        lines.append(DISCLAIMER_SUGGEST)
        return "\n".join(lines)

    for i, s in enumerate(suggestions, 1):
        confidence_mark = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(s.confidence, "🟡")
        lines.append(f"[{i}] {s.drug_name_ja} ({s.drug_name_en}) — {s.category} {confidence_mark}")
        lines.append(f"    用量: {s.dose_mg_per_kg} mg/kg {s.frequency} {s.route}（{s.duration}）")

        if weight_kg and s.dose_mg_per_kg:
            try:
                parts = s.dose_mg_per_kg.replace("–", "-").split("-")
                dose_min = float(parts[0].strip()) * weight_kg
                lines.append(f"    → {species_label}{weight_kg:g}kg: {dose_min:g} mg")
            except (ValueError, IndexError):
                pass

        if s.products:
            prods = " / ".join(f"{p.brand} {p.strength:g}{p.strength_unit}" for p in s.products)
            lines.append(f"    商品: {prods}")

        if s.warnings:
            for w in s.warnings:
                lines.append(f"    ⚠️ {w}")

        if s.references:
            for r in s.references[:2]:
                lines.append(f"    📖 {r.title}")
                if r.url:
                    lines.append(f"       {r.url}")
        lines.append("")

    # Grounding URLs (Search Groundingから得たURL)
    if grounding_urls:
        lines.append("参考情報 (Google Search):")
        for g in grounding_urls[:5]:
            title = g.get("title", "")
            uri = g.get("uri", "")
            lines.append(f"  - {title}: {uri}" if title else f"  - {uri}")
        lines.append("")

    lines.append(DISCLAIMER_SUGGEST)
    return "\n".join(lines)


def format_drug_detail(drug: dict) -> str:
    lines = [f"━━━ {drug['name']} ━━━"]
    if drug.get("aliases"):
        lines.append(f"別名: {', '.join(drug['aliases'])}")
    lines.append(f"カテゴリ: {drug.get('category', '未設定')}")
    lines.append(f"登録元: {drug.get('source', 'user_registered')}")

    sf = drug.get("safety_flags", {})
    flags = []
    if sf.get("cat_contraindicated"):
        flags.append("🚫猫禁忌")
    if sf.get("narrow_therapeutic_index"):
        flags.append("⚠️NTI")
    if sf.get("requires_monitoring"):
        flags.append("📊要モニタリング")
    if flags:
        lines.append(f"安全フラグ: {' '.join(flags)}")

    for sp in ["dog", "cat"]:
        sp_data = drug.get("species_data", {}).get(sp, {})
        if not sp_data:
            continue
        sp_label = SPECIES_LABELS.get(sp, sp)
        lines.append(f"\n--- {sp_label} ---")
        for ind in sp_data.get("indications", []):
            lines.append(f"  [{ind.get('indication', '一般')}]")
            lines.append(f"    用量: {ind.get('dose_mg_per_kg', '?')} mg/kg {ind.get('frequency', '')} {ind.get('route', '')}")
            if ind.get("duration"):
                lines.append(f"    期間: {ind['duration']}")
            if ind.get("notes"):
                lines.append(f"    注: {ind['notes']}")
        if sp_data.get("warnings"):
            for w in sp_data["warnings"]:
                lines.append(f"  ⚠️ {w}")

    if drug.get("references"):
        lines.append("\n参考文献:")
        for ref in drug["references"]:
            if isinstance(ref, dict):
                lines.append(f"  - {ref.get('title', '')} {ref.get('url', '')}")
            else:
                lines.append(f"  - {ref}")

    return "\n".join(lines)
