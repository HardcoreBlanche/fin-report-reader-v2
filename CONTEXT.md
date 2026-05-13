# Fin Report Reader

This context describes a Chinese annual-report reading assistant. The system helps users work with company annual reports and the analysis produced from them.

## Language

**AnnualReport**:
A company's annual report for one fiscal year.
_Avoid_: Report type, PDF file, analysis task

**AnnualReportSource**:
A Chinese PDF that can be recognized as a complete annual report for a StockCode and fiscal year.
_Avoid_: Semiannual report, quarterly report, annual report summary, English annual report

**AnnualReportUploadIntake**:
The backend facade that owns upload intake for AnnualReport admission, duplicate detection, AnnualReport/FileVersion creation, and source PDF write.
_Avoid_: Route glue, AnalysisRun, full-PDF analysis

**FrontendFileVersionWorkflow**:
The frontend facade that owns FileVersion user workflow orchestration, including FileVersion action ordering, API call sequencing, status refresh, confirmation flows, and current report cleanup.
_Avoid_: Page glue, display labels, table/figure rendering, pure presentation helpers

**AnalysisResultDetailInteraction**:
The frontend facade that owns AnalysisResult detail interactions, including table detail loading, QA session state, QA submit flow, QA session copy/download, and report-detail-local error state.
_Avoid_: Page glue, FileVersion workflow, pure layout, report list management, backend access checks

**AnnualReportLibrary**:
The backend facade that owns AnnualReport list and delete user-facing flows, including AnnualReport summary projection, FileVersion delete confirmation shaping, AnnualReport delete confirmation shaping, delete response shaping, and startup-visible library cleanup entrypoint.
_Avoid_: Route glue, upload intake, AnalysisRun lifecycle, current-result access, raw persistence queries, presentation helpers

**StockCode**:
The displayed securities code used to identify the listed company behind an AnnualReport.
_Avoid_: Company name

**NormalizedStockCode**:
The market-qualified securities code used in AnnualReport identity, such as A:600519 or HK:00700.
_Avoid_: Raw stock code, display stock code

**CompanyFullName**:
The Chinese full name used as the primary display name for an AnnualReport.
_Avoid_: Company short name

**CompanyShortName**:
The optional Chinese short name used as a secondary display name for an AnnualReport.
_Avoid_: Company full name

**Exchange**:
The optional securities exchange associated with an AnnualReport.
_Avoid_: AnnualReport identity

**ReportYear**:
The fiscal year named by an AnnualReport title.
_Avoid_: Publication date, upload date, filename year

**FileVersion**:
A specific uploaded PDF source for an AnnualReport.
_Avoid_: AnnualReport, analysis result

**FileVersionState**:
The inferred current state of a FileVersion, derived from its current AnalysisResult first and latest AnalysisRun second.
_Avoid_: Persisted FileVersion status, AnalysisRun status, frontend-only label

**AnalysisResult**:
The successful generated reading output for one analysis run on one FileVersion.
_Avoid_: AnnualReport, FileVersion

**ManagementDiscussionAnalysisExecution**:
The backend facade that owns ManagementDiscussionAnalysisSection execution for one FileVersion/AnalysisRun pair, including section extraction, EvidencePackage construction, figure analysis, outline validation, QA index preparation, and AnalysisResult draft creation.
_Avoid_: Run lifecycle, current-result access, report downloads, QA answer retrieval, route glue

**ManagementDiscussionAnalysisSection**:
The annual report section titled "管理层讨论与分析" that is the only analysis source for an AnalysisResult.
_Avoid_: Full annual report, audit rules, financial-statement extraction

**EvidencePackage**:
The current AnalysisResult-owned evidence package for ManagementDiscussionAnalysisSection source sections, text spans, tables, figures, and section-location evidence.
_Avoid_: Markdown report, generated asset directory, separate evidence namespace

**EvidencePackageProjection**:
The current AnalysisResult-owned projection Module that turns an EvidencePackage into report detail, QA retrieval/index documents, Markdown/ZIP evidence views, and table/figure read models.
_Avoid_: Canonical evidence storage, business validation, run lifecycle

**Figure**:
A visual chart, diagram, or image-based exhibit in the ManagementDiscussionAnalysisSection.
_Avoid_: Table, thumbnail, "有图年报", "无图年报"

**Table**:
A row-and-column data table in the ManagementDiscussionAnalysisSection.
_Avoid_: Figure, image-only table

**AnalysisRun**:
A single execution that generates an AnalysisResult for one FileVersion.
_Avoid_: Task, AnalysisResult

## Relationships

