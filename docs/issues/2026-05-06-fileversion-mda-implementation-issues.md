# Implementation Issues: FileVersion and MDA Analysis

Source PRD: #1 (`docs/prd/2026-05-06-fileversion-mda-analysis-prd.md`)

Architecture source: `docs/adr/0001-annual-report-file-version-mda-analysis.md`

Domain source: `CONTEXT.md`

Label for all issues: `needs-triage`

These issues are ordered as tracer-bullet slices. Each AFK issue should deliver a user-verifiable path through persistence, API behavior, frontend behavior where applicable, and deterministic tests. Do not add a separate horizontal "tests only" issue; add or update the relevant tests inside the issue that changes behavior.

## 1. Reject unsupported uploads before persistence

Type: AFK

User stories covered: 1-10, 75-76, 93

## Parent

#1

## What to build

Implement upload admission for AnnualReportSource candidates so unsupported PDFs fail before any visible AnnualReport or FileVersion is created. The upload API and UI should return stable Chinese reasons for invalid format, unsupported report type, language, missing identity fields, and consistency failures, using only allowed PDF body evidence.

## Acceptance criteria

- [ ] Invalid extension, invalid PDF header, and unreadable PDF return HTTP 400 with `error_code`, `message`, and safe optional `details`.
- [ ] Valid PDFs that fail annual-report admission return HTTP 422 with the specific business error code and Chinese message from `CONTEXT.md`.
- [ ] Annual-report summaries, quarterly/semiannual reports, non-Chinese reports, missing StockCode, ambiguous StockCode, missing ReportYear, missing CompanyFullName, company-name mismatch, report-year mismatch, and company-profile section location failure are rejected.
- [ ] Upload admission uses the first page and the `公司简介和主要财务指标` section, with table-of-contents location first and heading-search fallback.
- [ ] StockCode, CompanyFullName, optional CompanyShortName, and ReportYear come from structured annual-report body evidence; filenames, headers, arbitrary code-like text, fuzzy company-name matching, and publication/upload dates are not accepted as identity sources.
- [ ] NormalizedStockCode is generated with market semantics, and A-share StockCode is preferred when multiple supported codes are present.
- [ ] Rejected AnnualReportSource candidates do not leave visible AnnualReport, FileVersion, source PDF, or active content-hash records.
- [ ] Automated tests cover the upload error contract, identity extraction, company-name normalization, year cross-checking, annual-report summary rejection, and no-persistence behavior with fixtures or mocks.

## Blocked by

None - can start immediately

## 2. Create AnnualReport-first library and duplicate FileVersion upload

Type: AFK

User stories covered: 11-19, 75, 77-78, 93

## Parent

#1

## What to build

Persist accepted PDFs as FileVersions under the AnnualReport identified by NormalizedStockCode and ReportYear, then expose AnnualReport-first browsing, FileVersion selection, duplicate upload handling, and display-state-driven actions.

## Acceptance criteria

- [ ] AnnualReport identity is exactly `NormalizedStockCode + ReportYear`; Exchange is stored only as optional metadata and does not participate in identity.
- [ ] Successful upload returns HTTP 201 with separate AnnualReport and FileVersion summaries.
- [ ] Uploading different PDF content for an existing AnnualReport creates a new FileVersion and returns `annual_report_already_exists=true`.
- [ ] AnnualReports list by CompanyFullName with optional CompanyShortName and visible NormalizedStockCode; same CompanyFullName and ReportYear with different NormalizedStockCode values display as separate AnnualReports.
- [ ] FileVersions display original filename and upload time without user-visible version numbers.
- [ ] Uploading content matching an active FileVersion returns HTTP 409 with `DUPLICATE_FILE_VERSION`, message `该文件已上传`, and existing AnnualReport and FileVersion summaries including display status.
- [ ] Deleted content uploaded later passes admission and creates a new FileVersion instead of restoring the old active record.
- [ ] AnnualReport summary status follows the priority rules in `CONTEXT.md`, and FileVersion display status is inferred from current AnalysisResult first and latest AnalysisRun second.
- [ ] A ready AnalysisRun without an accessible current AnalysisResult is treated as failed with `分析结果缺失`.
- [ ] Frontend actions for analyze, report view, QA, download, stop, retry, and delete are shown only when valid for the FileVersion display state.
- [ ] Automated tests cover AnnualReport grouping, duplicate FileVersion decisions, deleted-content re-upload, summary-status inference, display status inference, and duplicate upload UI handling.

## Blocked by

- Issue 1

