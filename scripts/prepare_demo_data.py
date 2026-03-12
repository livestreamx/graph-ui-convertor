from __future__ import annotations

import argparse
import shutil
from pathlib import Path

MARKUP_SUFFIXES = (".json",)
EXCALIDRAW_SUFFIXES = (".excalidraw", ".excalidraw.lock")
UNIDRAW_SUFFIXES = (".unidraw", ".unidraw.lock")


def _matches_suffix(path: Path, suffixes: tuple[str, ...]) -> bool:
    return any(path.name.endswith(suffix) for suffix in suffixes)


def iter_files(root: Path, suffixes: tuple[str, ...]) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file() and _matches_suffix(path, suffixes)]


def sync_markup_files(source_dir: Path, target_dir: Path) -> None:
    source_files = iter_files(source_dir, MARKUP_SUFFIXES)
    if not source_files:
        raise SystemExit(f"No markup files found under {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    for relative in {path.relative_to(source_dir) for path in source_files}:
        source_path = source_dir / relative
        target_path = target_dir / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def clear_generated_files(target_dir: Path, suffixes: tuple[str, ...]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in iter_files(target_dir, suffixes):
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare local demo data from source markup fixtures."
    )
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--markup-dir", required=True)
    parser.add_argument("--excalidraw-dir", required=True)
    parser.add_argument("--unidraw-dir", required=True)
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    markup_dir = Path(args.markup_dir)
    excalidraw_dir = Path(args.excalidraw_dir)
    unidraw_dir = Path(args.unidraw_dir)

    if not source_dir.exists():
        raise SystemExit(f"Source directory not found: {source_dir}")

    sync_markup_files(source_dir, markup_dir)
    clear_generated_files(excalidraw_dir, EXCALIDRAW_SUFFIXES)
    clear_generated_files(unidraw_dir, UNIDRAW_SUFFIXES)

    print(f"Prepared demo markup in {markup_dir} from {source_dir}")
    print(f"Cleared generated Excalidraw files in {excalidraw_dir}")
    print(f"Cleared generated Unidraw files in {unidraw_dir}")


if __name__ == "__main__":
    main()
