# PRD: 基于 FileVersion 和管理层讨论与分析重构年报分析

目标 issue label: `needs-triage`

需求来源优先级：

- `CONTEXT.md` 是需求和领域语言的最高优先级来源。
- `ADR-0001` 是架构方向和设计约束的最高优先级来源。
- 当前代码只用于判断后续改造范围，不作为需求依据。

## Problem Statement

用户需要一个以 **AnnualReport** 为中心的中文年报阅读助手：系统应在上传时确认 PDF 是可识别的完整中文年度报告，按 **NormalizedStockCode + ReportYear** 归档同一公司的同一年报，并允许用户在同一 AnnualReport 下管理多个 **FileVersion**。

当前产品目标不再是对整份 PDF 做通用概览、硬规则检查和财务抽取，而是只基于第三节 **ManagementDiscussionAnalysisSection（管理层讨论与分析）** 生成可验证的 **AnalysisResult**。用户需要看到有证据引用的结构化分析，能够查看文本、表格和图示证据，下载报告，并在同一范围内追问。任何超出该章节、来自模型背景知识、网页或其他年报章节的信息都不应进入分析或问答。

## Solution

将产品重构为四个核心对象：**AnnualReport**、**FileVersion**、**AnalysisRun** 和 **AnalysisResult**。

上传阶段执行严格准入：只接受完整中文年度报告；从 PDF 正文识别 StockCode、CompanyFullName、ReportYear，并生成 NormalizedStockCode。重复上传同一 active FileVersion 返回 `DUPLICATE_FILE_VERSION`；同一 AnnualReport 的不同 PDF 内容创建新的 FileVersion。

用户先浏览 AnnualReport，再选择 FileVersion。每个 FileVersion 最多有一个当前 AnalysisResult；分析运行只处理 ManagementDiscussionAnalysisSection，定位该节范围后构建当前 AnalysisResult 拥有的 **EvidencePackage**，包括 source_sections、text spans、structured tables、figure assets、section-location evidence 和 evidence references。后端验证模型输出，丢弃无证据分析点，失败时返回明确错误。交互式报告、structured_outline、Markdown/ZIP 下载和 QA 都是同一个 EvidencePackage 与已验证 AnalysisResult 的投影，不创建独立证据命名空间。

当前阶段的真实模型集成优先落在 Figure 视觉分析链路：系统继续保留 `FigureVisualAnalyzer` 与 `MdaOutlineGenerator` 的职责分离，底层模型供应商可以相同，但本阶段只要求先接通真实 Figure 视觉理解能力，使检测到需要视觉分析的 Figure 时不再因默认 unavailable 实现而失败。文本报告生成与 QA 可继续使用现有简化实现，后续再单独升级为真实模型调用。

## User Stories

