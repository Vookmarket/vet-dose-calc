# vet-dose-calc

獣医臨床向け薬用量クイック計算ツール。二層アーキテクチャで、ルールベース計算とAI薬剤提案を統合。

## 特徴

- **calc**: 登録済み薬剤DBから即時用量計算（体重→mg→錠数/ml数）
- **suggest**: Gemini API + Google Search で症状から薬剤候補を提案（根拠URL付き）
- **ユーザー管理DB**: 獣医師自身が薬剤・商品データを登録・管理
- **安全設計**: suggest結果は直接投与不可（DB登録=獣医師承認を必ず経由）

## アーキテクチャ

```
┌──────────────────────────────────────────┐
│  LLM拡張層（suggest）                     │
│  Gemini API + Search Grounding            │
│  症状→薬剤候補+商品名+用量+根拠URL        │
│  ⚠️ AI提案（要獣医師確認）               │
│         │                                 │
│         ▼ ユーザー承認                    │
│  ┌──────────────┐                         │
│  │ DB登録フロー  │ → drugs.yaml            │
│  │（対話式確認） │ → products.yaml         │
│  └──────────────┘                         │
├──────────────────────────────────────────┤
│  ルールベース層（calc）                    │
│  drugs.yaml + products.yaml               │
│  薬剤+体重→用量計算+商品別錠数/ml数       │
│  ✅ 登録データに基づく確定計算             │
└──────────────────────────────────────────┘
```

## セットアップ

### 必要環境

- Python 3.12+
- PyYAML

### インストール

```bash
pip install vet-dose-calc
```

### Gemini APIキーの設定（suggest機能に必要）

```bash
export GEMINI_API_KEY="your-api-key-here"
```

[Google AI Studio](https://aistudio.google.com/) から無料で取得できます。
calc（用量計算）はAPIキーなしで動作します。

## 使い方

### 用量計算（calc）

```bash
# 犬 5kg にアモキシシリンの用量を計算
vet-dose-calc calc dog 5.0 アモキシシリン

# 出力例:
# ━━━ 薬用量計算結果 ━━━
# 薬剤: アモキシシリン/クラブラン酸
# 動物: 犬 / 5 kg
#
# [一般感染症] 62.5-125 mg
#   BID | PO | 期間: 7-14日
#   → クラバモックス小型犬用 (62.5mg/錠): 1 錠
#
# ✅ 登録データに基づく計算結果です。
# 臨床判断は必ず獣医師が行ってください。
```

### 薬剤提案（suggest）

```bash
# 犬 5kg の嘔吐・食欲不振に対する薬剤を提案
vet-dose-calc suggest dog 嘔吐 食欲不振 --weight 5.0

# 出力例:
# ━━━ 薬剤提案（AI検索結果） ━━━
# 動物: 犬 / 5 kg
# 症状: 嘔吐, 食欲不振
#
# [1] マロピタント (maropitant) — antiemetic 🟢
#     用量: 2 mg/kg SID PO（最大5日間）
#     → 犬5kg: 10 mg
#     商品: セレニア錠 16mg
#     📖 Merck Vet Manual
#        https://www.merckvetmanual.com/...
#
# ⚠️ AI提案です（参考情報）。
# 根拠URLで内容を確認することを推奨します。
#
# DBに登録しますか？ [1/2/3/all/none]:
```

### 薬剤マスタ管理

```bash
# 薬剤一覧
vet-dose-calc drug list

# 薬剤詳細
vet-dose-calc drug show アモキシシリン

# 手動で薬剤追加（対話式）
vet-dose-calc drug add

# テンプレートYAMLからインポート
vet-dose-calc drug import data/templates/chatgpt_pro_33drugs.yaml
```

### 商品マスタ管理

```bash
# 商品一覧
vet-dose-calc product list

# 手動で商品追加（対話式）
vet-dose-calc product add
```

## データ構造

### drugs.yaml（薬剤マスタ）

獣医師が登録・管理する薬剤データ。

```yaml
drugs:
  - name: アモキシシリン/クラブラン酸
    aliases: [AMPC/CVA, amoxicillin/clavulanate]
    category: antibiotics
    source: user_registered  # user_registered / suggested_approved / template_imported
    species_data:
      dog:
        indications:
          - indication: 一般感染症
            dose_mg_per_kg: "12.5-25"
            frequency: BID
            route: PO
            duration: "7-14日"
    safety_flags:
      cat_contraindicated: false
      narrow_therapeutic_index: false
```

### products.yaml（商品マスタ）

```yaml
products:
  - brand: クラバモックス小型犬用
    drug: アモキシシリン/クラブラン酸
    strength: 62.5
    strength_unit: mg/tab   # mg/tab, mg/ml, percent, iu/ml 等10種対応
    form: tablet
    divisible: true
    min_division: 0.5
```

### 対応 strength_unit

| 単位 | 説明 | 計算方式 |
|------|------|---------|
| mg/tab | 錠剤 mg/1錠 | 必要量 ÷ strength = 錠数 |
| mg/cap | カプセル mg/1個 | 同上 |
| mg/packet | 散剤 mg/1包 | 同上 |
| mg/ml | 液剤 mg/1ml | 必要量 ÷ strength = ml |
| percent | 濃度% | 必要量 ÷ (strength × 10) = ml |
| iu/ml | 国際単位/ml | 必要量IU ÷ strength = ml |
| mcg/tab | μg/1錠 | 同上 |
| mg/vial | バイアル全量 | 必要量 ÷ strength = 本 |
| mg/pipette | ピペット全量 | 体重帯マッチング |
| mg/pump | 1プッシュ mg | 必要量 ÷ strength = 回 |

## 設定

`data/config.yaml` でGemini APIの設定を変更できます。

```yaml
gemini:
  model: "gemini-2.0-flash"
  timeout_sec: 300
  use_search_grounding: true
  resolve_redirect_urls: true
```

## テスト

```bash
pytest tests/ -v
```

## 免責事項

本ツールは獣医臨床の補助を目的としています。

- **calc出力**: ユーザーが登録したデータに基づく計算結果です。データの正確性はユーザーの責任です。
- **suggest出力**: AI（Gemini API）による参考情報です。臨床判断は必ず獣医師が行ってください。
- 本ツールの出力を根拠とした医療行為の結果について、開発者は一切の責任を負いません。

## ライセンス

MIT License
