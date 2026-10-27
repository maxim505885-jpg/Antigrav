"""Compare all Python modules shipped in an installed SCAN bundle to source."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def _runtime_sources(root: Path) -> dict[str, Path]:
    package = root / "backend" / "scan2bim"
    launcher = root / "desktop_app.py"
    if not package.is_dir() or not launcher.is_file():
        return {}

    files = {"desktop_app.py": launcher}
    files.update({
        "backend/scan2bim/" + path.relative_to(package).as_posix(): path
        for path in package.rglob("*.py")
        if path.is_file()
    })
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compare_runtime_sources(source_root: Path, installed_root: Path) -> dict[str, list[str]]:
    """Return missing, extra, and byte-different shipped Python source paths."""
    source = _runtime_sources(Path(source_root))
    installed = _runtime_sources(Path(installed_root))
    if not source:
        raise ValueError(f"No SCAN runtime Python sources found under {source_root}")

    source_names = set(source)
    installed_names = set(installed)
    common = source_names & installed_names
    return {
        "missing_installed": sorted(source_names - installed_names),
        "unexpected_installed": sorted(installed_names - source_names),
        "hash_mismatches": sorted(
            name for name in common if _sha256(source[name]) != _sha256(installed[name])
        ),
    }


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: verify_installed_sources.py SOURCE_ROOT INSTALLED_ROOT", file=sys.stderr)
        return 2
    try:
        result = compare_runtime_sources(Path(sys.argv[1]), Path(sys.argv[2]))
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if any(result.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
