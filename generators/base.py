"""
Base classes for output generators in the KYC Onboarding Intelligence System.

Provides abstract interfaces for brief and document generation.
"""

from abc import ABC, abstractmethod
from typing import Optional
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


class BaseGenerator(ABC):
    """
    Abstract base class for all output generators.

    Generators produce formatted output documents from KYC results.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of this generator."""
        pass

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Output format (markdown, pdf, json, etc.)."""
        pass

    @abstractmethod
    def generate(self, **kwargs) -> str:
        """Generate the output document."""
        pass

    def save(
        self,
        content: str,
        output_path: Path,
        filename: Optional[str] = None
    ) -> Path:
        """Save generated content to a file."""
        if filename is None:
            filename = f"{self.name}.{self.output_format}"

        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        file_path = output_path / filename
        file_path.write_text(content, encoding="utf-8")

        logger.info(f"Saved {self.name} to {file_path}")
        return file_path


class MarkdownGenerator(BaseGenerator):
    """Base class for markdown-based generators."""

    @property
    def output_format(self) -> str:
        return "md"


class PDFGenerator(BaseGenerator):
    """Base class for PDF generators."""

    @property
    def output_format(self) -> str:
        return "pdf"

    def save(
        self,
        content: str,
        output_path: Path,
        filename: Optional[str] = None
    ) -> Path:
        if filename is None:
            filename = f"{self.name}.{self.output_format}"

        output_path = Path(output_path)
        output_path.mkdir(parents=True, exist_ok=True)

        file_path = output_path / filename

        if isinstance(content, str):
            logger.warning(f"PDFGenerator received string content for {self.name}, saving as text")
            file_path = file_path.with_suffix(".md")
            file_path.write_text(content, encoding="utf-8")
        else:
            file_path.write_bytes(content)

        logger.info(f"Saved {self.name} to {file_path}")
        return file_path


class GeneratorRegistry:
    """Registry for managing output generators."""

    def __init__(self):
        self._generators: dict[str, BaseGenerator] = {}

    def register(self, generator: BaseGenerator):
        self._generators[generator.name] = generator
        logger.debug(f"Registered generator: {generator.name}")

    def get(self, name: str) -> Optional[BaseGenerator]:
        return self._generators.get(name)

    def get_all(self) -> list[BaseGenerator]:
        return list(self._generators.values())
