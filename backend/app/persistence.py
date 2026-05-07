from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from backend.app.admission import AcceptedAnnualReportSource, normalize_company_name
from backend.app.errors import BusinessError
from backend.app.models import ActiveContentHash, AnnualReport, Base, FileVersion


class DuplicateActiveFileVersionError(Exception):
    def __init__(self, file_version: FileVersion):
        self.file_version = file_version
        super().__init__("DUPLICATE_FILE_VERSION")


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    database_path = make_url(database_url).database
    if database_url.startswith("sqlite") and database_path and database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


class UploadRepository:
    def __init__(self, session: Session, source_pdf_dir: Path):
        self.session = session
        self.source_pdf_dir = source_pdf_dir

    def persist_upload(
        self,
        *,
        filename: str,
        content: bytes,
        content_hash: str,
        admitted: AcceptedAnnualReportSource,
    ) -> tuple[AnnualReport, FileVersion, bool]:
        duplicate = self.session.scalar(
            select(ActiveContentHash).where(ActiveContentHash.content_hash == content_hash)
        )
        if duplicate is not None:
            file_version = duplicate.file_version
            _ = file_version.annual_report
            raise DuplicateActiveFileVersionError(file_version)

        annual_report = self.session.scalar(
            select(AnnualReport).where(
                AnnualReport.normalized_stock_code == admitted.normalized_stock_code,
                AnnualReport.report_year == admitted.report_year,
            )
        )
        annual_report_already_exists = annual_report is not None
        if annual_report is not None and (
            normalize_company_name(annual_report.company_full_name)
            != normalize_company_name(admitted.company_full_name)
        ):
            raise BusinessError("ANNUAL_REPORT_IDENTITY_CONFLICT")

        if annual_report is None:
            annual_report = AnnualReport(
                stock_code=admitted.stock_code,
                normalized_stock_code=admitted.normalized_stock_code,
                exchange=admitted.exchange,
                report_year=admitted.report_year,
                company_full_name=admitted.company_full_name,
                company_short_name=admitted.company_short_name,
            )
            self.session.add(annual_report)
            self.session.flush()

        file_version = FileVersion(
            annual_report_id=annual_report.id,
            original_filename=filename,
            content_hash=content_hash,
            storage_path="pending",
        )
        self.session.add(file_version)
        self.session.flush()

        self.source_pdf_dir.mkdir(parents=True, exist_ok=True)
        storage_path = self.source_pdf_dir / f"{file_version.id}-{content_hash[:12]}.pdf"
        storage_path.write_bytes(content)
        file_version.storage_path = str(storage_path)
        self.session.add(
            ActiveContentHash(content_hash=content_hash, file_version_id=file_version.id)
        )
        self.session.commit()
        return annual_report, file_version, annual_report_already_exists

    def list_annual_reports(self) -> list[AnnualReport]:
        return list(
            self.session.scalars(
                select(AnnualReport).order_by(AnnualReport.report_year.desc(), AnnualReport.id)
            )
        )
