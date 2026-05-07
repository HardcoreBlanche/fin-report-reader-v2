export type DisplayStatus =
  | "not_analyzed"
  | "analyzing"
  | "analyzed"
  | "analysis_failed"
  | "stopped";

export type FileVersionActionId =
  | "analyze"
  | "view_report"
  | "qa"
  | "download"
  | "stop"
  | "retry"
  | "delete";

export type FileVersionAction = {
  id: FileVersionActionId;
  label: string;
};

export type AnalysisRunLike = {
  file_version_id: number;
  status: string;
};

export type ApiError = {
  error_code: string;
  message: string;
  details?: {
    annual_report?: {
      company_full_name?: string;
    };
    file_version?: {
      original_filename?: string;
      display_status?: DisplayStatus | string;
    };
  };
};

const displayStatusLabels: Record<DisplayStatus, string> = {
  not_analyzed: "未分析",
  analyzing: "分析中",
  analyzed: "有分析报告",
  analysis_failed: "分析失败",
  stopped: "已停止"
};

const actionRules: Record<DisplayStatus, FileVersionAction[]> = {
  not_analyzed: [
    { id: "analyze", label: "分析管理层讨论与分析" },
    { id: "delete", label: "删除文件" }
  ],
  analyzing: [{ id: "stop", label: "停止分析" }],
  analyzed: [
    { id: "view_report", label: "查看分析报告" },
    { id: "qa", label: "问答索引" },
    { id: "download", label: "下载分析报告" },
    { id: "delete", label: "删除文件" }
  ],
  analysis_failed: [
    { id: "retry", label: "重试分析" },
    { id: "delete", label: "删除文件" }
  ],
  stopped: [
    { id: "retry", label: "重试分析" },
    { id: "delete", label: "删除文件" }
  ]
};

const analysisStageLabels: Record<string, string> = {
  locating_section: "定位管理层讨论与分析",
  extracting_content: "提取证据包",
  analyzing_figures: "分析图表",
  generating_report: "生成分析报告",
  building_qa_index: "构建问答索引",
  completed: "完成"
};

export function getFileVersionActions(status: string): FileVersionAction[] {
  return actionRules[toDisplayStatus(status)];
}

export function formatDisplayStatus(status: string): string {
  return displayStatusLabels[toDisplayStatus(status)];
}

export function formatUploadError(error: ApiError): string {
  if (error.error_code !== "DUPLICATE_FILE_VERSION") {
    return error.message;
  }

  const annualReportName = error.details?.annual_report?.company_full_name;
  const filename = error.details?.file_version?.original_filename;
  const status = error.details?.file_version?.display_status;
  if (!annualReportName || !filename) {
    return error.message;
  }

  return `${error.message}：${annualReportName} / ${filename}（${formatDuplicateStatus(status)}）`;
}

export function shouldRefreshLibraryAfterUploadError(error: ApiError): boolean {
  return error.error_code === "DUPLICATE_FILE_VERSION";
}

export function formatAnalysisStage(stage: string | null | undefined): string {
  return analysisStageLabels[stage ?? ""] ?? "准备分析";
}

export function shouldAutoOpenAnalysisResult(
  foregroundFileVersionId: number | null,
  run: AnalysisRunLike
): boolean {
  return foregroundFileVersionId === run.file_version_id && run.status === "ready";
}

export function shouldNotifyBackgroundCompletion(
  foregroundFileVersionId: number | null,
  run: AnalysisRunLike
): boolean {
  return foregroundFileVersionId !== run.file_version_id && run.status === "ready";
}

function formatDuplicateStatus(status: string | undefined): string {
  if (status === "analyzed") return "有分析报告";
  return formatDisplayStatus(status ?? "not_analyzed");
}

function toDisplayStatus(status: string): DisplayStatus {
  if (
    status === "not_analyzed" ||
    status === "analyzing" ||
    status === "analyzed" ||
    status === "analysis_failed" ||
    status === "stopped"
  ) {
    return status;
  }
  return "not_analyzed";
}
