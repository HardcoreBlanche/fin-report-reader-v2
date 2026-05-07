# Implementation Issues: FileVersion and MDA Analysis

Source PRD: #1

Label for all issues: `needs-triage`

## 1. Admit only valid AnnualReportSource uploads

## Parent

#1

## What to build

Implement upload admission so only complete Chinese AnnualReportSource PDFs are accepted. The upload path validates PDF format, recognizes annual-report type and language, extracts StockCode, NormalizedStockCode, CompanyFullName, optional CompanyShortName, and ReportYear from allowed PDF body evidence, and rejects unsupported documents without persisting an active FileVersion.

## Acceptance criteria

- [ ] Invalid file extension, invalid PDF header, and unreadable PDF return HTTP 400 with `error_code`, `message`, and safe optional `details`.
- [ ] Valid PDFs that fail annual-report admission return HTTP 422 with the specific business error code from CONTEXT.md.
- [ ] Annual-report summaries, quarterly/semiannual reports, non-Chinese reports, missing identity fields, ambiguous StockCode, company-name mismatch, year mismatch, and company-profile section location failure are rejected with Chinese messages.
- [ ] StockCode and CompanyFullName are extracted from structured annual-report body evidence, not filenames, headers, arbitrary free text, or fuzzy guesses.
- [ ] ReportYear is extracted from the annual-report title and cross-checked against financial-data dates.
- [ ] Rejected AnnualReportSource candidates do not leave visible AnnualReport or FileVersion records.

## Blocked by

None - can start immediately

## 2. Create AnnualReport and FileVersion library entries from upload

## Parent

#1

## What to build

After a PDF passes admission, persist it as a FileVersion under the AnnualReport identified by NormalizedStockCode and ReportYear, then expose AnnualReport-first browsing with FileVersion selection.

## Acceptance criteria

- [ ] AnnualReport identity is exactly `NormalizedStockCode + ReportYear`; Exchange is stored only as optional metadata.
- [ ] Successful upload returns HTTP 201 with separate AnnualReport and FileVersion summaries.
- [ ] Uploading different content for an existing AnnualReport creates a new FileVersion and returns `annual_report_already_exists=true`.
- [ ] AnnualReports list by CompanyFullName with optional CompanyShortName and visible NormalizedStockCode.
- [ ] AnnualReports with the same CompanyFullName and ReportYear but different NormalizedStockCode values display as separate entries.
- [ ] FileVersions display original filename and upload time, without user-visible version numbers.

## Blocked by

- Issue 1

## 3. Handle duplicate active FileVersions and visible FileVersion actions

## Parent

#1

## What to build

Implement duplicate active FileVersion handling and derive FileVersion display state so the frontend can show valid actions for analysis, report viewing, QA, download, and deletion.

## Acceptance criteria

- [ ] Uploading content matching an active FileVersion returns HTTP 409 with `DUPLICATE_FILE_VERSION` and message `该文件已上传`.
- [ ] Duplicate responses include existing AnnualReport and FileVersion summaries, including display status.
- [ ] Deleted content uploaded again passes admission and creates a new FileVersion instead of restoring the old active record.
- [ ] AnnualReport summary status follows CONTEXT.md priority rules.
- [ ] FileVersion display status is inferred from current AnalysisResult or latest AnalysisRun.
- [ ] A ready AnalysisRun without an accessible AnalysisResult is treated as failed with `分析结果缺失`.
- [ ] Frontend actions are shown only for valid FileVersion display states.

## Blocked by

- Issue 2

## 4. Start auditable AnalysisRuns for FileVersions

## Parent

#1

## What to build

Start analysis from a FileVersion by creating an auditable AnalysisRun with concurrency controls, coarse status, detailed stage progress, and Chroma collection naming by AnalysisRun implementation id.

## Acceptance criteria

