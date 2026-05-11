import { useEffect, useState } from "react";
import type {
  FigureMeta,
  ReportDetail,
  TableAsset,
  TableMeta
} from "./frontendFileVersionWorkflow";
import type { ApiError, QaExchange, QaResponse } from "./uploadPresentation";
import { qaSessionMarkdown } from "./uploadPresentation";

type QaState = { kind: "idle" } | { kind: "asking" };

type InteractionErrorScope = "table" | "qa" | "clipboard" | "download";

type InteractionError = {
  scope: InteractionErrorScope;
  message: string;
};

type DownloadAnchor = {
  href: string;
  download: string;
  click: () => void;
};

type AnalysisResultDetailInteractionDependencies = {
  fetchImpl?: typeof fetch;
  writeClipboardText?: (text: string) => Promise<void>;
  createObjectUrl?: (blob: Blob) => string;
  revokeObjectUrl?: (url: string) => void;
  createDownloadAnchor?: () => DownloadAnchor;
};

export type AnalysisResultDetailView = {
  textSpanCount: number;
  tables: TableMeta[];
  figures: FigureMeta[];
};

export function deriveAnalysisResultDetailView(
  report: ReportDetail
): AnalysisResultDetailView {
  return {
    textSpanCount: Object.keys(report.text_span_index).length,
    tables: Object.values(report.table_index),
    figures: Object.values(report.figure_index).filter(
      (figure) => figure.is_relevant_to_analysis
    )
  };
}

export function buildQaSessionDownload(
  fileVersionId: number,
  qaSession: QaExchange[]
): { filename: string; content: string } {
  return {
    filename: `qa-session-${fileVersionId}.md`,
    content: qaSessionMarkdown(qaSession)
  };
}

function toErrorMessage(
  body: unknown,
  fallback: string
): string {
  if (
    typeof body === "object" &&
    body !== null &&
    "message" in body &&
    typeof body.message === "string"
  ) {
    return body.message;
  }
  return fallback;
}

export function useAnalysisResultDetailInteraction(
  report: ReportDetail,
  dependencies: AnalysisResultDetailInteractionDependencies = {}
) {
  const fetchImpl = dependencies.fetchImpl ?? fetch;
  const writeClipboardText =
    dependencies.writeClipboardText ??
    ((text: string) => navigator.clipboard.writeText(text));
  const createObjectUrl =
    dependencies.createObjectUrl ?? ((blob: Blob) => URL.createObjectURL(blob));
  const revokeObjectUrl =
    dependencies.revokeObjectUrl ?? ((url: string) => URL.revokeObjectURL(url));
  const createDownloadAnchor =
    dependencies.createDownloadAnchor ??
    (() => document.createElement("a") as DownloadAnchor);

  const view = deriveAnalysisResultDetailView(report);
  const [loadedTables, setLoadedTables] = useState<Record<string, TableAsset>>({});
  const [loadingTableId, setLoadingTableId] = useState<string | null>(null);
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaSession, setQaSession] = useState<QaExchange[]>([]);
  const [qaState, setQaState] = useState<QaState>({ kind: "idle" });
  const [interactionError, setInteractionError] = useState<InteractionError | null>(
    null
  );

  useEffect(() => {
    setLoadedTables({});
    setLoadingTableId(null);
    setQaQuestion("");
    setQaSession([]);
    setQaState({ kind: "idle" });
    setInteractionError(null);
  }, [report.analysis_run_id]);

  async function toggleTableRows(table: TableMeta) {
    setInteractionError((current) =>
      current?.scope === "table" ? null : current
    );
    if (loadedTables[table.table_id]) {
      setLoadedTables(({ [table.table_id]: _removed, ...rest }) => rest);
      return;
    }

    setLoadingTableId(table.table_id);
    try {
      const response = await fetchImpl(table.table_url);
      const body = await response.json();
      if (!response.ok) {
        setInteractionError({
          scope: "table",
          message: toErrorMessage(body, "表格明细加载失败")
        });
        return;
      }
      setLoadedTables((current) => ({
        ...current,
        [table.table_id]: body as TableAsset
      }));
    } catch {
      setInteractionError({ scope: "table", message: "表格明细加载失败" });
    } finally {
      setLoadingTableId(null);
    }
  }

  async function submitQaQuestion() {
    const question = qaQuestion.trim();
    if (!question) return;

    setQaState({ kind: "asking" });
    setInteractionError((current) =>
      current?.scope === "qa" ||
      current?.scope === "clipboard" ||
      current?.scope === "download"
        ? null
        : current
    );
    try {
      const response = await fetchImpl(
        `/api/file-versions/${report.file_version_id}/analysis-result/qa`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question })
        }
      );
      const body = await response.json();
      if (!response.ok) {
        setInteractionError({
          scope: "qa",
          message: toErrorMessage(body, "问答生成失败")
        });
        return;
      }
      setQaSession((current) => [
        ...current,
        { question, response: body as QaResponse }
      ]);
      setQaQuestion("");
    } catch {
      setInteractionError({ scope: "qa", message: "问答生成失败" });
    } finally {
      setQaState({ kind: "idle" });
    }
  }

  async function copyQaSession() {
    if (qaSession.length === 0) return;
    try {
      await writeClipboardText(qaSessionMarkdown(qaSession));
      setInteractionError((current) =>
        current?.scope === "clipboard" ? null : current
      );
    } catch {
      setInteractionError({
        scope: "clipboard",
        message: "复制问答 Markdown 失败"
      });
    }
  }

  function downloadQaSession() {
    if (qaSession.length === 0) return;

    const download = buildQaSessionDownload(report.file_version_id, qaSession);
    try {
      const blob = new Blob([download.content], {
        type: "text/markdown;charset=utf-8"
      });
      const url = createObjectUrl(blob);
      const anchor = createDownloadAnchor();
      anchor.href = url;
      anchor.download = download.filename;
      anchor.click();
      revokeObjectUrl(url);
      setInteractionError((current) =>
        current?.scope === "download" ? null : current
      );
    } catch {
      setInteractionError({
        scope: "download",
        message: "下载问答 Markdown 失败"
      });
    }
  }

  return {
    ...view,
    loadedTables,
    loadingTableId,
    qaQuestion,
    qaSession,
    qaState,
    interactionError,
    canExportQaSession: qaSession.length > 0,
    setQaQuestion,
    toggleTableRows,
    submitQaQuestion,
    copyQaSession,
    downloadQaSession
  };
}
