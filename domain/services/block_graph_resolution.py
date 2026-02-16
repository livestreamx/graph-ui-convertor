from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from domain.models import Procedure


@dataclass(frozen=True)
class ResolvedBlockGraphEdge:
    source_block_id: str
    target_block_id: str
    source_procedure_id: str
    target_procedure_id: str


def build_block_owner_index(
    procedures: Sequence[Procedure],
    owned_blocks_by_proc: Mapping[str, set[str]] | None = None,
) -> dict[str, set[str]]:
    owners: dict[str, set[str]] = {}
    for procedure in procedures:
        procedure_id = procedure.procedure_id
        block_ids = (
            owned_blocks_by_proc.get(procedure_id)
            if owned_blocks_by_proc is not None
            else procedure.block_ids()
        )
        if block_ids is None:
            block_ids = procedure.block_ids()
        for block_id in block_ids:
            owners.setdefault(block_id, set()).add(procedure_id)
    return owners


def resolve_block_graph_edges(
    block_graph: Mapping[str, Iterable[str]],
    owners_by_block: Mapping[str, set[str]],
    procedure_graph: Mapping[str, Iterable[str]],
) -> list[ResolvedBlockGraphEdge]:
    adjacency = _normalize_procedure_graph(procedure_graph)
    resolved: list[ResolvedBlockGraphEdge] = []
    seen: set[tuple[str, str, str, str]] = set()

    for source_block_id, targets in block_graph.items():
        source_candidates = owners_by_block.get(source_block_id, set())
        if not source_candidates:
            continue
        for target_block_id in targets:
            target_candidates = owners_by_block.get(target_block_id, set())
            if not target_candidates:
                continue
            pairs = _select_procedure_pairs(source_candidates, target_candidates, adjacency)
            if not pairs:
                continue
            for source_proc, target_proc in pairs:
                key = (source_block_id, target_block_id, source_proc, target_proc)
                if key in seen:
                    continue
                seen.add(key)
                resolved.append(
                    ResolvedBlockGraphEdge(
                        source_block_id=source_block_id,
                        target_block_id=target_block_id,
                        source_procedure_id=source_proc,
                        target_procedure_id=target_proc,
                    )
                )
    return resolved


def _normalize_procedure_graph(
    procedure_graph: Mapping[str, Iterable[str]],
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = {}
    for parent, children in procedure_graph.items():
        parent_id = str(parent)
        normalized = adjacency.setdefault(parent_id, set())
        for child in children:
            child_id = str(child)
            if child_id == parent_id:
                continue
            normalized.add(child_id)
    return adjacency


def _select_procedure_pairs(
    source_candidates: set[str],
    target_candidates: set[str],
    adjacency: Mapping[str, set[str]],
) -> list[tuple[str, str]]:
    if len(source_candidates) == 1 and len(target_candidates) == 1:
        return [(next(iter(source_candidates)), next(iter(target_candidates)))]

    pairs = [
        (source_proc, target_proc)
        for source_proc in sorted(source_candidates)
        for target_proc in sorted(target_candidates)
    ]
    if not pairs:
        return []

    direct = [pair for pair in pairs if pair[1] in adjacency.get(pair[0], set())]
    if direct:
        return direct

    # If block ids are reused across procedures, preserve per-procedure local edges.
    local = [(proc_id, proc_id) for proc_id in sorted(source_candidates & target_candidates)]
    if local:
        return local

    reverse = [pair for pair in pairs if pair[0] in adjacency.get(pair[1], set())]
    if reverse:
        return reverse

    return []
