from dataclasses import dataclass
from typing import Protocol


class PdfReadError(Exception):
    """Raised when a PDF cannot be opened or text cannot be extracted."""


@dataclass(frozen=True)
class PdfTextDocument:
    pages: list[str]


class PdfTextExtractor(Protocol):
    def extract_text(self, content: bytes) -> PdfTextDocument:
        """Return physical pages of extracted text."""


class PyMuPdfTextExtractor:
    def extract_text(self, content: bytes) -> PdfTextDocument:
        try:
            import fitz

            with fitz.open(stream=content, filetype="pdf") as document:
                pages = [page.get_text("text") for page in document]
        except Exception as exc:  # pragma: no cover - exercised with integration PDFs.
            raise PdfReadError from exc

        if not pages:
            raise PdfReadError
        return PdfTextDocument(pages=pages)

