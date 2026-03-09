"""統合テスト — tool.py (calc サブコマンド)"""

import sys
import shutil
import subprocess
from pathlib import Path

import pytest

import vet_dose_calc
PKG_DIR = Path(vet_dose_calc.__file__).parent
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def setup_data(tmp_path):
    """テスト用のdrugs.yaml / products.yaml をdata/にコピー"""
    data_dir = PKG_DIR / "data"
    # バックアップ
    drugs_bak = None
    products_bak = None
    if (data_dir / "drugs.yaml").exists():
        drugs_bak = (data_dir / "drugs.yaml").read_text(encoding="utf-8")
    if (data_dir / "products.yaml").exists():
        products_bak = (data_dir / "products.yaml").read_text(encoding="utf-8")

    # テストフィクスチャをコピー
    shutil.copy(FIXTURES / "drugs.yaml", data_dir / "drugs.yaml")
    shutil.copy(FIXTURES / "products.yaml", data_dir / "products.yaml")

    yield

    # 復元
    if drugs_bak is not None:
        (data_dir / "drugs.yaml").write_text(drugs_bak, encoding="utf-8")
    else:
        (data_dir / "drugs.yaml").unlink(missing_ok=True)
    if products_bak is not None:
        (data_dir / "products.yaml").write_text(products_bak, encoding="utf-8")
    else:
        (data_dir / "products.yaml").unlink(missing_ok=True)


def run_tool(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "vet_dose_calc", *args],
        capture_output=True, text=True, )


class TestCalc:
    def test_basic(self):
        r = run_tool("calc", "dog", "5.0", "アモキシシリン")
        assert r.returncode == 0
        assert "62.5" in r.stdout  # 12.5 * 5 = 62.5
        assert "クラバモックス小型犬用" in r.stdout
        assert "登録データに基づく" in r.stdout

    def test_alias(self):
        r = run_tool("calc", "dog", "5.0", "AMPC/CVA")
        assert r.returncode == 0
        assert "アモキシシリン/クラブラン酸" in r.stdout

    def test_cat_contraindicated(self):
        r = run_tool("calc", "cat", "4.0", "ペルメトリン")
        assert r.returncode == 0
        assert "禁忌" in r.stdout

    def test_nti_warning(self):
        r = run_tool("calc", "dog", "10.0", "ジゴキシン")
        assert r.returncode == 0
        assert "治療域が狭い" in r.stdout

    def test_unknown_drug(self):
        r = run_tool("calc", "dog", "5.0", "不明薬")
        assert r.returncode == 1
        assert "未登録" in r.stdout

    def test_invalid_weight(self):
        r = run_tool("calc", "dog", "-1", "アモキシシリン")
        assert r.returncode == 1


class TestDrugList:
    def test_list(self):
        r = run_tool("drug", "list")
        assert r.returncode == 0
        assert "アモキシシリン/クラブラン酸" in r.stdout
        assert "ジゴキシン" in r.stdout

    def test_show(self):
        r = run_tool("drug", "show", "ジゴキシン")
        assert r.returncode == 0
        assert "NTI" in r.stdout or "治療域" in r.stdout


class TestProductList:
    def test_list(self):
        r = run_tool("product", "list")
        assert r.returncode == 0
        assert "クラバモックス小型犬用" in r.stdout
