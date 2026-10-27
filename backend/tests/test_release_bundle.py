from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_installer_does_not_duplicate_base_python_site_packages():
    installer = (ROOT / "installer" / "scan_studio_setup.iss").read_text(encoding="utf-8")
    venv_config = (ROOT / ".venv" / "pyvenv.cfg").read_text(encoding="utf-8")

    base_python_entry = next(
        line for line in installer.splitlines() if 'Source: "{#PythonBase}\\*"' in line
    )
    assert "include-system-site-packages = false" in venv_config
    assert "Lib\\site-packages\\*" in base_python_entry


def test_installer_excludes_python_type_stubs_and_stdlib_tests():
    installer = (ROOT / "installer" / "scan_studio_setup.iss").read_text(encoding="utf-8")
    venv_entry = next(
        line for line in installer.splitlines() if 'Source: "..\\.venv\\*"' in line
    )
    base_python_entry = next(
        line for line in installer.splitlines() if 'Source: "{#PythonBase}\\*"' in line
    )

    assert "Lib\\site-packages\\jedi\\third_party\\typeshed\\*" in venv_entry
    assert "Lib\\test\\*" in base_python_entry
