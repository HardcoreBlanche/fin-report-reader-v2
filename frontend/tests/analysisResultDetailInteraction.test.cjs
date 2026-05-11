const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relativePath) {
  return loadTsModuleFromAbsolute(path.join(__dirname, "..", relativePath));
}

function loadTsModuleFromAbsolute(sourcePath) {
  const source = fs.readFileSync(sourcePath, "utf8");
  const transpiled = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022
    }
  });
  const module = { exports: {} };
  const requireFromSource = (specifier) => {
    if (specifier.startsWith(".")) {
      const candidate = path.resolve(path.dirname(sourcePath), `${specifier}.ts`);
      if (fs.existsSync(candidate)) {
        return loadTsModuleFromAbsolute(candidate);
      }
    }
    return require(require.resolve(specifier, { paths: [path.dirname(sourcePath)] }));
  };
  new Function("require", "module", "exports", transpiled.outputText)(
    requireFromSource,
    module,
    module.exports
  );
  return module.exports;
}

const {
  buildQaSessionDownload,
  deriveAnalysisResultDetailView
} = loadTsModule("src/analysisResultDetailInteraction.ts");

test("deriveAnalysisResultDetailView keeps only analysis-relevant figures and counts text spans", () => {
  const view = deriveAnalysisResultDetailView({
    file_version_id: 8,
    analysis_run_id: 18,
    title: "管理层讨论与分析",
    prompt_version: "report_v1",
    summary: [],
    source_sections: [],
    text_span_index: {
      text_1: { text_span_id: "text_1" },
      text_2: { text_span_id: "text_2" }
    },
    table_index: {
      table_1: {
        table_id: "table_1",
        title: "主要指标",
        summary: "收入增长",
        page: 4,
        page_label: "PDF 第 4 页",
        source_section_id: "section_1",
        columns: ["项目", "数值"],
        row_count: 2,
        notes: [],
        table_url: "/api/file-versions/8/analysis-result/tables/table_1"
      }
    },
    figure_index: {
      figure_1: {
        image_id: "figure_1",
        source_section_id: "section_1",
        page: 5,
        page_label: "PDF 第 5 页",
        bbox: [0, 0, 1, 1],
        title: "市场份额",
        caption: null,
        summary: "市场份额提升。",
        relevance: "high",
        relevance_reason: null,
        is_relevant_to_analysis: true,
        thumb_url: "/thumb-1.png",
        original_url: "/original-1.png"
      },
      figure_2: {
        image_id: "figure_2",
        source_section_id: "section_2",
        page: 6,
        page_label: "PDF 第 6 页",
        bbox: [0, 0, 1, 1],
        title: "装饰图",
        caption: null,
        summary: "不进入分析。",
        relevance: "low",
        relevance_reason: null,
        is_relevant_to_analysis: false,
        thumb_url: "/thumb-2.png",
        original_url: "/original-2.png"
      }
    },
    other_figures: [],
    analysis_sections: [],
    qa_available: true,
    qa_unavailable_reason: null,
    labels: {
      source_tree: "章节结构",
      analysis_report: "分析报告",
      qa_index: "问答索引",
      evidence_package: "证据包"
    }
  });

  assert.equal(view.textSpanCount, 2);
  assert.equal(view.tables.length, 1);
  assert.deepEqual(
    view.figures.map((figure) => figure.image_id),
    ["figure_1"]
  );
});

test("buildQaSessionDownload reuses markdown export and stable filename", () => {
  const download = buildQaSessionDownload(42, [
    {
      question: "收入增长的主要来源是什么？",
      response: {
        status: "answered",
        answer: "核心产品销售稳定，是收入增长的主要来源。",
        evidence: [
          {
            content_type: "text",
            text_span_id: "text_span_2",
            page_label: "PDF 第 4 页",
            evidence_text: "核心产品销售稳定，是收入增长的主要来源。"
          }
        ],
        prompt_version: "qa_answer_v1"
      }
    }
  ]);

  assert.equal(download.filename, "qa-session-42.md");
  assert.equal(
    download.content,
    [
      "# 当前问答",
      "",
      "## Q1 收入增长的主要来源是什么？",
      "",
      "状态：已回答",
      "",
      "核心产品销售稳定，是收入增长的主要来源。",
      "",
      "证据：",
      "",
      "- 文本 `text_span_2`（PDF 第 4 页）：核心产品销售稳定，是收入增长的主要来源。",
      ""
    ].join("\n")
  );
});