- [ ] Starting analysis creates an AnalysisRun bound to exactly one FileVersion.
- [ ] New AnalysisRuns use statuses `parsing`, `generating`, `ready`, `failed`, `stopped`, and `result_deleted`; new runs do not use `uploaded`.
- [ ] User-visible stages include `locating_section`, `extracting_content`, `analyzing_figures`, `generating_report`, `building_qa_index`, and `completed`.
- [ ] One FileVersion can have only one in-progress AnalysisRun.
- [ ] Different FileVersions can analyze concurrently when capacity allows.
- [ ] Product-level concurrency limit returns HTTP 429 with `ANALYSIS_CONCURRENCY_LIMIT_REACHED` and may include `Retry-After`.
- [ ] Chroma collections are named by AnalysisRun implementation id.

## Blocked by

- Issue 2

## 5. Stop, retry, and re-analysis guardrails

## Parent

#1

## What to build

Support stopping in-progress AnalysisRuns, retrying failed or stopped FileVersions, and preventing accidental overwrite of an existing current AnalysisResult.

## Acceptance criteria

- [ ] Stop marks the current AnalysisRun as `stopped` and distinguishes user cancellation from system failure.
- [ ] Stop prevents further PDF work and LLM calls for that run.
- [ ] Stop cleans pages, chunks, Chroma data, temporary report output, and figure assets created by the run.
- [ ] Failed and stopped FileVersions can be analyzed again directly, creating a new AnalysisRun while retaining historical runs.
- [ ] FileVersions with a current AnalysisResult cannot be re-analyzed until the AnalysisResult is explicitly deleted.
- [ ] Deleting an AnalysisResult retains AnnualReport, FileVersion, and historical AnalysisRun records.

## Blocked by

- Issue 4

## 6. Locate ManagementDiscussionAnalysisSection and extract text evidence

## Parent

#1

## What to build

Build a ManagementDiscussionAnalysisSection locator and text evidence extractor that scopes all downstream analysis to the third section, preserving source sections and stable text spans with physical PDF page references.

## Acceptance criteria

- [ ] Section range is located from `第三节 管理层讨论与分析` to before the next same-level section.
- [ ] TOC evidence is used when available and section start is verified in body pages.
- [ ] Location failures return `MD_A_SECTION_NOT_FOUND`, `MD_A_SECTION_START_UNVERIFIED`, or `MD_A_SECTION_END_NOT_FOUND`.
- [ ] Text extraction failures return `MD_A_TEXT_EXTRACTION_FAILED`.
- [ ] Source subsections are preserved in a source_sections tree.
- [ ] Text evidence cites `text_span_id` and physical PDF page.
- [ ] PDF-to-Markdown remains auxiliary; the structured MDA evidence package is the analysis source of truth.

## Blocked by

- Issue 4

## 7. Extract and expose MDA tables as structured evidence

## Parent

#1

## What to build

Extract tables inside the ManagementDiscussionAnalysisSection into structured rows and columns, validate them as evidence, and expose controlled access to table assets for report rendering and ZIP downloads.

## Acceptance criteria

- [ ] Tables in the MDA section are parsed into structured metadata, columns, rows, notes, and page references.
- [ ] Table evidence cites `table_id` and physical PDF page.
- [ ] Table parsing failure in the MDA section fails the AnalysisRun with `TABLE_ANALYSIS_FAILED`.
- [ ] Report detail includes table metadata and a controlled table URL for loading rows on demand.
- [ ] Table asset API verifies the table belongs to the FileVersion's current AnalysisResult.
- [ ] ZIP downloads include `tables/{table_id}.json` for structured table data.

## Blocked by

- Issue 6

## 8. Extract and analyze MDA figures as controlled assets

## Parent

#1

## What to build

Detect, filter, crop, store, and analyze informational figures in the ManagementDiscussionAnalysisSection, using controlled asset storage and visual-model summaries only when required by present figures.

## Acceptance criteria

