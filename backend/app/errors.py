from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ErrorSpec:
    error_code: str
    message: str
    status_code: int


ERRORS: dict[str, ErrorSpec] = {
    "INVALID_FILE_EXTENSION": ErrorSpec("INVALID_FILE_EXTENSION", "仅支持 PDF 文件", 400),
    "INVALID_PDF_HEADER": ErrorSpec("INVALID_PDF_HEADER", "文件内容不是有效 PDF", 400),
    "INVALID_PDF_FILE": ErrorSpec("INVALID_PDF_FILE", "PDF 文件无法读取", 400),
    "DUPLICATE_FILE_VERSION": ErrorSpec("DUPLICATE_FILE_VERSION", "该文件已上传", 409),
    "NOT_AN_ANNUAL_REPORT": ErrorSpec("NOT_AN_ANNUAL_REPORT", "当前仅支持年度报告", 422),
    "ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED": ErrorSpec(
        "ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED",
        "当前仅支持完整年度报告，不支持年度报告摘要",
        422,
    ),
    "NON_CHINESE_ANNUAL_REPORT": ErrorSpec(
        "NON_CHINESE_ANNUAL_REPORT",
        "当前仅支持中文年度报告",
        422,
    ),
    "COMPANY_PROFILE_SECTION_NOT_FOUND": ErrorSpec(
        "COMPANY_PROFILE_SECTION_NOT_FOUND",
        "无法定位公司简介和主要财务指标",
        422,
    ),
    "MISSING_STOCK_CODE": ErrorSpec("MISSING_STOCK_CODE", "无法识别股票代码", 422),
    "AMBIGUOUS_STOCK_CODE": ErrorSpec("AMBIGUOUS_STOCK_CODE", "股票代码不唯一", 422),
    "MISSING_REPORT_YEAR": ErrorSpec("MISSING_REPORT_YEAR", "无法识别报告年度", 422),
    "MISSING_COMPANY_FULL_NAME": ErrorSpec(
        "MISSING_COMPANY_FULL_NAME",
        "无法识别公司全称",
        422,
    ),
    "COMPANY_FULL_NAME_MISMATCH": ErrorSpec(
        "COMPANY_FULL_NAME_MISMATCH",
        "首页公司名与公司全称不匹配",
        422,
    ),
    "REPORT_YEAR_MISMATCH": ErrorSpec("REPORT_YEAR_MISMATCH", "报告年度不一致", 422),
    "ANNUAL_REPORT_IDENTITY_CONFLICT": ErrorSpec(
        "ANNUAL_REPORT_IDENTITY_CONFLICT",
        "该股票代码和年度已存在年报，但公司全称不一致",
        422,
    ),
    "TABLE_DATE_EXTRACTION_FAILED": ErrorSpec(
        "TABLE_DATE_EXTRACTION_FAILED",
        "表格提取日期失败",
        422,
    ),
    "FILE_VERSION_NOT_FOUND": ErrorSpec("FILE_VERSION_NOT_FOUND", "文件版本不存在", 404),
    "ANALYSIS_ALREADY_IN_PROGRESS": ErrorSpec(
        "ANALYSIS_ALREADY_IN_PROGRESS",
        "该文件版本已有分析正在进行",
        409,
    ),
    "ANALYSIS_RESULT_ALREADY_EXISTS": ErrorSpec(
        "ANALYSIS_RESULT_ALREADY_EXISTS",
        "该文件版本已有分析报告，请先删除后再重新分析",
        409,
    ),
    "ANALYSIS_RESULT_NOT_FOUND": ErrorSpec(
        "ANALYSIS_RESULT_NOT_FOUND",
        "该文件版本暂无分析报告",
        404,
    ),
    "ANALYSIS_CONCURRENCY_LIMIT_REACHED": ErrorSpec(
        "ANALYSIS_CONCURRENCY_LIMIT_REACHED",
        "当前分析任务较多，请稍后再试",
        429,
    ),
    "MD_A_SECTION_NOT_FOUND": ErrorSpec(
        "MD_A_SECTION_NOT_FOUND",
        "无法定位管理层讨论与分析",
        422,
    ),
    "MD_A_SECTION_START_UNVERIFIED": ErrorSpec(
        "MD_A_SECTION_START_UNVERIFIED",
        "无法验证管理层讨论与分析起始位置",
        422,
    ),
    "MD_A_SECTION_END_NOT_FOUND": ErrorSpec(
        "MD_A_SECTION_END_NOT_FOUND",
        "无法确定管理层讨论与分析结束位置",
        422,
    ),
    "MD_A_TEXT_EXTRACTION_FAILED": ErrorSpec(
        "MD_A_TEXT_EXTRACTION_FAILED",
        "管理层讨论与分析中的文本无法识别",
        422,
    ),
    "ANALYSIS_OUTPUT_NO_VALID_EVIDENCE": ErrorSpec(
        "ANALYSIS_OUTPUT_NO_VALID_EVIDENCE",
        "分析结果缺少可验证证据",
        422,
    ),
    "ANALYSIS_OUTPUT_VALIDATION_FAILED": ErrorSpec(
        "ANALYSIS_OUTPUT_VALIDATION_FAILED",
        "分析结果结构校验失败",
        422,
    ),
    "ANALYSIS_OUTPUT_INVALID_TABLE_REFERENCE": ErrorSpec(
        "ANALYSIS_OUTPUT_INVALID_TABLE_REFERENCE",
        "分析结果引用了不存在的表格",
        422,
    ),
    "ANALYSIS_OUTPUT_INVALID_FIGURE_REFERENCE": ErrorSpec(
        "ANALYSIS_OUTPUT_INVALID_FIGURE_REFERENCE",
        "分析结果引用了不存在的图",
        422,
    ),
    "ANALYSIS_OUTPUT_INVALID_ASSET_REFERENCE": ErrorSpec(
        "ANALYSIS_OUTPUT_INVALID_ASSET_REFERENCE",
        "分析结果引用了不存在的图表资源",
        422,
    ),
}


class BusinessError(Exception):
    def __init__(self, error_code: str, details: dict[str, Any] | None = None):
        self.spec = ERRORS[error_code]
        self.details = details
        super().__init__(self.spec.message)


def error_response_payload(error: BusinessError) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error_code": error.spec.error_code,
        "message": error.spec.message,
    }
    if error.details:
        payload["details"] = error.details
    return payload
