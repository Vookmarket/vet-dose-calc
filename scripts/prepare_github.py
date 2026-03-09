#!/usr/bin/env python3
"""GitHub公開用にリポジトリ構造を準備するスクリプト

VT-004/ のソースを vet_dose_calc/ パッケージ構造に変換し、
bare import を relative import に変換する。

使い方:
    cd <新規リポジトリのルート>
    python3 scripts/prepare_github.py <VT-004のパス>

生成される構造:
    vet-dose-calc/
    ├── pyproject.toml
    ├── LICENSE
    ├── .gitignore
    ├── README.md
    ├── vet_dose_calc/
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── tool.py
    │   ├── ...
    │   └── data/
    │       ├── config.yaml
    │       ├── prompts/suggest.txt
    │       └── templates/chatgpt_pro_33drugs.yaml
    └── tests/
        ├── conftest.py
        └── test_*.py
"""

import re
import shutil
import sys
from pathlib import Path

# VT-004内のPythonモジュール名（bare import対象）
MODULES = [
    "dosage_calc",
    "drug_registry",
    "product_registry",
    "input_parser",
    "output_formatter",
    "llm_client",
    "suggest_engine",
    "registration_flow",
    "tool",
]

# bare import → relative import の変換パターン
IMPORT_PATTERNS = []
for mod in MODULES:
    # from module import ...  →  from .module import ...
    IMPORT_PATTERNS.append(
        (re.compile(rf'^(from\s+){mod}(\s+import\s+)', re.MULTILINE),
         rf'\1.{mod}\2')
    )
    # import module  →  from . import module
    IMPORT_PATTERNS.append(
        (re.compile(rf'^import\s+{mod}\s*$', re.MULTILINE),
         f'from . import {mod}')
    )


def convert_imports(content: str) -> str:
    """bare import を relative import に変換（パッケージソース用）"""
    for pattern, replacement in IMPORT_PATTERNS:
        content = pattern.sub(replacement, content)
    return content


def convert_test_imports(content: str) -> str:
    """テストファイルのimportを vet_dose_calc.module 形式に変換"""
    # sys.path.insert 行を除去
    content = re.sub(
        r'^sys\.path\.insert\(0,\s*str\(Path\(__file__\)\.parent\.parent\)\)\s*\n',
        '',
        content,
        flags=re.MULTILINE,
    )
    # from module import ... → from vet_dose_calc.module import ...
    # インデントされたインライン import にも対応（^ ではなく行頭空白を許容）
    for mod in MODULES:
        content = re.sub(
            rf'^(\s*from\s+){mod}(\s+import\s+)',
            rf'\1vet_dose_calc.{mod}\2',
            content,
            flags=re.MULTILINE,
        )
        content = re.sub(
            rf'^(\s*import\s+){mod}\s*$',
            rf'\1vet_dose_calc.{mod}',
            content,
            flags=re.MULTILINE,
        )
    # @patch("module.func") → @patch("vet_dose_calc.module.func")
    for mod in MODULES:
        content = re.sub(
            rf'@patch\("({mod})\.',
            rf'@patch("vet_dose_calc.\1.',
            content,
        )
        content = re.sub(
            rf'patch\("({mod})\.',
            rf'patch("vet_dose_calc.\1.',
            content,
        )

    # TOOL_DIR → PKG_DIR (パッケージディレクトリ参照)
    if "TOOL_DIR" in content:
        # TOOL_DIR定義を置換
        content = re.sub(
            r'^TOOL_DIR\s*=\s*Path\(__file__\)\.parent\.parent\s*$',
            'import vet_dose_calc\nPKG_DIR = Path(vet_dose_calc.__file__).parent',
            content,
            flags=re.MULTILINE,
        )
        content = content.replace("TOOL_DIR", "PKG_DIR")
        # subprocess実行を -m vet_dose_calc 形式に変換
        content = re.sub(
            r'\[sys\.executable,\s*str\(PKG_DIR\s*/\s*"tool\.py"\),\s*\*args\]',
            '[sys.executable, "-m", "vet_dose_calc", *args]',
            content,
        )
        content = re.sub(
            r'cwd=str\(PKG_DIR\),?\s*',
            '',
            content,
        )

    return content