1. As an annual-report reader, I want to upload a PDF and know immediately whether it is a supported complete Chinese annual report, so that I do not wait until analysis to discover the file is unusable.
2. As an annual-report reader, I want unsupported PDFs to be rejected with a clear Chinese reason, so that I understand whether the issue is file format, report type, language, missing StockCode, missing ReportYear, or missing CompanyFullName.
3. As an annual-report reader, I want annual-report summaries to be rejected during upload, so that the system only analyzes complete annual reports.
4. As an annual-report reader, I want quarterly, semiannual, non-Chinese, and unreadable PDFs rejected during upload, so that the library only contains usable AnnualReportSources.
5. As an annual-report reader, I want StockCode and CompanyFullName extracted from structured annual-report content rather than guessed from filenames, so that AnnualReport identity is reliable.
6. As an annual-report reader, I want ReportYear extracted from the annual-report title rather than publication date or upload date, so that reports are grouped by fiscal year.
7. As an annual-report reader, I want the first-page company name checked against CompanyFullName, so that misidentified PDFs are rejected.
8. As an annual-report reader, I want report-year conflicts between title and financial-data dates to be rejected, so that the system does not attach a PDF to the wrong year.
9. As an annual-report reader, I want the system to use a NormalizedStockCode such as A:600519 for identity, so that same-looking codes from different markets are not merged incorrectly.
10. As an annual-report reader, I want the system to prefer A-share StockCode when multiple codes are present, so that the primary AnnualReport identity follows the current product rule.
11. As an annual-report reader, I want AnnualReports grouped by NormalizedStockCode and ReportYear, so that I can browse by company-year instead of by raw uploaded files.
12. As an annual-report reader, I want CompanyFullName shown as the main AnnualReport label and CompanyShortName as secondary text when available, so that list entries are recognizable.
13. As an annual-report reader, I want AnnualReports with the same CompanyFullName and ReportYear but different NormalizedStockCode values shown separately, so that A/H or conflicting identities are visible.
14. As an annual-report reader, I want each FileVersion shown by original filename and upload time, so that I can distinguish uploaded PDFs without user-visible version numbers.
15. As an annual-report reader, I want uploading the same active PDF content to return `DUPLICATE_FILE_VERSION`, so that duplicate FileVersions are not created.
16. As an annual-report reader, I want duplicate upload responses to include the existing AnnualReport and FileVersion summaries, so that the frontend can guide me to the existing item.
17. As an annual-report reader, I want uploading different PDF content for an existing AnnualReport to create a new FileVersion, so that revised or alternative source PDFs can be compared by source.
18. As an annual-report reader, I want AnnualReport summary status to reflect whether any FileVersion is analyzing, analyzed, failed, stopped, or not analyzed, so that navigation gives me a useful overview.
19. As an annual-report reader, I want FileVersion display status to control available actions, so that I only see analysis, report, QA, and delete actions when they are valid.
20. As an annual-report reader, I want starting analysis on a FileVersion to create an AnalysisRun, so that each execution is auditable.
21. As an annual-report reader, I want only one in-progress AnalysisRun per FileVersion, so that duplicate runs do not compete or corrupt results.
22. As an annual-report reader, I want different FileVersions to be analyzed concurrently when capacity allows, so that independent uploads do not block each other unnecessarily.
23. As an annual-report reader, I want analysis concurrency limits to return HTTP 429 with `ANALYSIS_CONCURRENCY_LIMIT_REACHED`, so that the UI can ask me to retry later.
24. As an annual-report reader, I want analysis progress to show detailed stages such as locating section, extracting content, analyzing figures, generating report, and building QA index, so that I know what the system is doing.
25. As an annual-report reader, I want to stop an in-progress AnalysisRun, so that I can cancel expensive or unwanted analysis.
26. As an annual-report reader, I want stopped analysis to be displayed separately from failed analysis, so that user cancellation is not confused with system error.
27. As an annual-report reader, I want stopping analysis to terminate further PDF work and LLM calls, so that cancellation has real effect.
28. As an annual-report reader, I want stopping analysis to clean up pages, chunks, Chroma data, temporary report output, and figure assets, so that no partial result is exposed.
29. As an annual-report reader, I want failed or stopped FileVersions to be directly analyzable again, so that I can retry without deleting the source PDF.
30. As an annual-report reader, I want a FileVersion with an existing AnalysisResult to require report deletion before re-analysis, so that the current result is never overwritten accidentally.
31. As an annual-report reader, I want deleting an AnalysisResult to keep AnnualReport, FileVersion, and historical AnalysisRun records, so that source management and audit history remain intact.
32. As an annual-report reader, I want deleting a FileVersion to delete its source PDF, current AnalysisResult, generated assets, and empty AnnualReport if it was the last version, so that visible library state matches available files.
33. As an annual-report reader, I want deleting an AnnualReport to delete all FileVersions, PDFs, current AnalysisResults, and generated artifacts after confirmation, so that I can clean up an entire company-year.
34. As an annual-report reader, I want delete actions to require explicit confirmation and show the affected FileVersions and AnalysisResults, so that destructive actions are deliberate.
35. As an annual-report reader, I want startup cleanup to remove FileVersions whose physical PDFs are missing and remove their current AnalysisResult artifacts, so that unavailable source files do not leave visible stale reports.
36. As an annual-report reader, I want historical AnalysisRuns retained only as audit records after source deletion, so that troubleshooting remains possible without showing unavailable resources as active.
37. As an annual-report reader, I want analysis to locate the ManagementDiscussionAnalysisSection from the third-section heading to before the next same-level section, so that results are scoped to the correct source.
38. As an annual-report reader, I want section location to use and verify table-of-contents evidence when available, so that analysis does not start from a mistaken page.
39. As an annual-report reader, I want section-location failures to use specific error codes, so that I know whether the section was missing, the start was unverified, or the end could not be found.
40. As an annual-report reader, I want PDF parsing to produce a structured evidence package rather than only Markdown, so that reports can cite precise source text, tables, and figures.
41. As an annual-report reader, I want source subsections preserved in a source_sections tree, so that I can navigate analysis back to the original MDA structure.
42. As an annual-report reader, I want text evidence to cite text_span_id and physical PDF page, so that claims can be checked against the source.
43. As an annual-report reader, I want table evidence to cite table_id and page, so that table-based conclusions are traceable.
44. As an annual-report reader, I want tables in ManagementDiscussionAnalysisSection parsed into structured rows and columns, so that analysis can use table data rather than table screenshots or lossy prose.
45. As an annual-report reader, I want table parsing failures in the MDA section to fail the AnalysisRun with `TABLE_ANALYSIS_FAILED`, so that incomplete table analysis does not produce a misleading report.
46. As an annual-report reader, I want figures in ManagementDiscussionAnalysisSection detected while excluding logos, watermarks, headers, footers, backgrounds, and tiny decorative icons, so that only relevant visual exhibits are analyzed.
47. As an annual-report reader, I want informational figures cropped and stored as controlled report assets, so that the report can show the original visual evidence.
48. As an annual-report reader, I want detected Figures in the ManagementDiscussionAnalysisSection analyzed by a visual model when they require visual analysis, so that chart and diagram content is not ignored.
49. As an annual-report reader, I want analysis to fail with `VISION_MODEL_UNAVAILABLE` when figures require visual analysis but no visual model is available, so that visual evidence gaps are explicit.
50. As an annual-report reader, I want irrelevant but valid figures placed in a collapsed other-figures area, so that the report remains focused without losing source visibility.
50a. As an annual-report reader, I want image-only tables that cannot yet be parsed into structured rows and columns to be treated as Figures for visual analysis, so that visual evidence is not dropped just because structured table extraction is incomplete.
50b. As an annual-report reader, I want local manual analysis of a real PDF to call the configured visual-model API when Figure analysis is required, so that local product use exercises the real integration rather than only mocks.
50c. As a maintainer, I want automated tests to keep mocking visual-model calls while local manual smoke tests use real model calls, so that CI remains deterministic without hiding real integration behavior from developers.
51. As an annual-report reader, I want the AnalysisResult to include a 3 to 5 sentence summary based only on MDA evidence, so that I get a concise overview without unsupported claims.
52. As an annual-report reader, I want analysis sections organized naturally from the MDA content, so that the report follows the source rather than a rigid checklist.
53. As an annual-report reader, I want recommended themes such as business model, industry environment, operating performance, competitiveness, risks, and future direction used when supported, so that common MDA concerns are easy to scan.
54. As an annual-report reader, I want unsupported recommended themes skipped rather than shown as not disclosed, so that the report contains only evidence-backed content.
55. As an annual-report reader, I want each analysis point to include source_section_ids and evidence, so that I can verify every substantive conclusion.
56. As an annual-report reader, I want evidence-free analysis points dropped by backend validation, so that the displayed report remains trustworthy.
57. As an annual-report reader, I want an AnalysisRun to fail with `ANALYSIS_OUTPUT_NO_VALID_EVIDENCE` if no valid evidence-backed points remain, so that an empty or hallucinated report is not saved.
58. As an annual-report reader, I want invalid model output retried once with validation errors, so that recoverable schema mistakes can be corrected automatically.
59. As an annual-report reader, I want persistent AnalysisResult content stored as structured JSON while the report shape evolves, so that the UI and downloads can render from validated data.
60. As an annual-report reader, I want report detail responses optimized for interactive rendering rather than returning one large Markdown string, so that the frontend can show sections, evidence, and assets efficiently.
61. As an annual-report reader, I want the interactive report to show evidence references and initially show the most important evidence with an option to expand, so that the page is readable but complete.
62. As an annual-report reader, I want figure images shown by default at a fitted size with summaries and larger originals available, so that I can inspect visual evidence.
63. As an annual-report reader, I want table names and summaries shown first with full structured table rows loaded on demand, so that large tables do not overwhelm the report view.
64. As an annual-report reader, I want report downloads in Markdown and ZIP formats, so that I can use a lightweight text report or a complete offline package with assets.
65. As an annual-report reader, I want ZIP downloads to include figure images and structured table JSON, so that evidence assets travel with the report.
66. As an annual-report reader, I want plain Markdown downloads to keep figure references and warn when ZIP is needed for complete offline assets, so that I understand download limitations.
67. As an annual-report reader, I want QA to be available only for analyzed FileVersions with a current AnalysisResult, so that answers are tied to a validated report.
68. As an annual-report reader, I want AnalysisResult to store `qa_available` and `qa_unavailable_reason`, so that indexing failures are visible without changing report state.
69. As an annual-report reader, I want QA index failures to return `QA_INDEX_UNAVAILABLE` rather than failing the saved report, so that report viewing still works.
70. As an annual-report reader, I want QA questions outside ManagementDiscussionAnalysisSection to return an out-of-scope answer, so that the system does not answer from unsupported sources.
71. As an annual-report reader, I want substantive QA answers to cite text, table, and figure evidence from the current AnalysisResult, so that answers are verifiable.
72. As an annual-report reader, I want QA to return insufficient-evidence status rather than an unsupported answer when retrieval is weak, so that uncertainty is explicit.
73. As an annual-report reader, I want QA evidence to reuse current AnalysisResult evidence ids, so that report and QA navigation share the same source package.
74. As an annual-report reader, I want to copy or download the current in-page QA session as Markdown, so that I can keep my working notes without requiring persistent conversations.
75. As a maintainer, I want business error responses to use `error_code`, `message`, and safe optional details, so that frontend handling is stable and internals are not leaked.
76. As a maintainer, I want upload format errors to be HTTP 400 and annual-report admission failures to be HTTP 422, so that clients can distinguish invalid file format from unsupported business document.
77. As a maintainer, I want current FileVersion state inferred from current AnalysisResult or latest AnalysisRun, so that visible UI state remains consistent.
78. As a maintainer, I want a ready AnalysisRun without an accessible AnalysisResult treated as failed with “分析结果缺失”, so that consistency errors do not show as successful reports.
79. As a maintainer, I want Chroma collections named by AnalysisRun implementation id, so that QA index cleanup is scoped to one run.
80. As a maintainer, I want QA indexing to include only MDA text, structured table content, and figure visual summaries, so that retrieval cannot pull from outside the allowed source.
81. As a maintainer, I want Chroma write or embedding failure to set `qa_available=false` without failing AnalysisResult creation, so that report generation and QA availability are decoupled.
82. As a maintainer, I want asset commit order to promote assets before saving AnalysisResult and mark the run ready only after result persistence succeeds, so that saved results never point to missing assets.
83. As a maintainer, I want asset and result persistence failures to clean up promoted assets and indexes, so that partial commits do not remain visible.
84. As a maintainer, I want prompt versions recorded for MDA outline, figure summaries, and QA answers, so that evaluation results are traceable.
85. As a maintainer, I want automated tests to mock LLM, embedding, and visual-model calls, so that CI is deterministic.
86. As a maintainer, I want evaluation runs with real models to record model configuration, app version, prompt version, and run time, so that model-quality changes can be compared.
87. As a maintainer, I want required and opportunity evaluation examples separated, so that rare missing samples are tracked without blocking every development step.
88. As a maintainer, I want evaluation annotations to use physical PDF page numbers, so that they match product evidence references.
89. As a maintainer, I want EvidencePackage to be the canonical registry for source sections, text spans, tables, figures, and section-location evidence, so that report detail, downloads, and QA cannot drift into separate evidence ids.
90. As a maintainer, I want locator evidence kept separate from analysis and QA evidence, so that table-of-contents or boundary-heading material outside the MDA body is never used as substantive support.
91. As an annual-report reader, I want the just-finished analysis I am waiting for to auto-open the selected FileVersion report, so that the workflow lands directly on the result.
92. As an annual-report reader, I want background analysis completions to show a notification without stealing focus, so that other work is not interrupted.
93. As an annual-report reader, I want user-facing labels to use terms such as “管理层讨论与分析”, “章节结构”, “分析报告”, “问答索引”, and “证据包”, so that internal implementation names do not leak into the product experience.

