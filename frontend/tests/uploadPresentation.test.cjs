const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const ts = require("typescript");

function loadTsModule(relativePath) {
  const sourcePath = path.join(__dirname, "..", relativePath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const transpiled = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022
    }
  });
  const module = { exports: {} };
  const requireFromSource = (specifier) => require(require.resolve(specifier, { paths: [path.dirname(sourcePath)] }));
  new Function("require", "module", "exports", transpiled.outputText)(
    requireFromSource,
    module,
    module.exports
  );
  return module.exports;
}

const {
  formatUploadError,
  getFileVersionActions,
  shouldRefreshLibraryAfterUploadError
} = loadTsModule("src/uploadPresentation.ts");

test("file version actions follow display status rules", () => {
  assert.deepEqual(
    getFileVersionActions("not_analyzed").map((action) => action.id),
    ["analyze", "delete"]
  );
  assert.deepEqual(
    getFileVersionActions("analyzing").map((action) => action.id),
    ["stop"]
  );
  assert.deepEqual(
    getFileVersionActions("analyzed").map((action) => action.id),
    ["view_report", "qa", "download", "delete"]
  );
  assert.deepEqual(
    getFileVersionActions("analysis_failed").map((action) => action.id),
    ["retry", "delete"]
  );
  assert.deepEqual(
    getFileVersionActions("stopped").map((action) => action.id),
    ["retry", "delete"]
  );
});

test("duplicate upload feedback points to the existing file version", () => {
  const duplicate = {
    error_code: "DUPLICATE_FILE_VERSION",
    message: "该文件已上传",
    details: {
      annual_report: {
        company_full_name: "贵州茅台酒股份有限公司"
      },
      file_version: {
        original_filename: "moutai-2024.pdf",
        display_status: "analyzed"
      }
    }
  };

  assert.equal(
    formatUploadError(duplicate),
    "该文件已上传：贵州茅台酒股份有限公司 / moutai-2024.pdf（有分析报告）"
  );
  assert.equal(shouldRefreshLibraryAfterUploadError(duplicate), true);
  assert.equal(
    formatUploadError({ error_code: "INVALID_FILE_EXTENSION", message: "仅支持 PDF 文件" }),
    "仅支持 PDF 文件"
  );
  assert.equal(
    shouldRefreshLibraryAfterUploadError({
      error_code: "INVALID_FILE_EXTENSION",
      message: "仅支持 PDF 文件"
    }),
    false
  );
});
