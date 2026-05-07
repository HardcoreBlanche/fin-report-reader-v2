import {
  AlertCircle,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Loader2,
  MessageCircleQuestion,
  PlayCircle,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  Upload
} from "lucide-react";
import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import type { ApiError, FileVersionActionId } from "./uploadPresentation";
import {
  formatDisplayStatus,
  formatUploadError,
  getFileVersionActions,
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
  const [annualReports, setAnnualReports] = useState<AnnualReportSummary[]>([]);
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
    </main>
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