## 3. Analyze a text-only MDA FileVersion into an evidence-backed report

Type: AFK

User stories covered: 20-24, 37-42, 51-61, 77-78, 84, 89-93

## Parent

#1

## What to build

For a FileVersion whose ManagementDiscussionAnalysisSection contains only text evidence, start an auditable AnalysisRun, locate the section, build the current EvidencePackage, generate a validated AnalysisResult, and render the interactive report detail. This is the first complete analysis path and should not rely on legacy full-PDF overview, hard-rule, financial-extraction, or Markdown-first report behavior.

## Acceptance criteria

- [ ] Starting analysis creates one AnalysisRun bound to one FileVersion and rejects concurrent starts for the same FileVersion.
- [ ] New AnalysisRuns use coarse statuses `parsing`, `generating`, `ready`, `failed`, `stopped`, and `result_deleted`; new runs do not use `uploaded`.
- [ ] User-visible stages include `locating_section`, `extracting_content`, `analyzing_figures`, `generating_report`, `building_qa_index`, and `completed`.
- [ ] Different FileVersions can analyze concurrently when capacity allows, and the product-level concurrency limit returns HTTP 429 with `ANALYSIS_CONCURRENCY_LIMIT_REACHED` and optional `Retry-After`.
- [ ] Chroma collections and temporary run resources are named by the AnalysisRun implementation id.
- [ ] The ManagementDiscussionAnalysisSection range is located from `第三节 管理层讨论与分析` to before the next same-level section; table-of-contents evidence is verified against body pages when used.
- [ ] Section-location failures return `MD_A_SECTION_NOT_FOUND`, `MD_A_SECTION_START_UNVERIFIED`, or `MD_A_SECTION_END_NOT_FOUND`; MDA text extraction failure returns `MD_A_TEXT_EXTRACTION_FAILED`.
- [ ] The current EvidencePackage owns source_sections, text spans, and section-location evidence; locator evidence is kept separate from analysis and QA evidence.
- [ ] Text evidence uses stable-within-result `text_span_id` values and physical PDF page references displayed as `PDF 第 N 页`.
- [ ] AnalysisResult stores validated structured JSON with a 3 to 5 sentence MDA-only summary, source_sections projection, analysis_sections, evidence-backed points, and prompt version such as `mda_outline_v1`.
- [ ] Recommended themes are used only when supported by evidence; unsupported themes are skipped rather than shown as not disclosed.
- [ ] Backend validation drops evidence-free points and empty sections; no valid evidence-backed points fails the run with `ANALYSIS_OUTPUT_NO_VALID_EVIDENCE`.
- [ ] Invalid model output is retried once with validation errors and then fails with the correct schema or invalid-asset error code.
- [ ] Report detail responses are optimized for interactive rendering, include the source section tree and text-span index, and do not return one large Markdown report.
- [ ] The frontend shows progress, uses user-facing labels such as `管理层讨论与分析`, `章节结构`, `分析报告`, `问答索引`, and `证据包`, auto-opens the foreground analysis result, and only notifies for unrelated background completions.
- [ ] Automated tests cover AnalysisRun creation, status/stage transitions, section-location success and failure, EvidencePackage ownership, structured outline validation, current-result status inference, report auto-open behavior, and mocked LLM/PDF extraction orchestration.

## Blocked by

- Issue 2

## 4. Stop, retry, and re-analysis guardrails

Type: AFK

User stories covered: 25-31

## Parent

#1

## What to build

Support stopping an in-progress AnalysisRun, retrying failed or stopped FileVersions, and preventing accidental overwrite of an existing current AnalysisResult.

## Acceptance criteria

- [ ] Stop marks the current AnalysisRun as `stopped` and displays user cancellation separately from system failure.
- [ ] Stop prevents further PDF extraction, embedding, visual-model, and LLM calls for that run.
- [ ] Stop cleans pages, chunks, Chroma data, temporary report output, and figure assets already created by that run.
- [ ] Stop failures use `STOP_ANALYSIS_FAILED`, and cleanup failures use `STOP_ANALYSIS_CLEANUP_FAILED`.
- [ ] Failed and stopped FileVersions can be analyzed again directly, creating a new AnalysisRun while retaining historical runs.
- [ ] A FileVersion with a current AnalysisResult cannot be re-analyzed until the user explicitly deletes that AnalysisResult.
- [ ] Deleting an AnalysisResult removes generated artifacts, keeps AnnualReport and FileVersion, retains the historical AnalysisRun, and marks it `result_deleted`.
- [ ] Automated tests cover cancellation checkpoints, cleanup behavior, stopped display state, retry after stopped/failed runs, and the re-analysis guard.

