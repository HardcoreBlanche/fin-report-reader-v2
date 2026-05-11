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
  buildAnnualReportDeleteConfirmationText,
  buildFileVersionDeleteConfirmationText,
  shouldClearCurrentReportAfterAnnualReportDelete
} = loadTsModule("src/frontendFileVersionWorkflow.ts");

test("file version delete confirmation text includes empty-report warning only when needed", () => {
  assert.equal(
    buildFileVersionDeleteConfirmationText({
      file_version_id: 5,
      annual_report_id: 2,
      original_filename: "moutai-2024.pdf",
      analysis_result_count: 1,
      will_delete_annual_report: true
    }),
    [
      "将删除文件“moutai-2024.pdf”。",
      "分析结果数量：1。",
      "该文件为该年报最后一个文件版本，删除后年报将一并移除。",
      "确认继续？"
    ].join("\n")
  );

  assert.equal(
    buildFileVersionDeleteConfirmationText({
      file_version_id: 6,
      annual_report_id: 2,
      original_filename: "moutai-2024-v2.pdf",
      analysis_result_count: 0,
      will_delete_annual_report: false
    }),
    ["将删除文件“moutai-2024-v2.pdf”。", "分析结果数量：0。", "确认继续？"].join("\n")
  );
});

test("annual report delete confirmation text stays tied to report identity", () => {
  assert.equal(
    buildAnnualReportDeleteConfirmationText(
      {
        id: 2,
        normalized_stock_code: "A:600519",
        report_year: 2024,
        company_full_name: "贵州茅台酒股份有限公司",
        company_short_name: "贵州茅台",
        summary_status: "有报告",
        file_versions: []
      },
      {
        annual_report_id: 2,
        file_version_count: 3,
        analysis_result_count: 2,
        file_versions: []
      }
    ),
    [
      "将删除年报“贵州茅台酒股份有限公司（2024）”。",
      "文件版本数量：3。",
      "分析结果数量：2。",
      "确认继续？"
    ].join("\n")
  );
});

test("current report cleanup follows deleted annual report ownership", () => {
  const currentReport = {
    file_version_id: 11,
    analysis_run_id: 21,
    title: "管理层讨论与分析",
    prompt_version: "report_v1",
    summary: [],
    source_sections: [],
    text_span_index: {},
    table_index: {},
    figure_index: {},
    other_figures: [],
    analysis_sections: [],
    qa_available: true,
    qa_unavailable_reason: null,
    labels: {
      source_tree: "source",
      analysis_report: "report",
      qa_index: "qa",
      evidence_package: "evidence"
    }
  };

  assert.equal(
    shouldClearCurrentReportAfterAnnualReportDelete(currentReport, {
      annual_report_id: 2,
      file_version_count: 2,
      analysis_result_count: 1,
      file_versions: [
        { file_version_id: 11, original_filename: "moutai-2024.pdf", has_current_analysis_result: true }
      ]
    }),
    true
  );

  assert.equal(
    shouldClearCurrentReportAfterAnnualReportDelete(currentReport, {
      annual_report_id: 3,
      file_version_count: 1,
      analysis_result_count: 0,
      file_versions: [
        { file_version_id: 19, original_filename: "other.pdf", has_current_analysis_result: false }
      ]
    }),
    false
  );
});
