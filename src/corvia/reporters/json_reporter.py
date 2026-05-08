"""JSON report generator."""

from __future__ import annotations

import json

from corvia.models import AnalysisResult
from corvia.reporters.base import BaseReporter


class JsonReporter(BaseReporter):
    def generate(self, result: AnalysisResult) -> str:
        return json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
