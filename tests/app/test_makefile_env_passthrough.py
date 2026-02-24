from __future__ import annotations

import re
from pathlib import Path


def test_catalog_builder_excluded_team_ids_are_forwarded_to_catalog_container() -> None:
    makefile = Path("makefile").read_text(encoding="utf-8")

    assert re.search(
        r"CJM_CATALOG__BUILDER_EXCLUDED_TEAM_IDS.*CATALOG_ENV_EXTRA",
        makefile,
        re.S,
    )
    assert "CJM_CATALOG__HEALTH_SAME_TEAM_OVERLAP_THRESHOLD_PERCENT" in makefile
    assert "CJM_CATALOG__HEALTH_CROSS_TEAM_OVERLAP_THRESHOLD_PERCENT" in makefile
    assert "$(CATALOG_ENV_EXTRA) \\" in makefile
