"""llm_client — Gemini API クライアント（Search Grounding対応）

suggest_engine から呼ばれる。Search Grounding で根拠URL付き応答を取得。
"""

import json
import os
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds

# --- 設定読み込み ---

_CONFIG_CACHE = None


def _load_config() -> dict:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    config_path = Path(__file__).parent / "data" / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            _CONFIG_CACHE = yaml.safe_load(f) or {}
    else:
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def _gemini_config() -> dict:
    return _load_config().get("gemini", {})


def _get_api_url() -> str:
    cfg = _gemini_config()
    model = cfg.get("model", "gemini-2.0-flash")
    url_template = cfg.get(
        "api_url",
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    return url_template.format(model=model)


@dataclass
class LLMResponse:
    """LLM応答の構造化結果"""
    text: str
    grounding_chunks: list = field(default_factory=list)  # [{uri, title}, ...]
    raw_response: dict = field(default_factory=dict)


def _get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError(
            "Gemini APIキーが未設定です。環境変数 GEMINI_API_KEY または GOOGLE_API_KEY を設定してください。"
        )
    return key


def call_gemini(
    prompt: str,
    *,
    use_search: bool | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout_sec: int | None = None,
) -> LLMResponse:
    """Gemini API呼び出し（Search Grounding対応）

    引数未指定時はconfig.yamlの値を使用。

    Args:
        prompt: プロンプトテキスト
        use_search: Google Search Grounding を有効にするか
        max_tokens: 最大出力トークン
        temperature: 温度パラメータ
        timeout_sec: タイムアウト秒数

    Returns:
        LLMResponse(text, grounding_chunks, raw_response)

    Raises:
        RuntimeError: APIキー未設定、API障害
    """
    cfg = _gemini_config()
    if use_search is None:
        use_search = cfg.get("use_search_grounding", True)
    if max_tokens is None:
        max_tokens = cfg.get("max_tokens", 8192)
    if temperature is None:
        temperature = cfg.get("temperature", 0.2)
    if timeout_sec is None:
        timeout_sec = cfg.get("timeout_sec", 300)

    key = _get_api_key()
    api_url = _get_api_url()
    url = f"{api_url}?key={key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": temperature,
        },
    }

    if use_search:
        payload["tools"] = [{"google_search": {}}]

    data = json.dumps(payload).encode("utf-8")
    last_error = None

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return _parse_response(result)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            last_error = f"Gemini APIエラー ({e.code}): {body[:300]}"
            if e.code in (429, 500, 503):
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            raise RuntimeError(last_error) from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = f"ネットワークエラー: {e}"
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue

    raise RuntimeError(f"Gemini API {MAX_RETRIES}回リトライ後も失敗: {last_error}")


def _parse_response(result: dict) -> LLMResponse:
    """API応答をパース"""
    candidates = result.get("candidates", [])
    if not candidates:
        return LLMResponse(text="", raw_response=result)

    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text = parts[0].get("text", "") if parts else ""

    # Search Grounding メタデータ
    grounding_meta = candidate.get("groundingMetadata", {})
    chunks = []
    for chunk in grounding_meta.get("groundingChunks", []):
        web = chunk.get("web", {})
        if web.get("uri"):
            chunks.append({"uri": web["uri"], "title": web.get("title", "")})

    # リダイレクトURL解決（config.yamlで無効化可能）
    if _gemini_config().get("resolve_redirect_urls", True):
        chunks = _resolve_redirect_urls(chunks)

    return LLMResponse(text=text, grounding_chunks=chunks, raw_response=result)


REDIRECT_HOST = "vertexaisearch.cloud.google.com"


def _resolve_redirect_urls(chunks: list[dict]) -> list[dict]:
    """Search GroundingのリダイレクトURLを実URLに解決

    vertexaisearch.cloud.google.com/grounding-api-redirect/ のURLは
    HEADリクエストで実URLにリダイレクトされる。
    解決失敗時はリダイレクトURLをそのまま維持。
    """
    resolved = []
    for chunk in chunks:
        uri = chunk.get("uri", "")
        if REDIRECT_HOST in uri:
            real_url = _resolve_one(uri)
            resolved.append({"uri": real_url, "title": chunk.get("title", "")})
        else:
            resolved.append(chunk)
    return resolved


def _resolve_one(url: str) -> str:
    """1つのリダイレクトURLを解決。失敗時は元URLを返す。"""
    try:
        req = urllib.request.Request(url, method="HEAD")
        req.add_header("User-Agent", "OpenClaw-Agent/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.url
    except Exception:
        return url


# --- 堅牢JSONパーサー（3段階） ---

def extract_json(text: str) -> dict | list | None:
    """テキストからJSONを抽出（3段階パーサー）

    Stage 1: ```json ... ``` コードブロック抽出
    Stage 2: サニタイズ（末尾カンマ、コメント除去）
    Stage 3: 切り詰め救済（不完全JSONの部分抽出）
    """
    # Stage 1: コードブロック抽出
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    raw = m.group(1).strip() if m else text.strip()

    # まず素直にパース
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Stage 2: サニタイズ
    sanitized = _sanitize_json(raw)
    try:
        return json.loads(sanitized)
    except json.JSONDecodeError:
        pass

    # Stage 3: 切り詰め救済
    return _parse_truncated(sanitized)


def _sanitize_json(text: str) -> str:
    """JSON文字列のサニタイズ"""
    # 末尾カンマ除去: ,] → ] , ,} → }
    text = re.sub(r',\s*([}\]])', r'\1', text)
    # コメント除去
    text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
    return text


def _parse_truncated(text: str) -> dict | list | None:
    """切り詰められたJSONの部分抽出

    配列の最後が不完全な場合、完全な要素だけを返す
    """
    # suggestionsキーを含むオブジェクトを探す
    start = text.find('"suggestions"')
    if start == -1:
        start = text.find("'suggestions'")
    if start == -1:
        return None

    # 配列の開始を見つける
    arr_start = text.find('[', start)
    if arr_start == -1:
        return None

    # 完全なオブジェクトを1つずつ抽出
    items = []
    depth = 0
    obj_start = None

    for i in range(arr_start + 1, len(text)):
        c = text[i]
        if c == '{' and depth == 0:
            obj_start = i
            depth = 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                obj_text = text[obj_start:i + 1]
                try:
                    items.append(json.loads(obj_text))
                except json.JSONDecodeError:
                    pass
                obj_start = None

    if items:
        return {"suggestions": items}
    return None


def load_prompt(name: str, **kwargs) -> str:
    """data/prompts/ からプロンプトテンプレートを読み込む

    Args:
        name: プロンプト名（拡張子なし）
        **kwargs: テンプレート変数

    Returns:
        展開済みプロンプトテキスト
    """
    prompts_dir = Path(__file__).parent / "data" / "prompts"
    path = prompts_dir / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")

    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)
