from __future__ import annotations

import copy
import json
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

from domain.models import MarkupDocument


@lru_cache(maxsize=1)
def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Repository root not found")


@cache
def _load_markup_document_cached(name: str) -> MarkupDocument:
    fixture_path = repo_root() / "examples" / "markup" / name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    return MarkupDocument.model_validate(payload)


def load_markup_fixture(name: str) -> MarkupDocument:
    return _load_markup_document_cached(name).model_copy(deep=True)


@cache
def _load_markup_payload_cached(name: str) -> dict[str, Any]:
    fixture_path = repo_root() / "examples" / "markup" / name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected dict payload in {fixture_path}")
    return payload


def load_markup_payload(name: str) -> dict[str, Any]:
    return copy.deepcopy(_load_markup_payload_cached(name))


@cache
def _load_expected_payload_cached(name: str) -> dict[str, Any]:
    expected_name = name.replace(".json", ".expected.json")
    fixture_path = repo_root() / "examples" / "markup_expected" / expected_name
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected dict payload in {fixture_path}")
    return payload


def load_expected_fixture(name: str) -> dict[str, Any]:
    return copy.deepcopy(_load_expected_payload_cached(name))
