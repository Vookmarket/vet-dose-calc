"""vet-dose-calc — 獣医薬用量クイック計算ツール

二層アーキテクチャ:
- calc: ルールベース層（登録済みDBから即時計算）
- suggest: LLM拡張層（Gemini API + Search Groundingで薬剤提案→DB登録）
"""

__version__ = "1.0.0"
