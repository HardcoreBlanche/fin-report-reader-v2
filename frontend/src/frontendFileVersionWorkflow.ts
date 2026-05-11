import { useEffect, useState } from "react";
import type {
  AnalysisResultDownloadFormat,
  ApiError,
  FileVersionActionId
} from "./uploadPresentation";
import {
  analysisResultDownloadUrl,
  formatUploadError,
  shouldAutoOpenAnalysisResult,
  shouldNotifyBackgroundCompletion,
  shouldRefreshLibraryAfterUploadError
} from "./uploadPresentation";

export type FileVersionSummary = {
  id: number;
  original_filename: string;
  display_status: string;
  display_status_message: string | null;
  uploaded_at: string;
};

export type AnnualReportSummary = {
  id: number;
  normalized_stock_code: string;
  report_year: number;
  company_full_name: string;
  company_short_name: string | null;
  summary_status: string;
  file_versions: FileVersionSummary[];
};

export type UploadState =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "success"; message: string }
  | { kind: "error"; error: ApiError; message: string };

export type AnalysisRunSummary = {
  id: number;
  file_version_id: number;
  implementation_id: string;
  status: string;
  stage: string | null;
  stages: string[];
  prompt_version: string | null;
  chroma_collection_name: string;
  error_code: string | null;
  error_message: string | null;
};

export type FileVersionDeleteConfirmation = {
  file_version_id: number;
  annual_report_id: number;
  original_filename: string;
  analysis_result_count: number;
  will_delete_annual_report: boolean;
};

export type AnnualReportDeleteFileVersionPreview = {
  file_version_id: number;
  original_filename: string;
  has_current_analysis_result: boolean;
};

export type AnnualReportDeleteConfirmation = {
  annual_report_id: number;
  file_version_count: number;
  analysis_result_count: number;
  file_versions: AnnualReportDeleteFileVersionPreview[];
};

export type TextSpan = {
  text_span_id: string;
  source_section_id: string;
  page: number;
  page_label: string;
  text: string;
};

export type SourceSection = {
  source_section_id: string;
  title: string;
  text_span_ids: string[];
  table_ids: string[];
  image_ids: string[];
  children: SourceSection[];
};

export type EvidenceItem = {
  content_type: string;
  source_section_id: string;
  text_span_id?: string;
  table_id?: string;
  image_id?: string;
  page_label: string;
  evidence_text: string;
  thumb_url?: string;
  original_url?: string;
};

export type AnalysisPoint = {
  text: string;
  evidence: EvidenceItem[];
};

export type AnalysisSection = {
  title: string;
  points: AnalysisPoint[];
};

export type TableMeta = {
  table_id: string;
  title: string;
  summary: string;
  page: number;
  page_label: string;
  source_section_id: string;
  columns: string[];
  row_count: number;
  notes: string[];
  table_url: string;
};

export type TableAsset = Omit<TableMeta, "row_count" | "table_url"> & {
  rows: Record<string, string>[];
  metadata: Record<string, unknown>;
  source_bbox: number[] | null;
};

export type FigureMeta = {
  image_id: string;
  source_section_id: string;
  page: number;
  page_label: string;
  bbox: number[];
  title: string | null;
  caption: string | null;
  summary: string;
  relevance: string;
  relevance_reason: string | null;
  is_relevant_to_analysis: boolean;
  thumb_url: string;
  original_url: string;
};

export type ReportDetail = {
  file_version_id: number;
  analysis_run_id: number;
  title: string;
  prompt_version: string;
  summary: string[];
  source_sections: SourceSection[];
  text_span_index: Record<string, TextSpan>;
  table_index: Record<string, TableMeta>;
  figure_index: Record<string, FigureMeta>;
  other_figures: FigureMeta[];
  analysis_sections: AnalysisSection[];
  qa_available: boolean;
  qa_unavailable_reason: string | null;
  labels: {
    source_tree: string;
    analysis_report: string;
    qa_index: string;
    evidence_package: string;
  };
};

export type AnalysisState =
  | { kind: "idle" }
  | { kind: "running"; fileVersionId: number; stage: string | null }
  | { kind: "error"; message: string; errorCode: string };

type AnnualReportListResponse = {
  items: AnnualReportSummary[];
};

type UploadSuccessResponse = {
  annual_report_already_exists: boolean;
};

type WorkflowDependencies = {
  fetchImpl?: typeof fetch;
  confirmImpl?: (message?: string) => boolean;
  navigateTo?: (url: string) => void;
};

