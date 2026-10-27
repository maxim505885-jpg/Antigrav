import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_installed_sources.py"
_SPEC = importlib.util.spec_from_file_location("verify_installed_sources", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
compare_runtime_sources = _MODULE.compare_runtime_sources


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_runtime_source_comparison_accepts_identical_installed_tree(tmp_path):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    for root in (source, installed):
        _write(root, "desktop_app.py", "print('launch')\n")
        _write(root, "backend/scan2bim/api/app.py", "app = True\n")
        _write(root, "backend/scan2bim/structure/gost_catalog.py", "CATALOG = ()\n")

    assert compare_runtime_sources(source, installed) == {
        "missing_installed": [],
        "unexpected_installed": [],
        "hash_mismatches": [],
    }


def test_runtime_source_comparison_finds_changed_missing_and_extra_modules(tmp_path):
    source = tmp_path / "source"
    installed = tmp_path / "installed"
    _write(source, "desktop_app.py", "print('launch')\n")
    _write(source, "backend/scan2bim/api/app.py", "app = True\n")
    _write(source, "backend/scan2bim/structure/gost_catalog.py", "CATALOG = ('current',)\n")
    _write(installed, "desktop_app.py", "print('launch')\n")
    _write(installed, "backend/scan2bim/api/app.py", "app = False\n")
    _write(installed, "backend/scan2bim/obsolete.py", "old = True\n")

    assert compare_runtime_sources(source, installed) == {
        "missing_installed": ["backend/scan2bim/structure/gost_catalog.py"],
        "unexpected_installed": ["backend/scan2bim/obsolete.py"],
        "hash_mismatches": ["backend/scan2bim/api/app.py"],
    }
