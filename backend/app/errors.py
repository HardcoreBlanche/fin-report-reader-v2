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
    "STOP_ANALYSIS_FAILED": ErrorSpec(
        "STOP_ANALYSIS_FAILED",
        "停止分析失败",
        409,
    ),
    "STOP_ANALYSIS_CLEANUP_FAILED": ErrorSpec(
        "STOP_ANALYSIS_CLEANUP_FAILED",
        "停止分析时清理中间结果失败",
        500,
    ),
    "DELETE_ANALYSIS_RESULT_FAILED": ErrorSpec(
        "DELETE_ANALYSIS_RESULT_FAILED",
        "删除分析报告失败",
        500,
    ),
    "DELETE_ANALYSIS_ARTIFACTS_FAILED": ErrorSpec(
        "DELETE_ANALYSIS_ARTIFACTS_FAILED",
        "删除分析产物失败",
        500,
    ),
    "DELETE_CONFIRMATION_REQUIRED": ErrorSpec(
        "DELETE_CONFIRMATION_REQUIRED",
        "删除操作需要确认",
        409,
    ),
    "DELETE_FILE_VERSION_FAILED": ErrorSpec(
        "DELETE_FILE_VERSION_FAILED",
        "删除文件版本失败",
        500,
    ),
    "DELETE_SOURCE_PDF_FAILED": ErrorSpec(
        "DELETE_SOURCE_PDF_FAILED",
        "删除源 PDF 失败",
        500,
    ),
    "DELETE_EMPTY_ANNUAL_REPORT_FAILED": ErrorSpec(
        "DELETE_EMPTY_ANNUAL_REPORT_FAILED",
        "删除空年报失败",
        500,
    ),
    "ANNUAL_REPORT_NOT_FOUND": ErrorSpec(
        "ANNUAL_REPORT_NOT_FOUND",
        "年报不存在",
        404,
    ),
    "ANNUAL_REPORT_HAS_ANALYSIS_IN_PROGRESS": ErrorSpec(
        "ANNUAL_REPORT_HAS_ANALYSIS_IN_PROGRESS",
        "该年报下有文件版本正在分析，请先停止分析",
        409,
    ),
    "DELETE_ANNUAL_REPORT_FAILED": ErrorSpec(
        "DELETE_ANNUAL_REPORT_FAILED",
        "删除年报失败",
        500,
    ),
    "DELETE_ANNUAL_REPORT_FILE_VERSIONS_FAILED": ErrorSpec(
        "DELETE_ANNUAL_REPORT_FILE_VERSIONS_FAILED",
        "删除年报文件版本失败",
        500,
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
    "TABLE_ANALYSIS_FAILED": ErrorSpec(
        "TABLE_ANALYSIS_FAILED",
        "管理层讨论与分析中的表格无法识别",
        422,
    ),
    "TABLE_ASSET_NOT_FOUND": ErrorSpec(
        "TABLE_ASSET_NOT_FOUND",
        "表格资源不存在",
        404,
    ),
    "FIGURE_ASSET_NOT_FOUND": ErrorSpec(
        "FIGURE_ASSET_NOT_FOUND",
        "图表资源不存在",
        404,
    ),
    "VISION_MODEL_UNAVAILABLE": ErrorSpec(
        "VISION_MODEL_UNAVAILABLE",
        "视觉模型不可用，无法分析管理层讨论与分析中的图表",
        422,
    ),
    "CHART_ANALYSIS_FAILED": ErrorSpec(
        "CHART_ANALYSIS_FAILED",
        "管理层讨论与分析中的图表无法识别",
        422,
    ),
    "VISUAL_CONTENT_ANALYSIS_FAILED": ErrorSpec(
        "VISUAL_CONTENT_ANALYSIS_FAILED",
        "管理层讨论与分析中的图表或表格无法识别",
        422,
    ),
    "FIGURE_ASSET_SAVE_FAILED": ErrorSpec(
        "FIGURE_ASSET_SAVE_FAILED",
        "图表资源保存失败",
        500,
    ),
    "REPORT_ASSET_COMMIT_FAILED": ErrorSpec(
        "REPORT_ASSET_COMMIT_FAILED",
        "报告资源保存失败",
        500,
    ),
    "ANALYSIS_RESULT_SAVE_FAILED": ErrorSpec(
        "ANALYSIS_RESULT_SAVE_FAILED",
        "分析报告保存失败",
        500,
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
    "UNSUPPORTED_REPORT_DOWNLOAD_FORMAT": ErrorSpec(
        "UNSUPPORTED_REPORT_DOWNLOAD_FORMAT",
        "不支持的报告下载格式",
        400,
    ),
    "REPORT_MARKDOWN_GENERATION_FAILED": ErrorSpec(
        "REPORT_MARKDOWN_GENERATION_FAILED",
        "分析报告 Markdown 生成失败",
        500,
    ),
    "REPORT_ZIP_GENERATION_FAILED": ErrorSpec(
        "REPORT_ZIP_GENERATION_FAILED",
        "分析报告 ZIP 生成失败",
        500,
    ),
    "EMPTY_QUESTION": ErrorSpec("EMPTY_QUESTION", "问题不能为空", 400),
    "QA_INDEX_UNAVAILABLE": ErrorSpec(
        "QA_INDEX_UNAVAILABLE",
        "问答暂不可用",
        409,
    ),
    "QA_GENERATION_FAILED": ErrorSpec(
        "QA_GENERATION_FAILED",
        "问答生成失败",
        500,
    ),
    "QA_EVIDENCE_VALIDATION_FAILED": ErrorSpec(
        "QA_EVIDENCE_VALIDATION_FAILED",
        "问答证据校验失败",
        500,
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
