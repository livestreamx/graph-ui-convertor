from __future__ import annotations

from collections.abc import Sequence

from domain.models import MarkupDocument, Procedure


class BuildTeamProcedureGraph:
    def build(self, documents: Sequence[MarkupDocument]) -> MarkupDocument:
        procedures: list[Procedure] = []
        procedure_graph: dict[str, list[str]] = {}
        procedure_meta: dict[str, dict[str, str]] = {}
        team_labels: set[str] = set()

        for document in documents:
            team_label = self._resolve_team_label(document)
            service_label = self._resolve_service_label(document)
            if team_label:
                team_labels.add(team_label)

            for proc in document.procedures:
                if proc.procedure_id in procedure_meta:
                    msg = f"Duplicate procedure_id found while merging: {proc.procedure_id}"
                    raise ValueError(msg)
                procedures.append(proc)
                procedure_meta[proc.procedure_id] = {
                    "team_name": team_label,
                    "service_name": service_label,
                }

            for parent, children in document.procedure_graph.items():
                procedure_graph.setdefault(parent, [])
                for child in children:
                    if child not in procedure_graph[parent]:
                        procedure_graph[parent].append(child)

        for proc in procedures:
            procedure_graph.setdefault(proc.procedure_id, [])

        team_list = sorted(team_labels, key=lambda name: name.lower())
        title = ", ".join(team_list) if team_list else "Unknown team"

        return MarkupDocument(
            markup_type="procedure_graph",
            service_name=title,
            procedures=procedures,
            procedure_graph=procedure_graph,
            procedure_meta=procedure_meta,
        )

    def _resolve_team_label(self, document: MarkupDocument) -> str:
        if document.team_name:
            return str(document.team_name)
        if document.team_id is not None:
            return str(document.team_id)
        return "Unknown team"

    def _resolve_service_label(self, document: MarkupDocument) -> str:
        if document.service_name:
            return str(document.service_name)
        return "Unknown service"