## Blocked by

- Issue 3

## 5. Add structured table evidence to the MDA analysis path

Type: AFK

User stories covered: 43-45, 63, 80, 89

## Parent

#1

## What to build

Extend the MDA analysis path for FileVersions whose ManagementDiscussionAnalysisSection contains tables. Structured table evidence should flow from extraction through EvidencePackage ownership, structured outline validation, report rendering, table asset access, and QA indexing preparation.

## Acceptance criteria

- [ ] Tables inside the ManagementDiscussionAnalysisSection are parsed into structured metadata, columns, rows, notes, and physical PDF page references.
- [ ] Table evidence uses EvidencePackage-owned `table_id` values and is linked to source_sections and analysis points.
- [ ] MDA table parsing failure fails the AnalysisRun with `TABLE_ANALYSIS_FAILED`; combined table/figure failures can use `VISUAL_CONTENT_ANALYSIS_FAILED` when both apply.
- [ ] The model can use structured table content as evidence, and validation rejects nonexistent table references.
- [ ] Report detail shows table names and summaries first, with full structured rows loaded on demand.
- [ ] The controlled table asset API verifies the table belongs to the FileVersion's current AnalysisResult before returning data.
- [ ] QA indexing preparation includes structured table content with FileVersion, AnalysisRun, subsection, page, and content-type metadata.
- [ ] Automated tests cover table extraction fixtures, failure mapping, table evidence validation, controlled table access, and report rendering with large tables.

## Blocked by

- Issue 3

## 6. Add controlled figure evidence to the MDA analysis path

Type: AFK

User stories covered: 46-50, 62, 82-83, 89

## Parent

#1

## What to build

Extend the MDA analysis path for FileVersions whose ManagementDiscussionAnalysisSection contains figures. Figure evidence should flow from detection through controlled assets, visual-model summaries, relevance classification, structured outline validation, report rendering, and cleanup.

## Acceptance criteria

- [ ] Figure detection excludes logos, watermarks, headers, footers, backgrounds, tiny decorative icons, and repeated non-body assets before visual-model classification.
- [ ] Informational figures are cropped and stored with `image_id`, physical PDF page, bbox, optional title/caption, original image, and thumbnail metadata.
- [ ] Visual-model availability is required only when MDA figures requiring visual analysis are present; missing availability returns `VISION_MODEL_UNAVAILABLE`.
- [ ] Figure failures use the specified figure, chart, visual-content, and asset persistence error codes from `CONTEXT.md`.
- [ ] Figure summaries include business or financial relevance, and low-relevance figures are retained in collapsed `其他图示` areas without being used as main analysis evidence.
- [ ] Figure evidence in structured_outline uses `content_type=figure_summary`, EvidencePackage-owned image ids, page references, and short evidence text.
- [ ] Report detail shows figure images by default at fitted size with summaries and controlled thumb/original URLs; thumbnail generation failure does not fail analysis when the original asset is available.
- [ ] Asset commit order prepares temporary assets, promotes official assets, saves AnalysisResult references, and marks the run ready only after result persistence succeeds; rollback cleans promoted assets and indexes on failure.
- [ ] Automated tests cover detection filtering, visual-model unavailable behavior, invalid figure reference validation, asset promotion/rollback, controlled figure access, and low-relevance figure rendering.

## Blocked by

- Issue 3

## 7. Download the current AnalysisResult as Markdown and ZIP

Type: AFK

User stories covered: 64-66

## Parent

#1

## What to build

Generate Markdown and ZIP downloads from the validated AnalysisResult and current EvidencePackage, including figure and table assets where available.

## Acceptance criteria

- [ ] Backend downloads render from validated AnalysisResult structure, not from legacy full-report Markdown.
- [ ] Markdown includes the MDA summary, analysis sections, concise evidence lists after points, physical page references, and no non-MDA claims.
- [ ] Markdown keeps figure references and warns that ZIP is needed for complete offline image retention.
- [ ] Markdown includes table names, summaries, page references, and a reminder that ZIP is needed for complete table data.
- [ ] ZIP includes Markdown, original cropped figure assets, and `tables/{table_id}.json` for structured table data; CSV exports may be included where supported.
- [ ] Download asset paths are relative inside ZIP and reuse current EvidencePackage ids.
- [ ] Unsupported format and generation failures return `UNSUPPORTED_REPORT_DOWNLOAD_FORMAT`, `REPORT_ZIP_GENERATION_FAILED`, or `REPORT_MARKDOWN_GENERATION_FAILED`.
- [ ] Automated tests cover text-only, table-backed, and figure-backed downloads, ownership validation, ZIP contents, and download error mapping.

