from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session

from backend.app.admission import UploadAdmissionService
from backend.app.errors import BusinessError
from backend.app.persistence import DuplicateActiveFileVersionError, UploadRepository
from backend.app.presenters import to_annual_report_brief_summary, to_file_version_summary
from backend.app.schemas import UploadSuccessResponse


@dataclass(frozen=True)
class AnnualReportUploadIntake:
    admission: UploadAdmissionService
    source_pdf_dir: Path

    def upload(
        self,
        session: Session,
        *,
        filename: str,
        content: bytes,
    ) -> UploadSuccessResponse:
        admitted = self.admission.admit(filename, content)
        content_hash = sha256(content).hexdigest()
        repository = UploadRepository(session, self.source_pdf_dir)
        try:
            annual_report, file_version, already_exists = repository.persist_upload(
                filename=filename,
                content=content,
                content_hash=content_hash,
                admitted=admitted,
            )
        except DuplicateActiveFileVersionError as exc:
            raise BusinessError(
                "DUPLICATE_FILE_VERSION",
                details={
                    "annual_report": to_annual_report_brief_summary(
                        exc.file_version.annual_report
                    ).model_dump(mode="json"),
                    "file_version": to_file_version_summary(exc.file_version).model_dump(
                        mode="json"
                    ),
                },
            ) from exc

        return UploadSuccessResponse(
            annual_report=to_annual_report_brief_summary(annual_report),
            file_version=to_file_version_summary(file_version),
            annual_report_already_exists=already_exists,
        )
