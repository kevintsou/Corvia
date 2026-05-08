"""Base reporter abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from corvia.models import AnalysisResult


class BaseReporter(ABC):
    @abstractmethod
    def generate(self, result: AnalysisResult) -> str:
        ...

    def write(self, result: AnalysisResult, output_path: str) -> None:
        content = self.generate(result)
        Path(output_path).write_text(content, encoding="utf-8")
