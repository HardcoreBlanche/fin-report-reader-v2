from dataclasses import dataclass, field
from typing import Protocol


class PdfReadError(Exception):
    """Raised when a PDF cannot be opened or text cannot be extracted."""


@dataclass(frozen=True)
class PdfFigureCandidate:
    candidate_id: str
    page: int
    bbox: list[float]
    width: int
    height: int
    image_bytes: bytes
    image_extension: str = "png"
    title: str | None = None
    caption: str | None = None
    role: str | None = None
    occurrence_count: int = 1
    page_width: float | None = None
    page_height: float | None = None


@dataclass(frozen=True)
class PdfTextDocument:
    pages: list[str]
    figure_candidates: list[PdfFigureCandidate] = field(default_factory=list)


class PdfTextExtractor(Protocol):
    def extract_text(self, content: bytes) -> PdfTextDocument:
        """Return physical pages of extracted text."""


class PyMuPdfTextExtractor:
    def extract_text(self, content: bytes) -> PdfTextDocument:
        try:
            import fitz

            with fitz.open(stream=content, filetype="pdf") as document:
                pages = []
                figure_candidates: list[PdfFigureCandidate] = []
                for page_index, page in enumerate(document):
                    pages.append(page.get_text("text"))
                    page_rect = page.rect
                    page_dict = page.get_text("dict")
                    for block_index, block in enumerate(page_dict.get("blocks", [])):
                        if block.get("type") != 1 or not block.get("image"):
                            continue
                        bbox = [float(value) for value in block.get("bbox", [])]
                        if len(bbox) != 4:
                            continue
                        image_extension = str(block.get("ext") or "png").lower()
                        figure_candidates.append(
                            PdfFigureCandidate(
                                candidate_id=f"p{page_index + 1}_image_{block_index + 1}",
                                page=page_index + 1,
                                bbox=bbox,
                                width=int(block.get("width") or max(bbox[2] - bbox[0], 0)),
                                height=int(block.get("height") or max(bbox[3] - bbox[1], 0)),
                                image_bytes=block["image"],
                                image_extension=image_extension,
                                page_width=float(page_rect.width),
                                page_height=float(page_rect.height),
                            )
                        )
        except Exception as exc:  # pragma: no cover - exercised with integration PDFs.
            raise PdfReadError from exc

        if not pages:
            raise PdfReadError
        return PdfTextDocument(pages=pages, figure_candidates=figure_candidates)
