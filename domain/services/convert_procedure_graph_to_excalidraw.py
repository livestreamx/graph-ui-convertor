from __future__ import annotations

from typing import cast

from domain.models import ExcalidrawDocument, MarkupDocument
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from domain.services.convert_procedure_graph_base import ProcedureGraphConverterMixin


class ProcedureGraphToExcalidrawConverter(
    ProcedureGraphConverterMixin, MarkupToExcalidrawConverter
):
    def convert(self, document: MarkupDocument) -> ExcalidrawDocument:
        return cast(ExcalidrawDocument, self._convert_procedure_graph(document))