## Implementation Decisions

- Treat `CONTEXT.md` as the highest-priority source for domain language and product requirements.
- Treat ADR-0001 as the highest-priority source for architecture direction and design constraints.
- Do not derive requirements from current code, old design documents, or as-built maps. Current code is only a retrofit input.
- Preserve the domain model vocabulary: AnnualReport, AnnualReportSource, StockCode, NormalizedStockCode, CompanyFullName, CompanyShortName, Exchange, ReportYear, FileVersion, AnalysisRun, AnalysisResult, ManagementDiscussionAnalysisSection, EvidencePackage, Figure, and Table.
- Replace file-first browsing with AnnualReport-first browsing and FileVersion selection under each AnnualReport.
- Define AnnualReport identity as exactly NormalizedStockCode plus ReportYear. Exchange may be stored but does not participate in identity.
- Store one primary NormalizedStockCode per AnnualReport. Do not store secondary stock codes in the current product scope.
- Move annual-report recognition into upload admission. Upload must not persist unrecognized PDFs.
- Build an upload admission module that extracts evidence from the first PDF page and the “公司简介和主要财务指标” section, with table-of-contents assisted section location and fallback heading search.
- Implement duplicate FileVersion behavior exactly as specified: active content-hash duplicates return HTTP 409 with `DUPLICATE_FILE_VERSION`; deleted content can be uploaded later as a new FileVersion after admission checks.
- Return HTTP 201 for any upload that creates a new active FileVersion, with `annual_report_already_exists` distinguishing whether it attached to an existing AnnualReport.
- Create or adapt persistence around AnnualReport, FileVersion, AnalysisRun, AnalysisResult, source section trees, text spans, structured table data, figure assets, and current-result pointers.
- Model EvidencePackage as the current AnalysisResult-owned canonical registry for ManagementDiscussionAnalysisSection source sections, text spans, structured tables, figures, and section-location evidence.
- Treat report detail, structured_outline, Markdown/ZIP downloads, and QA as projections over the current EvidencePackage. These projections must reuse EvidencePackage ids and must not mint separate evidence ids or persist projected asset URLs as source-of-truth data.
- Keep section locator evidence distinct from analysis-point and QA-answer evidence because locator evidence may include table-of-contents text or boundary headings outside the ManagementDiscussionAnalysisSection body.
- Model AnalysisRun statuses as `parsing`, `generating`, `ready`, `failed`, `stopped`, and `result_deleted`; new runs do not use `uploaded`.
- Add AnalysisRun stage values for `locating_section`, `extracting_content`, `analyzing_figures`, `generating_report`, `building_qa_index`, and `completed`.
- Enforce one in-progress AnalysisRun per FileVersion and add a product-level concurrency limit across active runs.
- Add stop-analysis behavior as a terminal state that cancels further extraction and model calls, marks the run `stopped`, and cleans intermediate artifacts.
- Require explicit AnalysisResult deletion before re-analyzing an already analyzed FileVersion.
- Keep historical AnalysisRuns for audit and troubleshooting but do not expose normal UI selection among historical runs.
- Build a ManagementDiscussionAnalysisSection locator that verifies section start in body pages and determines section end before the next same-level section.
- Treat PDF-to-Markdown as optional auxiliary extraction; the analysis source of truth is the structured MDA evidence package.
- Build text-span extraction with physical PDF page references and stable ids within an AnalysisResult.
- Build table extraction and validation for MDA tables, storing structured rows and metadata in the AnalysisResult JSON and exposing controlled table resource access.
- Define Table narrowly as structured row-and-column evidence. If a table-like exhibit is only available as an image and cannot yet be parsed into structured rows and columns, treat it as a Figure for the current phase of visual analysis rather than pretending it is a structured Table.
- Build figure detection, filtering, cropping, asset storage, visual-model summarization, relevance classification, thumbnail generation, and controlled figure asset access.
- Make visual model availability required only when MDA figures that require visual analysis are present.
- Keep Figure visual analysis and outline generation as separate system responsibilities even when they point at the same underlying multimodal model provider; the current phase only replaces the FigureVisualAnalyzer default with a real provider integration.
- Introduce OpenAI-like visual-model configuration through environment variables rather than UI settings or database-backed configuration. Separate configuration keys should exist for Figure visual analysis and outline generation even if both eventually point to the same model name.
- In the current phase, support OpenAI-like multimodal providers through Chat Completions-compatible requests and configurable base URL. Do not promise compatibility with every non-standard OpenAI-like dialect.
- Send one Figure candidate per visual-model request using an inline image payload such as base64 or data URL. Treat this as an intentional first-step seam, not the long-term throughput design; future batching and URL-based image delivery remain expected follow-up work.
- Keep capability detection as an analysis-time check for now. If visual-model configuration is missing, the system may still start up normally, but an AnalysisRun that reaches required Figure analysis must fail fast with `VISION_MODEL_UNAVAILABLE`.
- Keep external error codes coarse: missing or unusable visual-model configuration maps to `VISION_MODEL_UNAVAILABLE`, while provider-call failures or invalid visual-model responses map to `CHART_ANALYSIS_FAILED`. Internal diagnostics and logs should preserve finer-grained failure reasons without leaking secrets or oversized raw payloads.
- Allow one limited retry for retryable visual-model failures such as transient network or provider errors; authentication, model-name, or request-shape failures should not retry.
- Require strong structured output validation from the visual model. The current FigureVisualAnalyzer contract continues to require `is_informational`, `classification_reason`, `summary`, `relevance`, and `relevance_reason`; missing or invalid fields fail the analysis rather than triggering silent degradation.
- Make the visual-model prompt explicitly cover image-only tables, charts, diagrams, and similar Figure inputs so that temporary Figure-based handling of image-only tables is consistent with the current product phase.
- Fail AnalysisRun on required MDA text, table, or figure analysis failures rather than creating incomplete AnalysisResults.
- Generate a validated loose structured_outline with summary, source_sections, analysis_sections, points, and evidence.
- Treat `source_sections` in structured_outline as a projection or mirror of the EvidencePackage tree. The model and UI must not independently modify the canonical source section tree.
- Ensure each source section node can associate its owned text spans, tables, and figures through `text_span_ids`, `table_ids`, and `image_ids`.
- Retry invalid model output once with validation errors, then fail with the specific validation or invalid-asset error code.
- Persist dropped evidence-free points in internal diagnostics only; do not show them in user-facing reports.
- Render interactive report detail from structured AnalysisResult JSON and source evidence indexes, not from one large Markdown blob.
- Render backend downloads from the validated AnalysisResult structure. Support Markdown and ZIP; include figure assets and table JSON in ZIP.
- Build QA indexing only from MDA evidence: text spans, structured table content, and figure visual summaries.
- Prefer Chroma retrieval and fall back to keyword search over structured outline and source sections when evidence is insufficient.
- Store `qa_available` and `qa_unavailable_reason` on AnalysisResult; QA indexing failure does not fail report creation.
- Validate QA answers against current AnalysisResult evidence ids before returning `answered`; otherwise return insufficient evidence or validation error.
- Add grouped AnnualReport list, FileVersion list, FileVersion actions, analysis progress, stop, delete, report detail, evidence navigation, asset viewing, downloads, QA statuses, and QA Markdown export to the frontend experience.
- Auto-select the FileVersion and open the interactive report detail when the analysis the user is actively waiting for reaches `analyzed`; background completions should notify without taking focus.
- Use user-facing copy such as “管理层讨论与分析”, “章节结构”, “分析报告”, “问答索引”, and “证据包”; do not use internal names such as `MDA`, `source_sections`, `AnalysisResult`, `Chroma`, or `evidence package` as primary labels.
- Add startup cleanup that removes invisible or missing-source FileVersions from active library state, cleans current AnalysisResult artifacts, cleans orphan report asset directories, and keeps historical AnalysisRun snapshots for audit.
- Add explicit delete flows for AnalysisResult, FileVersion, and AnnualReport with confirmation and specified error codes.
- Treat existing file/task/report implementation as a migration and compatibility concern, not as the target domain model.

