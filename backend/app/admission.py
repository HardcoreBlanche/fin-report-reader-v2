from dataclasses import dataclass
import re
import unicodedata

from backend.app.errors import BusinessError
from backend.app.pdf_extraction import PdfReadError, PdfTextExtractor


COMPANY_PROFILE_TITLE = "公司简介和主要财务指标"


@dataclass(frozen=True)
class AcceptedAnnualReportSource:
    stock_code: str
    normalized_stock_code: str
    exchange: str
    company_full_name: str
    company_short_name: str | None
    report_year: int
    section_location_strategy: str


@dataclass(frozen=True)
class LocatedSection:
    text: str
    strategy: str


class UploadAdmissionService:
    def __init__(self, extractor: PdfTextExtractor):
        self.extractor = extractor

    def admit(self, filename: str, content: bytes) -> AcceptedAnnualReportSource:
        if not filename.lower().endswith(".pdf"):
            raise BusinessError("INVALID_FILE_EXTENSION")
        if not content.startswith(b"%PDF-"):
            raise BusinessError("INVALID_PDF_HEADER")

        try:
            document = self.extractor.extract_text(content)
        except PdfReadError as exc:
            raise BusinessError("INVALID_PDF_FILE") from exc

        pages = document.pages
        first_page = pages[0] if pages else ""
        preview_text = "\n".join(pages[:5])

        self._reject_unsupported_report_type(first_page, preview_text)
        report_year = self._extract_report_year(first_page)
        if report_year is None:
            raise BusinessError("MISSING_REPORT_YEAR")

        located_section = self._locate_company_profile_section(pages)
        section_text = located_section.text

        company_full_name = self._extract_company_full_name(section_text)
        if company_full_name is None:
            raise BusinessError("MISSING_COMPANY_FULL_NAME")

        first_page_company_name = self._extract_first_page_company_name(first_page)
        if first_page_company_name is not None and (
            normalize_company_name(first_page_company_name)
            != normalize_company_name(company_full_name)
        ):
            raise BusinessError("COMPANY_FULL_NAME_MISMATCH")

        stock_identity = self._extract_stock_identity(section_text)
        if stock_identity is None:
            raise BusinessError("MISSING_STOCK_CODE")

        financial_year = self._extract_financial_data_year(section_text)
        if financial_year is None:
            raise BusinessError("TABLE_DATE_EXTRACTION_FAILED")
        if financial_year != report_year:
            raise BusinessError("REPORT_YEAR_MISMATCH")

        return AcceptedAnnualReportSource(
            stock_code=stock_identity.stock_code,
            normalized_stock_code=stock_identity.normalized_stock_code,
            exchange=stock_identity.exchange,
            company_full_name=company_full_name,
            company_short_name=self._extract_company_short_name(section_text),
            report_year=report_year,
            section_location_strategy=located_section.strategy,
        )

    def _reject_unsupported_report_type(self, first_page: str, preview_text: str) -> None:
        if self._chinese_character_count(first_page) < 5 and re.search(
            r"annual\s+report",
            first_page,
            re.IGNORECASE,
        ):
            raise BusinessError("NON_CHINESE_ANNUAL_REPORT")
        if "年度报告摘要" in first_page or "年报摘要" in first_page:
            raise BusinessError("ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED")
        unsupported_markers = ["季度报告", "第一季度报告", "第三季度报告", "半年度报告", "中期报告"]
        if any(marker in first_page for marker in unsupported_markers):
            raise BusinessError("NOT_AN_ANNUAL_REPORT")
        if "年度报告" not in first_page and "年报" not in first_page:
            raise BusinessError("NOT_AN_ANNUAL_REPORT")

    def _extract_report_year(self, first_page: str) -> int | None:
        match = re.search(r"(?<!\d)((?:19|20)\d{2})\s*年\s*(?:年度报告|年报)(?!摘要)", first_page)
        if match is None:
            return None
        return int(match.group(1))

    def _locate_company_profile_section(self, pages: list[str]) -> LocatedSection:
        toc_section = self._locate_section_from_table_of_contents(pages)
        if toc_section is not None:
            return toc_section

        for index, page_text in enumerate(pages[:20]):
            if COMPANY_PROFILE_TITLE in page_text and not self._is_table_of_contents_only(page_text):
                return LocatedSection(
                    text=self._collect_section_text(pages, index),
                    strategy="heading_search",
                )
        raise BusinessError("COMPANY_PROFILE_SECTION_NOT_FOUND")

    def _locate_section_from_table_of_contents(self, pages: list[str]) -> LocatedSection | None:
        for page_text in pages[:10]:
            if "目录" not in page_text or COMPANY_PROFILE_TITLE not in page_text:
                continue
            match = re.search(rf"{COMPANY_PROFILE_TITLE}[^\d]{{0,30}}(\d{{1,3}})", page_text)
            if match is None:
                continue
            start_index = int(match.group(1)) - 1
            if 0 <= start_index < len(pages) and COMPANY_PROFILE_TITLE in pages[start_index]:
                return LocatedSection(
                    text=self._collect_section_text(pages, start_index),
                    strategy="table_of_contents",
                )
        return None

    def _collect_section_text(self, pages: list[str], start_index: int) -> str:
        collected: list[str] = []
        for index in range(start_index, min(len(pages), start_index + 6)):
            page_text = pages[index]
            if index != start_index and re.search(r"第[一二三四五六七八九十]+节", page_text):
                break
            collected.append(page_text)
        return "\n".join(collected)

    def _is_table_of_contents_only(self, page_text: str) -> bool:
        return "目录" in page_text and "公司全称" not in page_text and "中文名称" not in page_text

    def _extract_company_full_name(self, section_text: str) -> str | None:
        return self._first_structured_field(
            section_text,
            ["公司全称", "中文名称", "中文全称", "公司中文名称"],
        )

    def _extract_company_short_name(self, section_text: str) -> str | None:
        return self._first_structured_field(
            section_text,
            ["公司简称", "股票简称", "证券简称"],
        )

    def _extract_first_page_company_name(self, first_page: str) -> str | None:
        explicit = self._first_structured_field(first_page, ["公司名称", "公司全称", "中文名称"])
        if explicit:
            return explicit

        lines = [line.strip() for line in first_page.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if "年度报告" in line or "年报" in line:
                for candidate in reversed(lines[:index]):
                    if self._chinese_character_count(candidate) >= 4 and "证券代码" not in candidate:
                        return candidate
                return None
        return None

    def _first_structured_field(self, text: str, labels: list[str]) -> str | None:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            for label in labels:
                if label not in line:
                    continue
                value = line.split(label, 1)[1]
                value = re.sub(r"^[\s:：|｜]+", "", value).strip()
                value = re.split(r"\s{2,}|[|｜]", value, maxsplit=1)[0].strip()
                if value:
                    return value
        return None

    def _extract_stock_identity(self, section_text: str) -> "_StockIdentity | None":
        a_codes: set[str] = set()
        hk_codes: set[str] = set()

        for raw_line in section_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            market = self._stock_line_market(line)
            if market is None:
                continue
            codes = re.findall(r"(?<!\d)(\d{5,6})(?!\d)", line)
            if market == "A":
                a_codes.update(code for code in codes if len(code) == 6)
            elif market == "HK":
                hk_codes.update(code for code in codes if len(code) == 5)
            else:
                a_codes.update(code for code in codes if len(code) == 6)
                hk_codes.update(code for code in codes if len(code) == 5)

        if len(a_codes) > 1:
            raise BusinessError("AMBIGUOUS_STOCK_CODE")
        if len(a_codes) == 1:
            code = next(iter(a_codes))
            return _StockIdentity(
                stock_code=code,
                normalized_stock_code=f"A:{code}",
                exchange="A",
            )
        if len(hk_codes) > 1:
            raise BusinessError("AMBIGUOUS_STOCK_CODE")
        if len(hk_codes) == 1:
            code = next(iter(hk_codes))
            return _StockIdentity(
                stock_code=code,
                normalized_stock_code=f"HK:{code}",
                exchange="HK",
            )
        return None

    def _stock_line_market(self, line: str) -> str | None:
        a_labels = ["A股股票代码", "A 股股票代码", "A股证券代码", "A 股证券代码"]
        hk_labels = ["H股股票代码", "H 股股票代码", "港股股票代码", "香港股票代码", "H股证券代码"]
        generic_labels = ["股票代码", "证券代码"]
        if any(label in line for label in a_labels):
            return "A"
        if any(label in line for label in hk_labels):
            return "HK"
        if any(label in line for label in generic_labels):
            return "GENERIC"
        return None

    def _extract_financial_data_year(self, section_text: str) -> int | None:
        candidate_years: set[int] = set()
        date_markers = ["主要会计数据", "财务指标", "报告期末", "年末", "12月31日", "报告期"]
        for line in section_text.splitlines():
            if not any(marker in line for marker in date_markers):
                continue
            candidate_years.update(int(year) for year in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", line))
        return max(candidate_years) if candidate_years else None

    def _chinese_character_count(self, text: str) -> int:
        return len(re.findall(r"[\u4e00-\u9fff]", text))


@dataclass(frozen=True)
class _StockIdentity:
    stock_code: str
    normalized_stock_code: str
    exchange: str


def normalize_company_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"[\s　·•\-－—_()（）《》【】\[\]:：|｜,.，。]+", "", normalized)