- Exactly one **AnnualReport** exists for a given **NormalizedStockCode** and **ReportYear**.
- An **AnnualReport** is displayed by **CompanyFullName**, with **CompanyShortName** as secondary text.
- **Exchange** is optional and does not participate in AnnualReport identity.
- The system stores one primary **NormalizedStockCode** for an AnnualReport and does not store secondary stock codes.
- An **AnnualReport** may be represented by one or more **FileVersions** over time.
- The same PDF content belongs to one **FileVersion**; different PDF content for the same **AnnualReport** creates a different **FileVersion**.
- Active **FileVersion** records have globally unique `content_hash` values.
- A **FileVersion** is displayed by original filename with upload time as secondary text; the system does not assign user-visible version numbers.
- Uploading a PDF whose `content_hash` matches an active **FileVersion** does not create a duplicate; it returns HTTP 409 with `DUPLICATE_FILE_VERSION`, "该文件已上传", and the existing **AnnualReport** and **FileVersion** summaries.
- `DUPLICATE_FILE_VERSION` uses the same message regardless of analysis state; the response includes the existing FileVersion display status for frontend-specific messaging.
- Uploading different PDF content for an existing **AnnualReport** creates a new **FileVersion** with HTTP 201 and `annual_report_already_exists=true`.
- Any upload that creates a new active **FileVersion** returns HTTP 201; `annual_report_already_exists` distinguishes existing AnnualReport attachment from new AnnualReport creation.
- After a **FileVersion** is deleted, its `content_hash` remains only in historical **AnalysisRun** snapshots; uploading the same PDF later creates a new FileVersion after admission checks.
- Users browse reports by **AnnualReport** first, then choose among its **FileVersions**.
- An **AnnualReport** may show a summary status for navigation only; FileVersion status controls actions.
- AnnualReport summary status priority is: any `analyzing` -> "分析中", else any `analyzed` -> "有报告", else any `analysis_failed` -> "有失败", else any `stopped` -> "已停止", else "未分析".
- An **AnalysisRun** is bound to exactly one **FileVersion**.
- Different **FileVersions** may be analyzed concurrently, but a single **FileVersion** can have only one in-progress **AnalysisRun**.
- If analysis concurrency limits are reached, starting a new **AnalysisRun** returns HTTP 429 with `ANALYSIS_CONCURRENCY_LIMIT_REACHED`, "当前分析任务较多，请稍后再试", and may include `Retry-After`.
- The backend **AnalysisRunLifecycle** Module is the facade for run creation, stop, retry eligibility, result deletion, run-owned cleanup, and startup repair; callers should go through it instead of re-implementing run status transitions or artifact cleanup.
- Starting, stopping, retrying, marking result deletion, cleanup after failed or stopped runs, FileVersion deletion cleanup, AnnualReport deletion cleanup, and startup repair all belong to the **AnalysisRun** lifecycle; callers should not each re-implement run status transitions or run-owned artifact cleanup.
- The backend **AnnualReportLibrary** Module is the facade for AnnualReport list and delete user-facing flows; the route should only forward the request and response, while AnnualReport summary projection, FileVersion delete confirmation, AnnualReport delete confirmation, delete response shaping, and startup-visible library cleanup entrypoint sit behind the Module.
- The frontend **AnalysisResultDetailInteraction** Module is the facade for AnalysisResult detail interactions; the report detail panel should only render and forward events, while table loading, QA session state, QA submit flow, QA session copy/download, and report-detail-local error state sit behind the Module.
- Re-analyzing a **FileVersion** after deleting its **AnalysisResult** creates a new **AnalysisRun**.
- A failed **AnalysisRun** does not create an **AnalysisResult**.
- A **FileVersion** with a failed **AnalysisRun** may be analyzed again directly, creating a new **AnalysisRun** while retaining old failed runs in storage.
- A **FileVersion** with a stopped **AnalysisRun** may be analyzed again directly, creating a new **AnalysisRun** while retaining old stopped runs in storage.
- Historical **AnalysisRuns** are retained for audit and troubleshooting but are not shown in the normal user interface.
- A **FileVersion** current state is inferred from its current **AnalysisResult** when present; otherwise it is inferred from the latest **AnalysisRun**.
- Users do not choose among historical **AnalysisRuns**.
- An in-progress **AnalysisRun** may be stopped by the user by marking the current run as `stopped`; only system errors use `failed`.
- Stop-analysis operation failures use `STOP_ANALYSIS_FAILED` ("停止分析失败") and cleanup failures use `STOP_ANALYSIS_CLEANUP_FAILED` ("停止分析时清理中间结果失败").
- New **AnalysisRun** statuses are `parsing`, `generating`, `ready`, `failed`, `stopped`, and `result_deleted`; new runs do not use `uploaded`.
- User-visible **AnalysisRun** stages are `locating_section`, `extracting_content`, `analyzing_figures`, `generating_report`, `building_qa_index`, and `completed`.
- **AnalysisRun** `status` remains coarse-grained: `parsing` covers section location and content extraction, `generating` covers figure analysis, report generation, and QA indexing, and `ready` means complete.
- **AnalysisRun** `stage` carries the user-visible detailed stage.
- **FileVersion** display statuses are inferred as: `parsing` or `generating` -> `analyzing`, `ready` with an **AnalysisResult** -> `analyzed`, `failed` -> `analysis_failed`, `stopped` -> `stopped`, and `result_deleted` or no run -> `not_analyzed`.
- A `ready` **AnalysisRun** without an accessible **AnalysisResult** is a consistency error and is treated as `failed` with "分析结果缺失".
- Stopping an **AnalysisRun** is terminal: it must stop further PDF analysis and LLM calls, must not create an **AnalysisResult**, and must clean up pages, chunks, Chroma collections, and temporary report output already written by that run.
- Stopped analysis is displayed separately from analysis failure because it is user-initiated.
- A **FileVersion** cannot be deleted while its current **AnalysisRun** is in progress; after the run is stopped, the **FileVersion** may be deleted.
- Report viewing, question answering, and report deletion are performed for a specific **FileVersion**.
- Report downloads are rendered by the backend from the validated **AnalysisResult** structure for the selected **FileVersion**.
- Report detail responses are for interactive rendering and do not return the full Markdown.
- Report detail, question answering, Markdown download, ZIP download, table resource access, and figure image asset access all resolve the selected **FileVersion**'s current **AnalysisResult** through one shared backend access seam, so file-version visibility, current-result lookup, and asset-ownership checks stay aligned.
- Report detail responses include the ManagementDiscussionAnalysisSection source section tree and text-span index for evidence navigation, not one large full-text string.
- Each `source_sections` node includes `text_span_ids`, `table_ids`, and `image_ids` for assets belonging to that source subsection.
- `source_section_id`, `text_span_id`, `table_id`, and `image_id` are stable only within the current **AnalysisResult**; re-analysis may generate new ids.
- User-facing copy uses "管理层讨论与分析", "章节结构", "分析报告", "问答索引", and "证据包"; internal terms such as `MDA`, `source_sections`, `AnalysisResult`, `Chroma`, and `evidence package` are not shown as primary labels.
- Report view and download actions are available only when a **FileVersion** is `analyzed`.
- When an analysis reaches `analyzed`, the frontend automatically selects that **FileVersion** and opens the interactive report detail.
- Automatic report opening applies only to the analysis the user is currently waiting for; background completions show a notification and do not steal focus.
- Question answering is available only for an `analyzed` **FileVersion** with a current **AnalysisResult**.
- **AnalysisResult** records whether question answering is available using `qa_available` and `qa_unavailable_reason`.
- `qa_available=false` means QA indexing was not successfully built during analysis, usually because embedding or Chroma writing failed; it is not a per-question retrieval result.
- When `qa_available=true`, individual QA questions may still return an evidence-insufficient answer without changing `qa_available`.
- If the QA index is unavailable, question answering returns `QA_INDEX_UNAVAILABLE` with "问答暂不可用" and does not change the **AnalysisResult** or FileVersion display state.
- QA questions outside the **ManagementDiscussionAnalysisSection** scope return a successful scoped-answer message saying "当前问答仅基于第三节‘管理层讨论与分析’，无法回答该问题" rather than using outside knowledge.
- Substantive QA answers must include evidence references from the **ManagementDiscussionAnalysisSection**, supporting text, table, and figure evidence.
- QA evidence reuses the current **AnalysisResult** `text_span_id`, `table_id`, and `image_id` assets rather than creating new evidence ids.
- If QA cannot retrieve enough evidence, it returns an unable-to-answer message rather than an unsupported answer.
- QA retrieval prefers Chroma over ManagementDiscussionAnalysisSection chunks and may fall back to keyword search over `structured_outline` and `source_sections` when Chroma returns insufficient evidence.
- QA successful HTTP responses use `status=answered`, `status=insufficient_evidence`, or `status=out_of_scope`; only `answered` requires non-empty evidence.
- QA request and generation errors include `EMPTY_QUESTION` ("问题不能为空"), `QA_GENERATION_FAILED` ("问答生成失败"), and `QA_EVIDENCE_VALIDATION_FAILED` ("问答证据校验失败").
- QA conversations are not persisted, but the frontend supports copying or downloading the current in-page QA session as Markdown.
- QA Markdown exports include concise evidence references but do not package figure or table assets.
- Requesting a missing current **AnalysisResult** returns `ANALYSIS_RESULT_NOT_FOUND` with "该文件版本暂无分析报告".
- **AnalysisResult** is generated only from the **ManagementDiscussionAnalysisSection**.
- **AnalysisResult** and QA must not use information outside the **ManagementDiscussionAnalysisSection**, including other annual-report sections, model background knowledge, or web information.
- Section locator evidence may include table-of-contents text or boundary headings outside the ManagementDiscussionAnalysisSection body; it is allowed only for locating the section and must not be used as analysis-point or QA-answer evidence.
- **AnalysisResult** includes a short overall summary of 3 to 5 sentences based only on the ManagementDiscussionAnalysisSection.
- The top-level summary does not need separate evidence, but it must not introduce facts that are not supported by analysis points.
- **AnalysisResult** summarizes and analyzes the ManagementDiscussionAnalysisSection by its own subsections rather than by a pre-defined business taxonomy.
- **AnalysisResult** stores a validated loose `structured_outline`; downloadable Markdown is rendered from that validated structure.
- **AnalysisResult** includes one current **EvidencePackage** used to verify and render the analysis.
- The **EvidencePackage** is the canonical registry for `source_sections`, `text_spans`, structured tables, figures, and section locator evidence for that AnalysisResult.
- The **EvidencePackage** shares the **AnalysisResult** lifecycle and is deleted by the same delete, stop, and FileVersion deletion rules.
- The **EvidencePackageProjection** Module renders report detail, Markdown, ZIP, and QA views from the current **EvidencePackage** and does not create separate evidence ids.
- **AnalysisResult** structured content is stored primarily as JSON while the structure evolves; only list or query fields such as `qa_available`, `created_at`, and `analysis_run_id` need separate columns.
- Structured table data is stored in the **AnalysisResult** JSON and emitted as `tables/{table_id}.json` when generating ZIP downloads.
- `structured_outline` uses a stable loose hierarchy with `summary`, `source_sections`, `analysis_sections`, `points`, and `evidence`.
- `source_sections` are canonically owned by the **EvidencePackage** and preserve the ManagementDiscussionAnalysisSection source subsection tree for location, evidence, and asset ownership.
- When `structured_outline` exposes `source_sections`, it is a projection or mirror of the **EvidencePackage** tree and must not be independently modified by the model or UI.
- `analysis_sections` are model-generated report sections that may synthesize across source subsections.
- Recommended `analysis_sections` themes are business and operating model, industry environment, operating performance, core competitiveness and strengths, risks and weaknesses, and future development direction.
- The recommended themes are not a whitelist; important ManagementDiscussionAnalysisSection content outside those themes must still be summarized in additional or renamed analysis sections.
- Recommended analysis sections are ordered as business and operating model, industry environment, operating performance, core competitiveness and strengths, risks and weaknesses, future development direction, then other important content.
- Recommended themes with no supporting content are skipped rather than shown as "未披露".
- Each analysis point references `source_section_id` values and evidence.
- A single analysis point may reference multiple `source_section_ids`; each evidence item has its own `source_section_id`.
- Each evidence reference item includes `content_type`, `source_section_id`, physical PDF `page`, short `evidence_text`, and exactly one typed id matching its type: `text_span_id`, `table_id`, or `image_id`.
- Evidence items are not capped in storage, are ordered by importance, and the UI initially shows only the first few with an option to view all.
- Analysis point counts are not capped, but points must be high-signal, non-duplicative, and evidence-backed.
- Backend validation drops analysis points without evidence and drops analysis sections left with no points.
- If no valid evidence-backed points remain after validation, the **AnalysisRun** fails with `ANALYSIS_OUTPUT_NO_VALID_EVIDENCE` and "分析结果缺少可验证证据".
- Dropped evidence-free points are recorded in internal logs or debug fields, not shown in the user-facing report.
- Invalid model `structured_outline` output, including schema violations or nonexistent `table_id` or `image_id` references, may be retried once with validation errors supplied back to the model.
- If output validation still fails after retry, schema failures use `ANALYSIS_OUTPUT_VALIDATION_FAILED` with "分析结果结构校验失败".
- If output validation still references nonexistent tables after retry, it uses `ANALYSIS_OUTPUT_INVALID_TABLE_REFERENCE` with "分析结果引用了不存在的表格".
- If output validation still references nonexistent figures after retry, it uses `ANALYSIS_OUTPUT_INVALID_FIGURE_REFERENCE` with "分析结果引用了不存在的图".
- If both table and figure references are invalid after retry, it uses `ANALYSIS_OUTPUT_INVALID_ASSET_REFERENCE` with "分析结果引用了不存在的图表资源".
- If clear source subsections are unexpectedly missing, the model may infer source sections from paragraphs and layout and mark `section_source="inferred"`.
- Figure information enters `structured_outline` as `figure_summary` evidence referenced by analysis points, not as a separate top-level figure module.
- Figure evidence in `structured_outline` includes `image_id`, `page`, `evidence_text`, and `content_type=figure_summary`.
- Figure summaries include relevance to business or financial analysis, such as `relevance` or `is_relevant_to_analysis`, with a reason.
- Low-relevance figures are not used in main analysis points; interactive reports place them in a collapsed "其他图示" area for the corresponding subsection, and Markdown reports place them under "其他图示".
- Figure relevance and summary quality require evaluation with manually labeled annual-report examples; detailed test design is deferred until report-analysis behavior is fully defined.
- Model judgment about skipping unsupported themes and adding extra important themes requires later report-analysis evaluation.
- Testing is divided into TDD automated tests for deterministic logic and API contracts, evaluation datasets for PDF/table/figure/LLM quality, and a small set of end-to-end workflow tests.
- Evaluation datasets distinguish required coverage from opportunity coverage; missing rare examples are recorded as gaps but do not block development.
- End-to-end workflow tests cover valid upload through report auto-open, annual-report summary rejection, stop and re-analyze, delete report and re-analyze, interactive report assets and downloads, QA response statuses, FileVersion deletion, and AnnualReport deletion.
- Automated CI/E2E tests use mocks or fixtures instead of real LLM, embedding, or visual-model calls; manual evaluation runs may use real models.
- Required evaluation examples include standard A-share Chinese complete annual reports, A-share reports with tables in the ManagementDiscussionAnalysisSection, A-share reports with figures, A-share reports with multi-level headings, and annual-report summary rejection examples.
- Opportunity evaluation examples include non-Chinese or English rejection examples, Hong Kong Chinese annual reports, A/H-code reports, difficult table extraction or scanned PDFs, unusual but locatable ManagementDiscussionAnalysisSection structure, and figure-heavy complex reports.
- Evaluation annotations use one JSON file per PDF sample.
- Evaluation annotation page numbers use physical PDF page numbers, matching product evidence references.
- Evaluation annotations are validated by an evolving `evaluation_annotation.schema.json` before model-output comparison.
- Evaluation runs output machine-readable JSON per-sample results and a human-readable Markdown summary with pass rates, failed samples, failure reasons, and manual-review items.
- Evaluation runs initially report results without blocking development; thresholds may be added after the dataset and metrics stabilize.
- Evaluation runs may call real models and record model configuration, run time, application version, and prompt version for traceability.
- Key prompts use explicit versions such as `mda_outline_v1`, `figure_summary_v1`, and `qa_answer_v1`; prompt changes bump versions and are recorded in evaluation results.
- Table evidence in `structured_outline` includes `table_id`, `page`, `evidence_text`, and `content_type=table`, and the structured table data is saved as a report asset.
- Text evidence in `structured_outline` includes `text_span_id`, `page`, `evidence_text`, and `content_type=text`.
- A `text_span_id` identifies a paragraph or continuous text block in the **ManagementDiscussionAnalysisSection**, not a whole page; it includes `page` and preferably `bbox` or `order_index`.
- Text span assets are returned with the report detail through `source_sections` and a text-span index; they do not require a separate asset endpoint.
- Interactive report views initially show table names and summary analysis; users can open the original structured table on demand.
- Evidence references can jump to table resources.
- Table resources are accessed through a controlled API that verifies the table belongs to the FileVersion's current **AnalysisResult**.
- Table resource responses are structured JSON with `table_id`, `title`, `page`, `columns`, `rows`, `notes`, and optional `source_bbox`.
- Report detail responses include table metadata with `table_url` for loading full rows on demand.
- Markdown reports include table names and summary analysis rather than full large tables.
- Report detail, asset, and download errors include `ANALYSIS_RESULT_NOT_FOUND` ("该文件版本暂无分析报告"), `FIGURE_ASSET_NOT_FOUND` ("图表资源不存在"), `TABLE_ASSET_NOT_FOUND` ("表格资源不存在"), `UNSUPPORTED_REPORT_DOWNLOAD_FORMAT` ("不支持的报告下载格式"), `REPORT_ZIP_GENERATION_FAILED` ("报告 ZIP 生成失败"), and `REPORT_MARKDOWN_GENERATION_FAILED` ("报告 Markdown 生成失败").
- The LLM may choose the most natural organization for the ManagementDiscussionAnalysisSection content; the system does not predefine how business lines must be summarized.
- **AnalysisResult** covers business/products/services, business model, industry conditions, operating performance, core competitiveness, risk factors, main operations, and future development when those themes appear in the section.
- **AnalysisResult** conclusions include page references and short evidence text.
- Analysis of the **ManagementDiscussionAnalysisSection** must include relevant information from figures and tables, not only narrative text.
- Figure detection first excludes obvious non-body assets such as headers, footers, logos, watermarks, backgrounds, tiny icons, and repeated decorative elements.
- Remaining images are sent to the visual model to decide whether they are informational, returning `is_informational` and a reason.
- Images judged informational become **Figures** and require summaries and evidence; images the visual model cannot classify are temporarily treated as informational.
- **Tables** in the **ManagementDiscussionAnalysisSection** must be parsed into structured data before LLM analysis.
- An image-only table that cannot be parsed into structured rows and columns is treated as a **Figure** for visual analysis until structured table extraction is available; only structured row-and-column evidence is a **Table**.
- **Figures** generally require visual-model analysis of the original cropped figure asset; text extraction alone is not considered sufficient.
- Do not classify AnnualReports as "with figures" or "without figures"; the meaningful distinction is whether the **ManagementDiscussionAnalysisSection** contains **Figures** that require visual analysis.
- If figure or table information in the **ManagementDiscussionAnalysisSection** cannot be analyzed, the entire analysis fails with a clear reason; incomplete AnalysisResults must not be generated.
- If the **ManagementDiscussionAnalysisSection** contains **Figures** that require visual analysis and the visual model is unavailable, analysis fails with `VISION_MODEL_UNAVAILABLE` and "视觉模型不可用，无法分析管理层讨论与分析中的图表".
- If the **ManagementDiscussionAnalysisSection** contains no **Figures**, visual model availability is not required.
- ManagementDiscussionAnalysisSection table parsing failure uses `TABLE_ANALYSIS_FAILED` with "管理层讨论与分析中的表格无法识别".
- ManagementDiscussionAnalysisSection figure analysis failure uses `CHART_ANALYSIS_FAILED` with "管理层讨论与分析中的图表无法识别".
- If both figure and table analysis fail, the failure may use `VISUAL_CONTENT_ANALYSIS_FAILED` with "管理层讨论与分析中的图表或表格无法识别".
- ManagementDiscussionAnalysisSection text extraction failure uses `MD_A_TEXT_EXTRACTION_FAILED` with "管理层讨论与分析中的文本无法识别".
- QA indexing covers only the **ManagementDiscussionAnalysisSection**, including text, structured table content, and figure visual summaries.
- ManagementDiscussionAnalysisSection content should be chunked into Chroma with metadata including `file_version_id`, `analysis_run_id` or `task_id`, `section`, `subsection_title`, `page`, and `content_type`.
- Chroma collections are named by **AnalysisRun** implementation id (`task_id`), not by **FileVersion**.
- Chroma write failure does not fail the **AnalysisRun** when the **AnalysisResult** report itself was generated; it sets `qa_available=false` and records `qa_unavailable_reason`.
- Embedding unavailability is treated like QA indexing failure: it does not block **AnalysisResult** creation and sets `qa_available=false`.
- Deleting an **AnalysisResult**, stopping an **AnalysisRun**, or deleting a **FileVersion** cleans up the corresponding Chroma collection.
- Evidence page references use physical PDF page numbers and are displayed as "PDF 第 N 页".
- Rendered Markdown reports include the original figure images alongside figure-based analysis when figure evidence is used.
- Interactive report views show figure images by default at a fitted size with figure summaries, and users may open them larger.
- Figure images used in analysis are cropped and stored as controlled local report assets.
- Figure image assets record `image_id`, `page`, `bbox`, `caption` or `title`, and `source_file_version_id`.
- Figure image assets are stored under an **AnalysisRun** asset directory such as `backend/data/report_assets/{task_id}/figures/{image_id}.png` and `thumbs/{image_id}.png`.
- In-progress analysis writes figure assets to a temporary report-assets directory such as `report_assets/_tmp/{task_id}`; assets become official only after **AnalysisResult** creation succeeds.
- AnalysisResult commit order is: prepare assets, promote assets, save **AnalysisResult** pointing to official assets, then mark the **AnalysisRun** `ready`.
- If asset promotion fails, the **AnalysisRun** fails and no **AnalysisResult** is created; if saving the AnalysisResult fails after promotion, promoted assets are cleaned up.
- Asset and result persistence failures use `FIGURE_ASSET_SAVE_FAILED` ("图表资源保存失败"), `REPORT_ASSET_COMMIT_FAILED` ("报告资源保存失败"), and `ANALYSIS_RESULT_SAVE_FAILED` ("分析报告保存失败").
- QA indexing is attempted after validated outline generation and asset promotion but before saving **AnalysisResult** so that `qa_available` reflects the index result.
- QA indexing failure does not roll back report assets or fail the **AnalysisRun**; it is saved as `qa_available=false`.
- If saving **AnalysisResult** fails after QA indexing succeeds, promoted assets and the Chroma collection are cleaned up and the **AnalysisRun** is marked failed.
- Report downloads support plain Markdown and a ZIP package containing Markdown plus referenced figure image assets.
- Plain Markdown downloads keep figure image references, figure summaries, and page references, and warn that offline image retention requires ZIP download.
- Plain Markdown downloads include table names, summaries, page references, and a reminder to download ZIP for complete tables; they do not include full large tables.
- Markdown rendering includes a concise evidence list after each analysis point.
- ZIP report downloads use relative paths for figure image assets.
- ZIP report downloads include `tables/{table_id}.json` for structured table assets and may include CSV exports.
- Figure image assets are accessed through a controlled API that verifies the image belongs to the FileVersion's current **AnalysisResult**.
- Figure image asset access supports `variant=thumb|original`, defaults to `thumb`; visual analysis uses original cropped images, and ZIP downloads include original cropped images.
- Report detail responses include figure metadata with `thumb_url` and `original_url` pointing to the controlled figure asset API.
- Thumbnail generation is a presentation optimization; failure to create a thumbnail does not fail analysis if the original cropped figure asset is available.
- Figure analysis fails the **AnalysisRun** when the original figure region cannot be located or extracted, the original figure asset cannot be saved, visual analysis cannot be linked to `image_id`, `page`, and `bbox` evidence, or the visual model cannot produce any figure summary.
- A figure summary that turns out to be irrelevant to the desired business or financial analysis does not fail the **AnalysisRun**.
- Missing figure titles do not fail analysis when the figure can still be cited by `page` and `bbox`.
- Deleting an **AnalysisResult** or **FileVersion** deletes associated figure image assets.
- Stopping an **AnalysisRun** deletes figure image assets already created by that run; figure assets become report assets only after **AnalysisResult** creation succeeds.
- **ManagementDiscussionAnalysisSection** range is located from the "第三节 管理层讨论与分析" heading to before the next same-level section heading.
- Analysis first uses the table of contents to locate the section start and end pages; if that fails, it finds the section heading in the first 20 PDF pages and then searches for the next same-level section heading.
- A table-of-contents location for **ManagementDiscussionAnalysisSection** must be verified by finding the section heading in the corresponding body pages.
- If the section start cannot be verified in the body, analysis fails with "无法验证管理层讨论与分析起始位置".
- If the end of **ManagementDiscussionAnalysisSection** cannot be determined, analysis fails with "无法确定管理层讨论与分析结束位置".
- ManagementDiscussionAnalysisSection location failures use `MD_A_SECTION_NOT_FOUND` ("无法定位管理层讨论与分析"), `MD_A_SECTION_START_UNVERIFIED` ("无法验证管理层讨论与分析起始位置"), and `MD_A_SECTION_END_NOT_FOUND` ("无法确定管理层讨论与分析结束位置").
- PDF parsing for analysis is defined by producing a structured evidence package for the **ManagementDiscussionAnalysisSection**, not by producing Markdown alone.
- PDF-to-Markdown conversion may be used as an auxiliary parsing step, and any extracted tables or figures may be reused, but Markdown conversion is not considered sufficient evidence-package extraction by itself.
- A **FileVersion** that has already been analyzed should not be analyzed again until its existing report is deleted by explicit user confirmation.
- A **FileVersion** has at most one current **AnalysisResult**.
- Deleting an **AnalysisResult** removes generated artifacts but keeps the **AnnualReport**, **FileVersion**, and historical **AnalysisRun** record.
- The historical **AnalysisRun** left after deleting an **AnalysisResult** is marked as `result_deleted`, not `ready`.
- Delete-analysis-result failures use `DELETE_ANALYSIS_RESULT_FAILED` ("删除分析报告失败") and `DELETE_ANALYSIS_ARTIFACTS_FAILED` ("删除分析产物失败").
- Deleting a **FileVersion** through the system deletes that **FileVersion** and its **AnalysisResult** together after one explicit confirmation.
- Delete-FileVersion failures use `DELETE_FILE_VERSION_FAILED` ("删除文件版本失败"), `DELETE_SOURCE_PDF_FAILED` ("删除源 PDF 失败"), and `DELETE_EMPTY_ANNUAL_REPORT_FAILED` ("删除空年报失败").
- An **AnalysisResult** is only available in the system while its source **FileVersion** and PDF are available in the system.
- Deleting the last **FileVersion** of an **AnnualReport** deletes the empty **AnnualReport**.
- Deleting an **AnnualReport** through the system deletes all of its **FileVersions**, source PDFs, current **AnalysisResults**, and generated artifacts after explicit confirmation.
- Deleting an **AnnualReport** is allowed only when none of its **FileVersions** are currently analyzing; it deletes FileVersions in any other display state.
- AnnualReport deletion confirmation shows the number of FileVersions and AnalysisResults that will be deleted.
- Delete-AnnualReport errors include `ANNUAL_REPORT_NOT_FOUND` ("年报不存在"), `ANNUAL_REPORT_HAS_ANALYSIS_IN_PROGRESS` ("该年报下有文件版本正在分析，请先停止分析"), `DELETE_ANNUAL_REPORT_FAILED` ("删除年报失败"), and `DELETE_ANNUAL_REPORT_FILE_VERSIONS_FAILED` ("删除年报文件版本失败").
- Delete actions require explicit confirmation.
- Startup cleanup removes any **FileVersion** whose physical PDF is missing, removes its current **AnalysisResult** artifacts, and deletes the empty **AnnualReport** if no FileVersions remain.
- Startup cleanup removes orphan report asset directories that do not belong to any current valid **AnalysisResult**.
- Historical **AnalysisRuns** may remain for audit after startup cleanup, but they must no longer point to a visible FileVersion.
- After a **FileVersion** is deleted, historical **AnalysisRuns** are retained only as audit records with source snapshots, not as strong references to a visible FileVersion.
- Historical **AnalysisRun** source snapshots include `original_filename`, `content_hash`, `normalized_stock_code`, `report_year`, `company_full_name`, and `file_version_deleted_at`.
- Missing or deleted FileVersion resources return HTTP 404 with `FILE_VERSION_NOT_FOUND` and "文件版本不存在".
- A PDF that does not yield a **StockCode** is rejected during upload.
- A PDF that does not yield a fiscal year is rejected during upload.
- A PDF source must be recognized as an **AnnualReportSource** during upload before it can be analyzed.
- Non-annual reports are rejected during upload even if they yield **StockCode** and fiscal year.
- Annual report summaries are rejected during upload; only complete annual reports are accepted.
- Annual reports whose main body is not Chinese are rejected during upload.
- Upload admission must be based on text extracted from the PDF body; filenames may only assist recognition.
- The backend **AnnualReportUploadIntake** Module owns upload intake as a facade: the route only forwards the request and response, while admission, duplicate detection, AnnualReport/FileVersion creation, and source PDF write sit behind the Module.
- The frontend **FrontendFileVersionWorkflow** Module owns FileVersion user workflow orchestration as a facade: the page only renders and forwards events, while FileVersion action sequencing, API call ordering, status refresh, confirmation flows, and current report cleanup sit behind the Module.
- Upload admission uses the first PDF page and the "公司简介和主要财务指标" section as recognition evidence; it does not parse the full PDF.
- **StockCode** and **CompanyFullName** must come from structured fields or table extraction in "公司简介和主要财务指标".
- **CompanyShortName** should come from the same structured section when available, but it is optional.
- If **StockCode** or **CompanyFullName** can only be guessed from free text, headers, filenames, or regular-expression matches, upload is rejected with the corresponding extraction-failure reason.
- **StockCode** is read from the stock-code field in "公司简介和主要财务指标", preferring A-share codes and then Hong Kong stock codes.
- **NormalizedStockCode** carries market semantics and is used with **ReportYear** as the AnnualReport identity.
- **ReportYear** is read from the annual-report title such as "2024 年年度报告"; the latest financial-data dates in "公司简介和主要财务指标" may be used for cross-checking.
- Publication date, PDF creation date, upload date, and filename year must not substitute for **ReportYear**.
- If a PDF lists multiple stock codes, upload binds the AnnualReport to the A-share code when present; otherwise it binds to the Hong Kong stock code.
- Hong Kong stock-code support is allowed but not a core required capability for the current version.
- If separate uploads bind the same **CompanyFullName** to different market codes for the same fiscal year, the system treats them as separate AnnualReports.
- AnnualReports with the same **CompanyFullName** and fiscal year but different **NormalizedStockCode** values are displayed as separate list entries with the normalized code shown prominently.
- Upload admission must not choose a **StockCode** by taking the first code-like number from arbitrary body text.
- Upload admission first tries to find the table of contents in the first 10 PDF pages, then uses it to locate "公司简介和主要财务指标".
- If table-of-contents location fails, upload admission tries to find the "公司简介和主要财务指标" section start in the first 20 PDF pages.
- If both section-location strategies fail, upload is rejected with a specific reason.
- If the annual-report title year conflicts with the latest financial-data dates in "公司简介和主要财务指标", upload is rejected with a specific reason.
- If upload admission cannot extract financial-data dates from "公司简介和主要财务指标", upload is rejected with "表格提取日期失败".
- Upload admission failures return a machine-readable error code and a user-readable Chinese message.
- Business error responses use `error_code`, `message`, and optional safe `details`; stack traces and internal paths are not exposed.
- Invalid PDF format or header failures return HTTP 400; valid PDFs that fail annual-report admission return HTTP 422.
- Upload format errors include `INVALID_FILE_EXTENSION` ("仅支持 PDF 文件"), `INVALID_PDF_HEADER` ("文件内容不是有效 PDF"), and `INVALID_PDF_FILE` ("PDF 文件无法读取").
- Upload annual-report admission errors include `NOT_AN_ANNUAL_REPORT` ("当前仅支持年度报告"), `ANNUAL_REPORT_SUMMARY_NOT_SUPPORTED` ("当前仅支持完整年度报告，不支持年度报告摘要"), and `NON_CHINESE_ANNUAL_REPORT` ("当前仅支持中文年度报告").
- Upload section-location errors include `COMPANY_PROFILE_SECTION_NOT_FOUND` ("无法定位公司简介和主要财务指标").
- Upload identity extraction errors include `MISSING_STOCK_CODE` ("无法识别股票代码"), `AMBIGUOUS_STOCK_CODE` ("股票代码不唯一"), `MISSING_REPORT_YEAR` ("无法识别报告年度"), and `MISSING_COMPANY_FULL_NAME` ("无法识别公司全称").
- Upload consistency errors include `COMPANY_FULL_NAME_MISMATCH` ("首页公司名与公司全称不匹配"), `REPORT_YEAR_MISMATCH` ("报告年度不一致"), and `ANNUAL_REPORT_IDENTITY_CONFLICT` ("该股票代码和年度已存在年报，但公司全称不一致").
- Upload financial-date extraction failure uses `TABLE_DATE_EXTRACTION_FAILED` ("表格提取日期失败") and is distinct from ManagementDiscussionAnalysisSection table analysis failures.
- Successful upload returns separate **AnnualReport** and **FileVersion** summaries.
- In grouped list responses, **AnnualReport** summary fields are shown at the AnnualReport level, not repeated inside each **FileVersion**.
- AnnualReport list errors include `ANNUAL_REPORT_LIST_FAILED` ("获取年报列表失败") and `INVALID_ANNUAL_REPORT_FILTER` ("筛选条件无效").
- If multiple stock codes are present and the primary **StockCode** cannot be determined, upload is rejected with a specific reason.
- The first-page company name must match **CompanyFullName** after minimal text normalization; otherwise upload is rejected with a full-name mismatch reason.
- Company-name normalization may remove whitespace, line breaks, common separators, and full-width or half-width form differences, but it must not use abbreviation matching, synonym matching, or fuzzy edit-distance matching.
- If a new **FileVersion** has the same **StockCode** and fiscal year as an existing **AnnualReport** but a different **CompanyFullName**, upload is rejected.