## Testing Decisions

- Good automated tests should assert external behavior, domain state transitions, API contracts, persistence invariants, and artifact lifecycle outcomes. They should avoid testing private implementation details or prompt phrasing.
- Use TDD-style automated tests for deterministic logic: upload admission classification, identity extraction, company-name normalization, duplicate FileVersion decisions, AnnualReport grouping, status inference, state transitions, deletion rules, startup cleanup, EvidencePackage ownership and id reuse, structured outline validation, asset commit/rollback, QA availability flags, and business error mapping.
- Use API contract tests for upload, AnnualReport listing, FileVersion analysis start, analysis status, stop analysis, report detail, table asset access, figure asset access, report downloads, QA, AnalysisResult deletion, FileVersion deletion, and AnnualReport deletion.
- Use orchestrator tests with mocked PDF extraction, LLM, embedding, visual model, Chroma, and asset storage to verify AnalysisRun progress, retries, failures, cleanup, and ready-state commit order.
- Add deterministic tests for the real visual-model adapter boundary without making network calls: environment-variable configuration loading, OpenAI-like request shaping, response-shape validation, retry policy, coarse error-code mapping, and image-only-table routing into the Figure path.
- Use component and integration tests for frontend workflows: valid upload through foreground auto-open report, background completion notification without focus stealing, duplicate upload handling, AnnualReport grouped browsing, FileVersion selection, stop and re-analyze, delete report and re-analyze, asset interactions, report downloads, QA statuses, and delete confirmations.
- Use a small end-to-end workflow suite with mocks or fixtures instead of real model calls for CI.
- Use local manual smoke tests with real PDF samples and real visual-model credentials outside CI to verify that local product use actually calls the configured provider when Figure analysis is required.
- Maintain evaluation datasets for PDF/table/figure/LLM quality. Required examples include standard A-share complete Chinese annual reports, reports with MDA tables, reports with MDA figures, reports with multi-level headings, and annual-report summary rejection cases.
- Track opportunity examples without making them initial blockers: non-Chinese or English rejection, Hong Kong Chinese annual reports, A/H-code reports, difficult table extraction, scanned PDFs, unusual MDA structure, and figure-heavy reports.
- Store evaluation annotations one JSON file per PDF sample and validate them with an evolving annotation schema before comparison.
- Evaluation page annotations and product evidence references both use physical PDF page numbers.
- Evaluation runs should initially report pass rates, failed samples, failure reasons, manual-review items, prompt versions, model configuration, run time, and application version without blocking development thresholds.
- Prior art in the current project includes backend verification scripts, a basic real-PDF workflow script, and an evaluation harness; these should be updated or replaced to match the new AnnualReport/FileVersion/MDA requirements.