- [ ] Figure detection excludes logos, watermarks, headers, footers, backgrounds, tiny decorative icons, and repeated non-body assets.
- [ ] Informational figures are cropped and stored under an AnalysisRun asset directory with `image_id`, page, bbox, and optional title/caption metadata.
- [ ] Visual model availability is required only when MDA figures requiring visual analysis are present.
- [ ] Missing visual model returns `VISION_MODEL_UNAVAILABLE`; figure analysis failures return the specified figure/visual error codes.
- [ ] Low-relevance figures are retained in collapsed other-figures areas but not used in main analysis points.
- [ ] Report detail exposes controlled thumb and original image URLs, and ZIP includes original cropped figures.
- [ ] Asset promotion, rollback, and cleanup follow the commit-order constraints in CONTEXT.md.

## Blocked by

- Issue 6

## 9. Generate validated AnalysisResult structured outline

## Parent

#1

## What to build

Generate and persist a validated MDA-only AnalysisResult structured outline from source sections, text spans, tables, and figure summaries, dropping unsupported analysis points and failing runs when no valid evidence remains.

## Acceptance criteria

- [ ] AnalysisResult contains a 3 to 5 sentence summary based only on MDA evidence.
- [ ] `structured_outline` includes `summary`, `source_sections`, `analysis_sections`, `points`, and `evidence`.
- [ ] Analysis sections follow the MDA content naturally, using recommended themes only when supported.
- [ ] Each substantive analysis point references source sections and evidence.
- [ ] Backend validation drops evidence-free points and empty sections from user-facing output.
- [ ] No valid evidence-backed points fails the run with `ANALYSIS_OUTPUT_NO_VALID_EVIDENCE`.
- [ ] Invalid model output is retried once with validation errors and then fails with the correct schema or invalid-asset error code.
- [ ] Prompt versions are recorded for traceability.

## Blocked by

- Issue 6
- Issue 7
- Issue 8

## 10. Render interactive report detail from AnalysisResult

## Parent

#1

## What to build

Render report detail from the structured AnalysisResult for interactive use, showing source sections, evidence references, text spans, table and figure metadata, and focused expandable evidence.

## Acceptance criteria

- [ ] Report detail responses are optimized for interactive rendering and do not return one large Markdown string.
- [ ] Report detail includes source section tree and text-span index.
- [ ] Evidence references are visible, with the most important evidence shown initially and all evidence expandable.
- [ ] Figure images show by default at fitted size with summaries and links to larger originals.
- [ ] Table names and summaries show first, with full rows loaded on demand.
- [ ] When analysis completes for the user-waited FileVersion, the frontend selects that FileVersion and opens the report without stealing focus from unrelated background completions.

## Blocked by

- Issue 9

## 11. Download AnalysisResult as Markdown and ZIP

## Parent

#1

## What to build

Generate Markdown and ZIP downloads from the validated AnalysisResult structure, including figure and table evidence assets where appropriate.

## Acceptance criteria

- [ ] Backend renders Markdown from AnalysisResult, not from legacy full-report Markdown.
- [ ] Markdown includes concise evidence lists after analysis points.
- [ ] Markdown includes figure references and warns that ZIP is needed for complete offline assets.
- [ ] Markdown includes table names, summaries, and a reminder that ZIP is needed for complete table data.
- [ ] ZIP includes Markdown, original cropped figure assets, and structured table JSON.
- [ ] Unsupported download format and generation failures return the specified report download error codes.

## Blocked by

- Issue 7
- Issue 8
- Issue 9

## 12. Constrain QA to current AnalysisResult evidence

## Parent

#1

## What to build

Limit QA to analyzed FileVersions with a current AnalysisResult, indexing only MDA evidence and validating every substantive answer against current AnalysisResult evidence ids.

## Acceptance criteria

- [ ] QA is available only for an analyzed FileVersion with a current AnalysisResult.
- [ ] AnalysisResult stores `qa_available` and `qa_unavailable_reason`.
- [ ] Embedding or Chroma failure sets `qa_available=false` and returns `QA_INDEX_UNAVAILABLE` without failing report creation.
- [ ] QA indexing includes only MDA text spans, structured table content, and figure visual summaries.
- [ ] Out-of-scope questions return `status=out_of_scope` with the specified scoped answer.
- [ ] Weak retrieval returns `status=insufficient_evidence` rather than unsupported content.
- [ ] Answered QA responses cite current AnalysisResult evidence ids.
- [ ] QA conversations are not persisted, but the frontend can copy or download the current in-page QA session as Markdown.