## Example Dialogue

> **Dev:** "If the user uploads the same company's annual report PDF twice, are those two AnnualReports?"
> **Domain expert:** "No - they are files for the same AnnualReport if they represent the same company and fiscal year."

## Flagged Ambiguities

- "AnnualReport" was previously described as "company + year + report type"; resolved: it means only a company's annual report for one fiscal year.
- Missing **StockCode** is not a user-completable metadata gap; resolved: it means the PDF cannot currently be recognized as a usable AnnualReport source.
- Recognition failure must identify whether **StockCode**, fiscal year, or both are missing.
- AnnualReport recognition was previously deferred until analysis starts; resolved: recognition happens during upload.
- Unrecognized PDFs are not retained or listed; resolved: upload fails with a specific recognition reason and leaves no persistent record.
- "Report type" is not part of **AnnualReport** identity; resolved: annual-report type is an upload admission rule.
- Filename-only recognition is insufficient; resolved: PDF body extraction must support upload admission.
- A physical PDF may be removed outside the system; resolved: its **AnalysisResult** must not remain available in the system.
- "Task" is the current implementation name for **AnalysisRun**; resolved: domain language uses **AnalysisRun**.
- Previous report modules such as overview, hard rules, financial analysis, extracts, and full-report markdown are no longer AnalysisResult requirements; resolved: analysis focuses only on "管理层讨论与分析".
- Rigid business-entry extraction rules were considered and rejected; resolved: summarize and analyze "管理层讨论与分析" according to its own subsection structure and let the LLM choose the natural organization.
