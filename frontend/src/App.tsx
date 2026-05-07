import {
  AlertCircle,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Image as ImageIcon,
  Loader2,
  MessageCircleQuestion,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Square,
  Table2,
  Trash2,
  Upload
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import type { ApiError, FileVersionActionId } from "./uploadPresentation";
import {
  formatAnalysisStage,
  formatDisplayStatus,
  formatUploadError,
  getFileVersionActions,
  shouldAutoOpenAnalysisResult,
  shouldNotifyBackgroundCompletion,
  shouldRefreshLibraryAfterUploadError
} from "./uploadPresentation";

type FileVersionSummary = {
  id: number;
  original_filename: string;
  display_status: string;
  display_status_message: string | null;
  uploaded_at: string;
};

type AnnualReportSummary = {
  id: number;
  normalized_stock_code: string;
  report_year: number;
  company_full_name: string;
  company_short_name: string | null;
  summary_status: string;
  file_versions: FileVersionSummary[];
};

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading" }
  | { kind: "success"; message: string }
  | { kind: "error"; error: ApiError; message: string };

type AnalysisRunSummary = {
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

type TextSpan = {
  text_span_id: string;
  source_section_id: string;
  page: number;
  page_label: string;
  text: string;
};

type SourceSection = {
  source_section_id: string;
  title: string;
  text_span_ids: string[];
  table_ids: string[];
  image_ids: string[];
  children: SourceSection[];
};

type EvidenceItem = {
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

type AnalysisPoint = {
  text: string;
  evidence: EvidenceItem[];
};

type AnalysisSection = {
  title: string;
  points: AnalysisPoint[];
};

type TableMeta = {
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

type TableAsset = Omit<TableMeta, "row_count" | "table_url"> & {
  rows: Record<string, string>[];
  metadata: Record<string, unknown>;
  source_bbox: number[] | null;
};

type FigureMeta = {
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

type ReportDetail = {
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

type AnalysisState =
  | { kind: "idle" }
  | { kind: "running"; fileVersionId: number; stage: string | null }
  | { kind: "error"; message: string; errorCode: string };

const actionIcons: Record<FileVersionActionId, typeof PlayCircle> = {
  analyze: PlayCircle,
  view_report: Eye,
  qa: MessageCircleQuestion,
  download: Download,
  stop: Square,
  retry: RotateCcw,
  delete: Trash2
};

export function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadState, setUploadState] = useState<UploadState>({ kind: "idle" });
  const [analysisState, setAnalysisState] = useState<AnalysisState>({ kind: "idle" });
  const [annualReports, setAnnualReports] = useState<AnnualReportSummary[]>([]);
  const [currentReport, setCurrentReport] = useState<ReportDetail | null>(null);
  const [backgroundNotice, setBackgroundNotice] = useState<string | null>(null);
  const [isLoadingReports, setIsLoadingReports] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadAnnualReports();
  }, []);

  async function loadAnnualReports() {
    setIsLoadingReports(true);
    try {
      const response = await fetch("/api/annual-reports");
      if (response.ok) {
        const body = (await response.json()) as { items: AnnualReportSummary[] };
        setAnnualReports(body.items);
      }
    } finally {
      setIsLoadingReports(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
    setUploadState({ kind: "idle" });
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) return;

    const formData = new FormData();
    formData.append("file", selectedFile);
    setUploadState({ kind: "uploading" });

    const response = await fetch("/api/uploads/annual-reports", {
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
      return;
    }

    setUploadState({
      kind: "success",
      message: body.annual_report_already_exists ? "已添加文件版本" : "已添加年报"
    });
    setSelectedFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
    await loadAnnualReports();
  }

  async function onFileVersionAction(actionId: FileVersionActionId, version: FileVersionSummary) {
    if (actionId === "analyze" || actionId === "retry") {
      await startAnalysis(version);
      return;
    }
    if (actionId === "view_report") {
      await openReport(version.id);
      return;
    }
    if (actionId === "stop") {
      await stopAnalysis(version);
      return;
    }
    if (actionId === "delete" && version.display_status === "analyzed") {
      await deleteAnalysisResult(version);
    }
  }

  async function startAnalysis(version: FileVersionSummary) {
    setBackgroundNotice(null);
    setAnalysisState({ kind: "running", fileVersionId: version.id, stage: "locating_section" });
    const response = await fetch(`/api/file-versions/${version.id}/analysis-runs`, {
      method: "POST"
    });
    const body = await response.json();

    if (!response.ok) {
      const error = body as ApiError;
      setAnalysisState({ kind: "error", message: error.message, errorCode: error.error_code });
      await loadAnnualReports();
      return;
    }

    const run = body as AnalysisRunSummary;
    setAnalysisState({ kind: "running", fileVersionId: version.id, stage: run.stage });
    await loadAnnualReports();
    if (shouldAutoOpenAnalysisResult(version.id, run)) {
      await openReport(run.file_version_id);
      setAnalysisState({ kind: "idle" });
    } else if (shouldNotifyBackgroundCompletion(version.id, run)) {
      setBackgroundNotice("后台分析已完成");
      setAnalysisState({ kind: "idle" });
    }
  }

  async function openReport(fileVersionId: number) {
    const response = await fetch(`/api/file-versions/${fileVersionId}/analysis-result`);
    const body = await response.json();
    if (!response.ok) {
      const error = body as ApiError;
      setAnalysisState({ kind: "error", message: error.message, errorCode: error.error_code });
      return;
    }
    setCurrentReport(body as ReportDetail);
  }

  async function stopAnalysis(version: FileVersionSummary) {
    const response = await fetch(`/api/file-versions/${version.id}/analysis-runs/stop`, {
      method: "POST"
    });
    const body = await response.json();
    if (!response.ok) {
      const error = body as ApiError;
      setAnalysisState({ kind: "error", message: error.message, errorCode: error.error_code });
      await loadAnnualReports();
      return;
    }
    setAnalysisState({ kind: "idle" });
    setBackgroundNotice(null);
    await loadAnnualReports();
  }

  async function deleteAnalysisResult(version: FileVersionSummary) {
    const response = await fetch(`/api/file-versions/${version.id}/analysis-result`, {
      method: "DELETE"
    });
    const body = await response.json();
    if (!response.ok) {
      const error = body as ApiError;
      setAnalysisState({ kind: "error", message: error.message, errorCode: error.error_code });
      await loadAnnualReports();
      return;
    }
    if (currentReport?.file_version_id === version.id) {
      setCurrentReport(null);
    }
    setBackgroundNotice("分析报告已删除");
    setAnalysisState({ kind: "idle" });
    await loadAnnualReports();
  }

  return (
    <main className="app-shell">
      <section className="workspace-band">
        <div className="workspace-header">
          <div>
            <h1>年报资料库</h1>
            <p>按公司年报整理上传文件</p>
          </div>
          <button className="icon-button" type="button" onClick={() => void loadAnnualReports()} title="刷新">
            <RefreshCw size={18} aria-hidden="true" />
          </button>
        </div>

        <form className="upload-bar" onSubmit={onSubmit}>
          <input
            ref={fileInputRef}
            className="file-input"
            type="file"
            accept="application/pdf,.pdf"
            onChange={onFileChange}
          />
          <div className="selected-file">
            <FileText size={18} aria-hidden="true" />
            <span>{selectedFile?.name ?? "未选择文件"}</span>
          </div>
          <button className="primary-button" type="submit" disabled={!selectedFile || uploadState.kind === "uploading"}>
            {uploadState.kind === "uploading" ? <Loader2 className="spin" size={18} /> : <Upload size={18} />}
            <span>上传</span>
          </button>
        </form>

        {uploadState.kind === "error" && (
          <div className="status-line error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <strong>{uploadState.message}</strong>
            <code>{uploadState.error.error_code}</code>
          </div>
        )}
        {uploadState.kind === "success" && (
          <div className="status-line success" role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            <strong>{uploadState.message}</strong>
          </div>
        )}
        {analysisState.kind === "running" && (
          <div className="status-line progress" role="status">
            <Loader2 className="spin" size={18} aria-hidden="true" />
            <strong>{formatAnalysisStage(analysisState.stage)}</strong>
          </div>
        )}
        {analysisState.kind === "error" && (
          <div className="status-line error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <strong>{analysisState.message}</strong>
            <code>{analysisState.errorCode}</code>
          </div>
        )}
        {backgroundNotice && (
          <div className="status-line success" role="status">
            <CheckCircle2 size={18} aria-hidden="true" />
            <strong>{backgroundNotice}</strong>
          </div>
        )}
      </section>

      <section className="library-band">
        <div className="section-heading">
          <h2>年报</h2>
          {isLoadingReports && <Loader2 className="spin muted" size={18} aria-hidden="true" />}
        </div>

        <div className="report-grid">
          {annualReports.map((report) => (
            <article className="report-card" key={report.id}>
              <div>
                <h3>{report.company_full_name}</h3>
                <p>{report.company_short_name ?? report.normalized_stock_code}</p>
              </div>
              <div className="report-meta">
                <span>{report.normalized_stock_code}</span>
                <span>{report.report_year}</span>
                <span>{report.summary_status}</span>
              </div>
              <ul>
                {report.file_versions.map((version) => (
                  <li key={version.id}>
                    <div className="file-version-main">
                      <span>{version.original_filename}</span>
                      <small>{formatUploadedAt(version.uploaded_at)}</small>
                    </div>
                    <div className="file-version-state">
                      <small title={version.display_status_message ?? undefined}>
                        {formatDisplayStatus(version.display_status)}
                      </small>
                      <div className="action-toolbar">
                        {getFileVersionActions(version.display_status).map((action) => {
                          const Icon = actionIcons[action.id];
                          return (
                            <button
                              className="mini-icon-button"
                              key={action.id}
                              type="button"
                              title={action.label}
                              aria-label={action.label}
                              onClick={() => void onFileVersionAction(action.id, version)}
                            >
                              <Icon size={15} aria-hidden="true" />
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>

        {!isLoadingReports && annualReports.length === 0 && <p className="empty-state">暂无年报</p>}
      </section>

      {currentReport && <ReportDetailPanel report={currentReport} />}
    </main>
  );
}

function ReportDetailPanel({ report }: { report: ReportDetail }) {
  const textSpanCount = Object.keys(report.text_span_index).length;
  const tables = Object.values(report.table_index);
  const figures = Object.values(report.figure_index).filter((figure) => figure.is_relevant_to_analysis);
  const [loadedTables, setLoadedTables] = useState<Record<string, TableAsset>>({});
  const [loadingTableId, setLoadingTableId] = useState<string | null>(null);

  useEffect(() => {
    setLoadedTables({});
    setLoadingTableId(null);
  }, [report.analysis_run_id]);

  async function toggleTableRows(table: TableMeta) {
    if (loadedTables[table.table_id]) {
      setLoadedTables(({ [table.table_id]: _removed, ...rest }) => rest);
      return;
    }
    setLoadingTableId(table.table_id);
    try {
      const response = await fetch(table.table_url);
      if (!response.ok) return;
      const body = (await response.json()) as TableAsset;
      setLoadedTables((current) => ({ ...current, [table.table_id]: body }));
    } finally {
      setLoadingTableId(null);
    }
  }

  return (
    <section className="report-detail-band">
      <div className="report-detail-header">
        <div>
          <h2>{report.title}</h2>
          <p>{report.prompt_version}</p>
        </div>
        <div className="report-meta">
          <span>{report.labels.analysis_report}</span>
          <span>{report.labels.evidence_package}</span>
          <span>{report.qa_available ? report.labels.qa_index : report.qa_unavailable_reason ?? report.labels.qa_index}</span>
        </div>
      </div>

      <div className="report-detail-layout">
        <aside className="source-tree" aria-label={report.labels.source_tree}>
          <h3>{report.labels.source_tree}</h3>
          {report.source_sections.map((section) => (
            <SourceSectionNode key={section.source_section_id} section={section} />
          ))}
        </aside>

        <article className="analysis-report">
          <h3>{report.labels.analysis_report}</h3>
          <ul className="summary-list">
            {report.summary.map((sentence) => (
              <li key={sentence}>{sentence}</li>
            ))}
          </ul>
          {figures.length > 0 && (
            <FigureEvidencePanel figures={figures} title="图示证据" />
          )}
          {tables.length > 0 && (
            <section className="table-evidence-panel">
              <h4>表格证据</h4>
              <div className="table-summary-list">
                {tables.map((table) => {
                  const loadedTable = loadedTables[table.table_id];
                  return (
                    <div className="table-summary" key={table.table_id}>
                      <div className="table-summary-main">
                        <Table2 size={17} aria-hidden="true" />
                        <div>
                          <strong>{table.title}</strong>
                          <span>
                            {table.summary} · {table.page_label}
                          </span>
                        </div>
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() => void toggleTableRows(table)}
                          disabled={loadingTableId === table.table_id}
                        >
                          {loadingTableId === table.table_id ? <Loader2 className="spin" size={15} /> : <Table2 size={15} />}
                          <span>{loadedTable ? "收起明细" : "加载明细"}</span>
                        </button>
                      </div>
                      {loadedTable && (
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                {loadedTable.columns.map((column) => (
                                  <th key={column}>{column}</th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {loadedTable.rows.map((row, rowIndex) => (
                                <tr key={`${loadedTable.table_id}-${rowIndex}`}>
                                  {loadedTable.columns.map((column) => (
                                    <td key={column}>{row[column]}</td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}
          {report.analysis_sections.map((section) => (
            <section className="analysis-section" key={section.title}>
              <h4>{section.title}</h4>
              {section.points.map((point) => (
                <div className="analysis-point" key={point.text}>
                  <p>{point.text}</p>
                  <div className="evidence-list">
                    {point.evidence.map((evidence) => (
                      <span
                        key={`${evidence.content_type}-${evidence.text_span_id ?? evidence.table_id ?? evidence.image_id}-${evidence.evidence_text}`}
                      >
                        {evidence.page_label} · {evidence.evidence_text}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          ))}
          {report.other_figures.length > 0 && (
            <details className="other-figures-panel">
              <summary>其他图示</summary>
              <FigureEvidencePanel figures={report.other_figures} />
            </details>
          )}
        </article>
      </div>

      <div className="evidence-foot">
        <span>{report.labels.evidence_package}</span>
        <span>{textSpanCount} 条文本证据</span>
        {tables.length > 0 && <span>{tables.length} 张表格证据</span>}
        {Object.keys(report.figure_index).length > 0 && (
          <span>{Object.keys(report.figure_index).length} 张图示证据</span>
        )}
      </div>
    </section>
  );
}

function FigureEvidencePanel({ figures, title }: { figures: FigureMeta[]; title?: string }) {
  return (
    <section className="figure-evidence-panel">
      {title && <h4>{title}</h4>}
      <div className="figure-summary-list">
        {figures.map((figure) => (
          <figure className="figure-summary" key={figure.image_id}>
            <img src={figure.thumb_url} alt={figure.title ?? figure.caption ?? "图示证据"} />
            <figcaption>
              <div className="figure-summary-heading">
                <ImageIcon size={17} aria-hidden="true" />
                <strong>{figure.title ?? figure.caption ?? figure.image_id}</strong>
                <a className="icon-link" href={figure.original_url} target="_blank" rel="noreferrer" title="查看原图">
                  <Eye size={15} aria-hidden="true" />
                </a>
              </div>
              <p>{figure.summary}</p>
              <span>{figure.page_label}</span>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  );
}

function SourceSectionNode({ section }: { section: SourceSection }) {
  const evidenceCount = section.text_span_ids.length + section.table_ids.length + section.image_ids.length;
  return (
    <div className="source-node">
      <span>{section.title}</span>
      <small>{evidenceCount}</small>
      {section.children.map((child) => (
        <SourceSectionNode key={child.source_section_id} section={child} />
      ))}
    </div>
  );
}

function formatUploadedAt(value: string): string {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}