## Blocked by

- Issue 3
- Issue 5
- Issue 6

## 8. Answer QA only from current AnalysisResult evidence

Type: AFK

User stories covered: 67-74, 79-81, 89-90

## Parent

#1

## What to build

Constrain QA to analyzed FileVersions with a current AnalysisResult. QA indexing and answers must use only ManagementDiscussionAnalysisSection evidence from the current EvidencePackage, and every substantive answer must validate against current evidence ids.

## Acceptance criteria

- [ ] QA is available only for FileVersions whose display state is `analyzed` and whose current AnalysisResult is accessible.
- [ ] AnalysisResult stores `qa_available` and `qa_unavailable_reason`.
- [ ] QA indexing includes only MDA text spans, structured table content, and figure visual summaries, with metadata scoped to FileVersion and AnalysisRun.
- [ ] Chroma write or embedding failure sets `qa_available=false`, records the reason, and does not fail AnalysisResult creation.
- [ ] If QA index is unavailable, QA returns `QA_INDEX_UNAVAILABLE` with `问答暂不可用` and does not change AnalysisResult or FileVersion display state.
- [ ] Out-of-scope questions return `status=out_of_scope` with the specified scoped answer rather than using outside knowledge.
- [ ] Weak retrieval returns `status=insufficient_evidence` rather than unsupported content.
- [ ] Answered responses cite current AnalysisResult evidence ids, and validation failures return `QA_EVIDENCE_VALIDATION_FAILED`.
- [ ] QA conversations are not persisted, but the frontend can copy or download the current in-page QA session as Markdown with concise evidence references.
- [ ] Automated tests cover QA availability flags, Chroma fallback behavior, out-of-scope answers, insufficient evidence, evidence-id validation, and QA Markdown export.

## Blocked by

- Issue 3
- Issue 5
- Issue 6

## 9. Delete FileVersions and AnnualReports while cleaning visible stale state

Type: AFK

User stories covered: 32-36, 82-83

## Parent

#1

## What to build

Implement explicit delete flows and startup cleanup so visible AnnualReport and FileVersion state always matches available source PDFs, current AnalysisResults, generated artifacts, and QA indexes while historical AnalysisRuns remain audit snapshots only.

## Acceptance criteria

- [ ] Deleting a FileVersion deletes its source PDF, current AnalysisResult, generated assets, Chroma collection, and the empty AnnualReport if it was the last FileVersion.
- [ ] Deleting an AnnualReport deletes all FileVersions, source PDFs, current AnalysisResults, generated assets, and QA indexes after explicit confirmation.
- [ ] Delete confirmations show affected FileVersions and AnalysisResults.
- [ ] FileVersions and AnnualReports with in-progress analysis cannot be deleted until the run is stopped.
- [ ] Delete failures use the FileVersion, AnnualReport, source PDF, AnalysisResult, artifact, and empty-AnnualReport error codes from `CONTEXT.md`.
- [ ] Startup cleanup removes FileVersions whose physical PDFs are missing, removes their current AnalysisResult artifacts, deletes empty AnnualReports, and cleans orphan report asset directories.
- [ ] Historical AnalysisRuns remain only as audit records with source snapshots and do not expose unavailable FileVersions as active resources.
- [ ] Automated tests cover delete confirmations, in-progress delete blocking, artifact and Chroma cleanup, empty AnnualReport cleanup, missing-source startup repair, and historical source snapshots.

## Blocked by

- Issue 2
- Issue 3
- Issue 4
- Issue 5
- Issue 6
- Issue 8

## 10. Add a mocked CI workflow for the complete annual-report journey

Type: AFK

User stories covered: 85

## Parent

#1

## What to build

Add a small deterministic CI workflow that exercises the full supported AnnualReport/FileVersion/MDA journey with fixtures and mocks instead of real LLM, embedding, visual-model, or external PDF services.

## Acceptance criteria