def prepare(vt004_path: Path, output_path: Path):
    """VT-004からGitHub公開用構造を生成"""
    pkg_dir = output_path / "vet_dose_calc"
    tests_dir = output_path / "tests"

    # ディレクトリ作成
    pkg_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "data" / "prompts").mkdir(parents=True, exist_ok=True)
    (pkg_dir / "data" / "templates").mkdir(parents=True, exist_ok=True)

    # ルートファイルコピー
    for f in ["pyproject.toml", "LICENSE", ".gitignore", "README.md"]:
        src = vt004_path / f
        if src.exists():
            shutil.copy2(src, output_path / f)

    # ソースファイルコピー＋import変換
    source_files = ["__init__.py", "tool.py", "dosage_calc.py",
                    "drug_registry.py", "product_registry.py",
                    "input_parser.py", "output_formatter.py",
                    "llm_client.py", "suggest_engine.py",
                    "registration_flow.py"]

    for f in source_files:
        src = vt004_path / f
        if not src.exists():
            print(f"  SKIP {f} (not found)")
            continue
        content = src.read_text(encoding="utf-8")
        content = convert_imports(content)
        (pkg_dir / f).write_text(content, encoding="utf-8")
        print(f"  {f} → vet_dose_calc/{f}")

    # __main__.py は特別処理
    main_content = '"""python -m vet_dose_calc で実行可能にする"""\n\nfrom .tool import main\n\nmain()\n'
    (pkg_dir / "__main__.py").write_text(main_content, encoding="utf-8")
    print("  __main__.py → vet_dose_calc/__main__.py (relative import)")

    # データファイル
    data_src = vt004_path / "data"
    shutil.copy2(data_src / "config.yaml", pkg_dir / "data" / "config.yaml")
    shutil.copy2(data_src / "prompts" / "suggest.txt", pkg_dir / "data" / "prompts" / "suggest.txt")
    if (data_src / "templates" / "chatgpt_pro_33drugs.yaml").exists():
        shutil.copy2(
            data_src / "templates" / "chatgpt_pro_33drugs.yaml",
            pkg_dir / "data" / "templates" / "chatgpt_pro_33drugs.yaml",
        )
    print("  data/ → vet_dose_calc/data/")

    # テストファイル
    tests_src = vt004_path / "tests"
    # conftest.py は不要（パッケージインストールでimport解決）
    conftest_content = '"""テスト共通設定 — pip install -e . でパッケージインストール済み前提"""\n'
    (tests_dir / "conftest.py").write_text(conftest_content, encoding="utf-8")
    print("  conftest.py → tests/conftest.py (minimal)")

    # テストファイルコピー＋import変換
    for f in tests_src.glob("test_*.py"):
        content = f.read_text(encoding="utf-8")
        content = convert_test_imports(content)
        (tests_dir / f.name).write_text(content, encoding="utf-8")
        print(f"  {f.name} → tests/{f.name} (imports converted)")

    # テストフィクスチャ
    fixtures_src = tests_src / "fixtures"
    if fixtures_src.exists():
        fixtures_dst = tests_dir / "fixtures"
        if fixtures_dst.exists():
            shutil.rmtree(fixtures_dst)
        shutil.copytree(fixtures_src, fixtures_dst)
        print("  fixtures/ → tests/fixtures/")

    # scriptsディレクトリ
    scripts_dir = output_path / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), scripts_dir / "prepare_github.py")

    print(f"\n✅ GitHub公開用構造を {output_path} に生成しました。")
    print(f"   パッケージ: vet_dose_calc/")
    print(f"   テスト: tests/")
    print(f"\n次のステップ:")
    print(f"   cd {output_path}")
    print(f"   pip install -e '.[dev]'")
    print(f"   pytest tests/ -v")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <VT-004_PATH> [OUTPUT_PATH]")
        sys.exit(1)

    vt004 = Path(sys.argv[1]).resolve()
    output = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path.cwd()

    if not vt004.exists():
        print(f"Error: {vt004} not found")
        sys.exit(1)

    prepare(vt004, output)