## Out of Scope

- Whole-PDF analysis outside ManagementDiscussionAnalysisSection.
- Legacy overview, hard rules, financial-statement extraction, and rigid business-entry extraction as AnalysisResult requirements.
- Persisted QA conversations; only in-page copy/download is required.
- User selection among historical AnalysisRuns in the normal UI.
- User-visible FileVersion version numbers.
- Secondary stock-code storage for an AnnualReport.
- Using filenames, headers, arbitrary code-like numbers, fuzzy company-name matching, model background knowledge, web information, or non-MDA sections as requirement-level evidence sources.
- Full Hong Kong annual-report support as a core required capability, though limited HK code support is allowed.
- Real LLM, embedding, or visual-model calls in CI.
- Hard evaluation thresholds before the dataset and metrics stabilize.
- Manual user correction of missing StockCode, ReportYear, or CompanyFullName during upload.

## Further Notes

- This PRD intentionally follows `CONTEXT.md` and ADR-0001 when they conflict with current code, old docs, or as-built maps.
- The current visual-model integration phase is intentionally incremental: Figure visual analysis is the first real-model integration, while real outline generation, richer capability discovery, batch Figure requests, and URL-based image transport are expected follow-up work rather than prerequisites for this phase.
- Current implementation appears to require broad retrofit across upload admission, identity persistence, analysis orchestration, MDA extraction, report generation, QA, cleanup, downloads, and frontend flows. That retrofit scope is an implementation planning input, not a source of product requirements.
- The most useful deep modules are upload admission, AnnualReport/FileVersion state, AnalysisRun orchestration, MDA evidence extraction, structured outline validation, report asset store, report rendering/downloads, and QA evidence validation.
- README and developer-facing runbooks should document the real visual-model configuration path, the fact that CI still uses mocks, and the fact that local manual analysis of a real PDF is expected to make real provider calls once credentials are configured.
- The PRD should be split into independently grabbable implementation issues after triage, likely by vertical slices rather than by purely technical layers.