export function buildFileVersionDeleteConfirmationText(
  confirmation: FileVersionDeleteConfirmation
): string {
  return [
    `将删除文件“${confirmation.original_filename}”。`,
    `分析结果数量：${confirmation.analysis_result_count}。`,
    confirmation.will_delete_annual_report ? "该文件为该年报最后一个文件版本，删除后年报将一并移除。" : "",
    "确认继续？"
  ]
    .filter(Boolean)
    .join("\n");
}

export function buildAnnualReportDeleteConfirmationText(
  report: AnnualReportSummary,
  confirmation: AnnualReportDeleteConfirmation
): string {
  return [
    `将删除年报“${report.company_full_name}（${report.report_year}）”。`,
    `文件版本数量：${confirmation.file_version_count}。`,
    `分析结果数量：${confirmation.analysis_result_count}。`,
    "确认继续？"
  ].join("\n");
}

export function shouldClearCurrentReportAfterAnnualReportDelete(
  currentReport: ReportDetail | null,
  confirmation: AnnualReportDeleteConfirmation
): boolean {
  if (!currentReport) {
    return false;
  }
  return confirmation.file_versions.some(
    (fileVersion) => fileVersion.file_version_id === currentReport.file_version_id
  );
}

export function useFrontendFileVersionWorkflow(
  dependencies: WorkflowDependencies = {}
) {
  const fetchImpl = dependencies.fetchImpl ?? fetch;
  const confirmImpl = dependencies.confirmImpl ?? window.confirm.bind(window);
  const navigateTo =
    dependencies.navigateTo ?? ((url: string) => {
      window.location.href = url;
    });

  const [uploadState, setUploadState] = useState<UploadState>({ kind: "idle" });
  const [analysisState, setAnalysisState] = useState<AnalysisState>({ kind: "idle" });
  const [annualReports, setAnnualReports] = useState<AnnualReportSummary[]>([]);
  const [currentReport, setCurrentReport] = useState<ReportDetail | null>(null);
  const [backgroundNotice, setBackgroundNotice] = useState<string | null>(null);
  const [isLoadingReports, setIsLoadingReports] = useState(false);

  useEffect(() => {
    void loadAnnualReports();
  }, []);

  async function loadAnnualReports() {
    setIsLoadingReports(true);
    try {
      const response = await fetchImpl("/api/annual-reports");
      if (!response.ok) {
        return;
      }
      const body = (await response.json()) as AnnualReportListResponse;
      setAnnualReports(body.items);
    } finally {
      setIsLoadingReports(false);
    }
  }

  function resetUploadState() {
    setUploadState({ kind: "idle" });
  }

  async function uploadAnnualReport(file: File) {
    const formData = new FormData();
    formData.append("file", file);
    setUploadState({ kind: "uploading" });

    const response = await fetchImpl("/api/uploads/annual-reports", {
      method: "POST",
      body: formData
    });
    const body = await response.json();

    if (!response.ok) {
      const error = body as ApiError;
      setUploadState({ kind: "error", error, message: formatUploadError(error) });
      if (shouldRefreshLibraryAfterUploadError(error)) {
        await loadAnnualReports();
      }
      return false;
    }

    const success = body as UploadSuccessResponse;
    setUploadState({
      kind: "success",
      message: success.annual_report_already_exists ? "已添加文件版本" : "已添加年报"
    });
    await loadAnnualReports();
    return true;
  }

  async function runFileVersionAction(
    actionId: FileVersionActionId,
    version: FileVersionSummary
  ) {
    if (actionId === "analyze" || actionId === "retry") {
      await startAnalysis(version);
      return;
    }
    if (actionId === "view_report" || actionId === "qa") {
      await openReport(version.id);
      return;
    }
    if (actionId === "stop") {
      await stopAnalysis(version);
      return;
    }
    if (actionId === "download") {
      downloadAnalysisResult(version.id, "zip");
      return;
    }
    if (actionId === "delete_report") {
      await deleteAnalysisResult(version);
      return;
    }
    if (actionId === "delete_file") {
      await deleteFileVersion(version);
    }
  }

  function downloadAnalysisResult(
    fileVersionId: number,
    format: AnalysisResultDownloadFormat
  ) {
    navigateTo(analysisResultDownloadUrl(fileVersionId, format));
  }

  async function startAnalysis(version: FileVersionSummary) {
    setBackgroundNotice(null);
    setAnalysisState({ kind: "running", fileVersionId: version.id, stage: "locating_section" });
    const response = await fetchImpl(`/api/file-versions/${version.id}/analysis-runs`, {
      method: "POST"
    });
    const body = await response.json();

    if (!response.ok) {
      await handleAnalysisError(body as ApiError);
      return;
    }

    const run = body as AnalysisRunSummary;
    setAnalysisState({ kind: "running", fileVersionId: version.id, stage: run.stage });
    await loadAnnualReports();
    if (shouldAutoOpenAnalysisResult(version.id, run)) {
      await openReport(run.file_version_id);
      setAnalysisState({ kind: "idle" });
      return;
    }
    if (shouldNotifyBackgroundCompletion(version.id, run)) {
      setBackgroundNotice("后台分析已完成");
      setAnalysisState({ kind: "idle" });
    }
  }

  async function openReport(fileVersionId: number) {
    const response = await fetchImpl(`/api/file-versions/${fileVersionId}/analysis-result`);
    const body = await response.json();
    if (!response.ok) {
      setAnalysisState({
        kind: "error",
        message: (body as ApiError).message,
        errorCode: (body as ApiError).error_code
      });
      return;
    }
    setCurrentReport(body as ReportDetail);
  }

  async function stopAnalysis(version: FileVersionSummary) {
    const response = await fetchImpl(`/api/file-versions/${version.id}/analysis-runs/stop`, {
      method: "POST"
    });
    const body = await response.json();
    if (!response.ok) {
      await handleAnalysisError(body as ApiError);
      return;
    }
    setAnalysisState({ kind: "idle" });
    setBackgroundNotice(null);
    await loadAnnualReports();
  }

  async function deleteAnalysisResult(version: FileVersionSummary) {
    const response = await fetchImpl(`/api/file-versions/${version.id}/analysis-result`, {
      method: "DELETE"
    });
    const body = await response.json();
    if (!response.ok) {
      await handleAnalysisError(body as ApiError);
      return;
    }
    if (currentReport?.file_version_id === version.id) {
      setCurrentReport(null);
    }
    setBackgroundNotice("分析报告已删除");
    setAnalysisState({ kind: "idle" });
    await loadAnnualReports();
  }

  async function deleteFileVersion(version: FileVersionSummary) {
    const confirmationResponse = await fetchImpl(
      `/api/file-versions/${version.id}/delete-confirmation`
    );
    const confirmationBody = await confirmationResponse.json();
    if (!confirmationResponse.ok) {
      await handleAnalysisError(confirmationBody as ApiError);
      return;
    }

    const confirmation = confirmationBody as FileVersionDeleteConfirmation;
    if (!confirmImpl(buildFileVersionDeleteConfirmationText(confirmation))) {
      return;
    }

    const response = await fetchImpl(`/api/file-versions/${version.id}?confirm=true`, {
      method: "DELETE"
    });
    const body = await response.json();
    if (!response.ok) {
      await handleAnalysisError(body as ApiError);
      return;
    }

    if (currentReport?.file_version_id === version.id) {
      setCurrentReport(null);
    }
    setBackgroundNotice(
      confirmation.will_delete_annual_report ? "文件版本已删除，空年报已清理" : "文件版本已删除"
    );
    setAnalysisState({ kind: "idle" });
    await loadAnnualReports();
  }

  async function deleteAnnualReport(report: AnnualReportSummary) {
    const confirmationResponse = await fetchImpl(
      `/api/annual-reports/${report.id}/delete-confirmation`
    );
    const confirmationBody = await confirmationResponse.json();
    if (!confirmationResponse.ok) {
      await handleAnalysisError(confirmationBody as ApiError);
      return;
    }

    const confirmation = confirmationBody as AnnualReportDeleteConfirmation;
    if (!confirmImpl(buildAnnualReportDeleteConfirmationText(report, confirmation))) {
      return;
    }

    const response = await fetchImpl(`/api/annual-reports/${report.id}?confirm=true`, {
      method: "DELETE"
    });
    const body = await response.json();
    if (!response.ok) {
      await handleAnalysisError(body as ApiError);
      return;
    }

    if (shouldClearCurrentReportAfterAnnualReportDelete(currentReport, confirmation)) {
      setCurrentReport(null);
    }
    setBackgroundNotice("年报已删除");
    setAnalysisState({ kind: "idle" });
    await loadAnnualReports();
  }

  async function handleAnalysisError(error: ApiError) {
    setAnalysisState({ kind: "error", message: error.message, errorCode: error.error_code });
    await loadAnnualReports();
  }

  return {
    uploadState,
    analysisState,
    annualReports,
    currentReport,
    backgroundNotice,
    isLoadingReports,
    loadAnnualReports,
    resetUploadState,
    uploadAnnualReport,
    runFileVersionAction,
    deleteAnnualReport
  };
}