- [ ] The mocked workflow covers valid upload, AnnualReport-first browsing, FileVersion selection, analysis start/progress, foreground report auto-open, report detail, Markdown/ZIP download, QA, AnalysisResult deletion, FileVersion deletion, and AnnualReport deletion.
- [ ] The mocked workflow covers annual-report summary rejection, duplicate upload handling, stop and re-analyze, and background completion notification without focus stealing.
- [ ] Tests assert API contracts, visible state transitions, artifact lifecycle outcomes, and frontend behavior rather than private implementation details or prompt wording.
- [ ] Existing verification scripts, real-PDF smoke tests, or evaluation harness entry points are updated or replaced so CI remains deterministic.
- [ ] CI fixtures do not call real LLM, embedding, visual-model, or web services.
- [ ] The workflow documents which required behavior is covered by automated CI and which quality behavior remains in evaluation.

## Blocked by

- Issue 1
- Issue 2
- Issue 3
- Issue 4
- Issue 5
- Issue 6
- Issue 7
- Issue 8
- Issue 9

## 11. Define evaluation examples and annotation schema

Type: HITL

User stories covered: 84, 86-88

## Parent

#1

## What to build

Define the human-reviewed evaluation dataset plan, annotation schema, and review criteria for upload admission, ManagementDiscussionAnalysisSection location, table extraction, figure analysis, structured outline quality, QA evidence behavior, and prompt/model changes.

## Acceptance criteria

- [ ] Required examples are identified for standard A-share complete Chinese annual reports, MDA tables, MDA figures, multi-level headings, and annual-report summary rejection.
- [ ] Opportunity examples are tracked separately for non-Chinese or English rejection, Hong Kong Chinese annual reports, A/H-code reports, difficult table extraction, scanned PDFs, unusual MDA structures, and figure-heavy reports.
- [ ] Evaluation annotations use one JSON file per PDF sample.
- [ ] Annotation schema validates physical PDF page numbers, MDA section boundaries, expected source sections, expected text/table/figure evidence, and expected QA evidence behavior.
- [ ] Evaluation runs record model configuration, application version, prompt versions, run time, pass rates, failed samples, failure reasons, and manual-review items.
- [ ] Human review criteria define sample quality and expected outcomes before samples become required coverage.
- [ ] Initial evaluation reporting does not enforce hard pass thresholds until the dataset and metrics stabilize.

## Blocked by

None - can start immediately

## 12. Integrate a real OpenAI-like FigureVisualAnalyzer for local MDA analysis

Type: AFK

User stories covered: 48-50, 75, 84

## Parent

#1

## What to build

Replace the default unavailable FigureVisualAnalyzer with a real OpenAI-like multimodal integration for local ManagementDiscussionAnalysisSection analysis while preserving the current separation between Figure visual analysis and outline generation. The product should continue to require visual analysis only when detected Figures need it, but once that happens, local manual analysis of a real PDF should call the configured provider instead of failing only because the default adapter is a placeholder. This slice should keep CI deterministic, preserve the current coarse product error codes, treat image-only tables as Figure inputs for the current phase, and document the real configuration path for developers.

## Acceptance criteria

- [ ] Figure visual analysis is configurable through environment variables with separate configuration keys for Figure analysis and outline generation, even if both eventually point to the same model name.
- [ ] The current phase supports OpenAI-like multimodal providers through Chat Completions-compatible requests and configurable base URL, without promising compatibility with every non-standard dialect.
- [ ] When Figure analysis is required, the FigureVisualAnalyzer sends one Figure candidate per request using an inline image payload such as base64 or data URL; this is implemented as the current seam and documented as a transitional design rather than the final throughput strategy.
- [ ] Image-only tables that cannot yet be parsed into structured rows and columns are treated as Figure inputs for visual analysis in this phase instead of being exposed as structured Tables.
- [ ] Missing or unusable visual-model configuration fails analysis with `VISION_MODEL_UNAVAILABLE`, while provider-call failures or invalid provider responses fail analysis with `CHART_ANALYSIS_FAILED`.
- [ ] Retryable provider failures are retried once; non-retryable authentication, configuration, model-name, or request-shape failures do not retry.
- [ ] Visual-model responses are strongly validated against the current Figure summary contract (`is_informational`, `classification_reason`, `summary`, `relevance`, and `relevance_reason`) before Figure evidence is accepted.
- [ ] Internal logs preserve fine-grained provider failure reasons without leaking secrets, full image payloads, or oversized raw responses.
- [ ] Deterministic automated tests cover environment-variable configuration loading, OpenAI-like request shaping, response validation, retry behavior, coarse error-code mapping, and image-only-table routing into the Figure path without making real network calls.
- [ ] Local developer documentation explains how to enable the real visual-model integration, clarifies that CI still uses mocks, and states that local manual analysis of a real PDF is expected to call the configured provider when Figure analysis is required.

## Blocked by

- Issue 6