## Blocked by

- Issue 9

## 13. Delete AnalysisResult, FileVersion, AnnualReport, and cleanup stale artifacts

## Parent

#1

## What to build

Implement explicit delete flows and startup cleanup that keep visible library state aligned with available sources and current AnalysisResults while retaining historical AnalysisRun snapshots for audit.

## Acceptance criteria

- [ ] Deleting an AnalysisResult removes generated artifacts and Chroma data, keeps AnnualReport and FileVersion, and marks the historical run `result_deleted`.
- [ ] Deleting a FileVersion deletes its source PDF, current AnalysisResult, generated assets, and empty AnnualReport if it was the last FileVersion.
- [ ] Deleting an AnnualReport deletes all FileVersions, source PDFs, current AnalysisResults, and generated artifacts after confirmation.
- [ ] Delete confirmations show affected FileVersions and AnalysisResults.
- [ ] FileVersions or AnnualReports with in-progress analysis cannot be deleted until analysis is stopped.
- [ ] Startup cleanup removes FileVersions whose physical PDFs are missing, removes current AnalysisResult artifacts, deletes empty AnnualReports, and cleans orphan report asset directories.
- [ ] Historical AnalysisRuns remain only as audit snapshots and do not expose unavailable resources as active.

## Blocked by

- Issue 5
- Issue 9

## 14. Update automated tests for FileVersion and MDA workflows

## Parent

#1

## What to build

Update deterministic automated tests and CI fixtures to verify the FileVersion, AnalysisRun, AnalysisResult, MDA evidence, artifact lifecycle, and frontend workflow behavior delivered by the implementation issues.

## Acceptance criteria

- [ ] API contract tests cover upload admission, AnnualReport listing, FileVersion analysis start/status/stop, report detail, table assets, figure assets, downloads, QA, and delete flows.
- [ ] State-transition tests cover duplicate FileVersion decisions, status inference, retry, stop, result deletion, and startup cleanup.
- [ ] Artifact lifecycle tests cover asset promotion, rollback, Chroma cleanup, report asset cleanup, and missing-source startup cleanup.
- [ ] Orchestrator tests mock PDF extraction, LLM, embedding, visual model, Chroma, and asset storage.
- [ ] Frontend component/integration tests cover grouped browsing, FileVersion selection, duplicate upload handling, stop and re-analyze, delete report and re-analyze, asset interactions, downloads, QA statuses, and delete confirmations.
- [ ] CI and E2E fixtures avoid real LLM, embedding, and visual-model calls.

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
- Issue 10
- Issue 11
- Issue 12
- Issue 13

## 15. Define evaluation examples and annotation schema

## Parent

#1

## What to build

Define the human-reviewed evaluation dataset plan, annotation schema, and review criteria for measuring upload admission, MDA section location, table extraction, figure analysis, structured outline quality, QA evidence behavior, and prompt/model changes.

## Acceptance criteria

- [ ] Required examples are identified for standard A-share Chinese complete annual reports, MDA tables, MDA figures, multi-level headings, and annual-report summary rejection.
- [ ] Opportunity examples are tracked separately for non-Chinese reports, Hong Kong Chinese reports, A/H-code reports, difficult table extraction, scanned PDFs, unusual MDA structures, and figure-heavy reports.
- [ ] Evaluation annotations use one JSON file per PDF sample.
- [ ] Annotation schema validates physical PDF page numbers and expected evidence references.
- [ ] Evaluation runs record model configuration, application version, prompt versions, run time, pass rates, failed samples, failure reasons, and manual-review items.
- [ ] Human review criteria define sample quality and expected outcomes before samples become required coverage.

## Blocked by

None - can start immediately
