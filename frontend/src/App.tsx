import {
  AlertCircle,
  CheckCircle2,
  Copy,
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
import { ChangeEvent, FormEvent, useRef, useState } from "react";
import { useAnalysisResultDetailInteraction } from "./analysisResultDetailInteraction";
import type { FigureMeta, ReportDetail, SourceSection } from "./frontendFileVersionWorkflow";
import { useFrontendFileVersionWorkflow } from "./frontendFileVersionWorkflow";
import type { FileVersionActionId } from "./uploadPresentation";
import {
  analysisResultDownloadUrl,
  formatAnalysisStage,
  formatDisplayStatus,
  formatQaStatus,
  getFileVersionActions,
  qaEvidenceReference
} from "./uploadPresentation";

const actionIcons: Record<FileVersionActionId, typeof PlayCircle> = {
  analyze: PlayCircle,
  view_report: Eye,
  qa: MessageCircleQuestion,
  download: Download,
  stop: Square,
  retry: RotateCcw,
  delete_report: Trash2,
  delete_file: Trash2
};

export function App() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const {
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
  } = useFrontendFileVersionWorkflow();

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setSelectedFile(event.target.files?.[0] ?? null);
    resetUploadState();
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedFile) return;
    const uploaded = await uploadAnnualReport(selectedFile);
    if (!uploaded) {
      return;
    }

    setSelectedFile(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
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
              <div className="report-card-header">
                <div>
                  <h3>{report.company_full_name}</h3>
                  <p>{report.company_short_name ?? report.normalized_stock_code}</p>
                </div>
                <button
                  className="mini-icon-button"
                  type="button"
                  title="删除年报"
                  aria-label="删除年报"
                  onClick={() => void deleteAnnualReport(report)}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </button>
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
                              onClick={() => void runFileVersionAction(action.id, version)}
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
  const {
    textSpanCount,
    tables,
    figures,
    loadedTables,
    loadingTableId,
    qaQuestion,
    qaSession,
    qaState,
    interactionError,
    canExportQaSession,
    setQaQuestion,
    toggleTableRows,
    submitQaQuestion,
    copyQaSession,
    downloadQaSession
  } = useAnalysisResultDetailInteraction(report);

  return (
    <section className="report-detail-band">
      <div className="report-detail-header">
        <div>
          <h2>{report.title}</h2>
          <p>{report.prompt_version}</p>
        </div>
        <div className="report-detail-actions">
          <div className="report-meta">
            <span>{report.labels.analysis_report}</span>
            <span>{report.labels.evidence_package}</span>
            <span>{report.qa_available ? report.labels.qa_index : report.qa_unavailable_reason ?? report.labels.qa_index}</span>
          </div>
          <div className="download-actions">
            <a
              className="icon-button"
              href={analysisResultDownloadUrl(report.file_version_id, "markdown")}
              title="下载 Markdown"
              aria-label="下载 Markdown"
            >
              <FileText size={18} aria-hidden="true" />
            </a>
            <a
              className="icon-button"
              href={analysisResultDownloadUrl(report.file_version_id, "zip")}
              title="下载 ZIP"
              aria-label="下载 ZIP"
            >
              <Download size={18} aria-hidden="true" />
            </a>
          </div>
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
              {interactionError?.scope === "table" && (
                <div className="qa-error" role="alert">
                  <AlertCircle size={16} aria-hidden="true" />
                  <span>{interactionError.message}</span>
                </div>
              )}
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
          <section className="qa-panel">
            <div className="qa-heading">
              <h4>{report.labels.qa_index}</h4>
              <div className="qa-actions">
                <button
                  className="icon-button"
                  type="button"
                  onClick={() => void copyQaSession()}
                  disabled={!canExportQaSession}
                  title="复制 Markdown"
                  aria-label="复制 Markdown"
                >
                  <Copy size={18} aria-hidden="true" />
                </button>
                <button
                  className="icon-button"
                  type="button"
                  onClick={downloadQaSession}
                  disabled={!canExportQaSession}
                  title="下载 Markdown"
                  aria-label="下载 Markdown"
                >
                  <Download size={18} aria-hidden="true" />
                </button>
              </div>
            </div>
            {!report.qa_available && (
              <div className="qa-unavailable" role="status">
                {report.qa_unavailable_reason ?? "问答暂不可用"}
              </div>
            )}
            {qaSession.length > 0 && (
              <div className="qa-session">
                {qaSession.map((exchange, index) => (
                  <div className="qa-exchange" key={`${exchange.question}-${index}`}>
                    <div className="qa-question">
                      <MessageCircleQuestion size={17} aria-hidden="true" />
                      <strong>{exchange.question}</strong>
                      <span>{formatQaStatus(exchange.response.status)}</span>
                    </div>
                    <p>{exchange.response.answer}</p>
                    {exchange.response.evidence.length > 0 && (
                      <div className="qa-evidence-list">
                        {exchange.response.evidence.map((evidence) => (
                          <span key={qaEvidenceReference(evidence)}>{qaEvidenceReference(evidence)}</span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
            <form
              className="qa-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void submitQaQuestion();
              }}
            >
              <textarea
                value={qaQuestion}
                onChange={(event) => setQaQuestion(event.target.value)}
                rows={3}
                placeholder={report.qa_available ? "输入问题" : "问答暂不可用"}
                disabled={!report.qa_available || qaState.kind === "asking"}
              />
              <button
                className="primary-button"
                type="submit"
                disabled={!report.qa_available || !qaQuestion.trim() || qaState.kind === "asking"}
              >
                {qaState.kind === "asking" ? <Loader2 className="spin" size={18} /> : <MessageCircleQuestion size={18} />}
                <span>提问</span>
              </button>
            </form>
            {interactionError &&
              (interactionError.scope === "qa" ||
                interactionError.scope === "clipboard" ||
                interactionError.scope === "download") && (
              <div className="qa-error" role="alert">
                <AlertCircle size={16} aria-hidden="true" />
                <span>{interactionError.message}</span>
              </div>
            )}
          </section>
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
