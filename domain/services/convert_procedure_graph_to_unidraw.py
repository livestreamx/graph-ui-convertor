from __future__ import annotations

from typing import cast

from domain.models import MarkupDocument, UnidrawDocument
from domain.services.convert_markup_to_unidraw import MarkupToUnidrawConverter
from domain.services.convert_procedure_graph_base import ProcedureGraphConverterMixin


class ProcedureGraphToUnidrawConverter(ProcedureGraphConverterMixin, MarkupToUnidrawConverter):
    def convert(self, document: MarkupDocument) -> UnidrawDocument:
        return cast(UnidrawDocument, self._convert_procedure_graph(document))
