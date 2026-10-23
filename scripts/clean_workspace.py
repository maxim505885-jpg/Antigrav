"""Safe workspace cleanup utility.

Removes temporary test directories (.pytest-*, .test-data-*, .column_type_store_*)
without touching any production data, source clouds (1.rcs, 2.rcs), or real databases.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def cleanup() -> None:
    deleted_dirs = 0
    deleted_files = 0
    freed_bytes = 0

    # 1. Hidden test directories in project root
    for p in ROOT.iterdir():
        if not p.is_dir():
            if p.name.startswith(".column_type_store_") or p.name.startswith(".pytest_run_"):
                try:
                    freed_bytes += p.stat().st_size
                    p.unlink()
                    deleted_files += 1
                except Exception as e:
                    print(f"Could not delete {p.name}: {e}")
            continue

        if any(
            p.name.startswith(prefix)
            for prefix in (
                ".pytest-",
                ".test-data-",
                ".pytest_run_",
                ".codex-pytest",
                ".openapi-test",
                ".openapi-full",
                ".tmp-text",
                ".test-temp",
            )
        ):
            try:
                for sub in p.rglob("*"):
                    if sub.is_file():
                        freed_bytes += sub.stat().st_size
                shutil.rmtree(p, ignore_errors=True)
                deleted_dirs += 1
            except Exception as e:
                print(f"Could not delete directory {p.name}: {e}")

    print(
        f"Cleaned {deleted_dirs} temporary directories and {deleted_files} files "
        f"({freed_bytes / (1024 * 1024):.1f} MB freed)."
    )


if __name__ == "__main__":
    cleanup()
