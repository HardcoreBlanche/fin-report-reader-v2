# Evaluation Dataset and Ground Truth Annotation Plan

This directory defines the human-reviewed evaluation contract for the
AnnualReport/FileVersion/MDA product. It is intentionally separate from CI:
deterministic tests cover behavior and contracts, while evaluation tracks
real-PDF extraction quality, model quality, and ground-truth drift.

## Scope

Issue #11 covers three things:

1. Dataset coverage planning
2. One-JSON-per-sample ground-truth shape
3. Human review criteria and reporting expectations

The goal is to let maintainers add evaluation samples incrementally without
guessing field names, page-number semantics, or what "good enough" means.

## Directory Contract

Recommended layout:

```text
docs/evaluation/
├─ README.md
├─ ground_truth_annotation.schema.json
├─ ground_truth_annotations/
│  ├─ required/
│  │  └─ <sample-id>.json
│  └─ opportunity/
│     └─ <sample-id>.json
└─ samples/
   ├─ required/
   │  └─ <sample-id>.pdf
   └─ opportunity/
      └─ <sample-id>.pdf
```

Each PDF sample should live under `docs/evaluation/samples/` and use the same
`<sample-id>` as its companion ground-truth JSON file under
`docs/evaluation/ground_truth_annotations/`. The JSON should validate against
`ground_truth_annotation.schema.json` before any model-output comparison.

This repo does not need to commit proprietary PDFs. The sample PDF paths may be
local-only and ignored by git; if so, keep the ground-truth JSON plus a stable
external or internal sample identifier and document how reviewers access the
source file.

## Coverage Tiers

### Required coverage

Every evaluation batch should gradually maintain examples for:

- Standard A-share complete Chinese annual report
- ManagementDiscussionAnalysisSection with tables
- ManagementDiscussionAnalysisSection with figures
- Multi-level ManagementDiscussionAnalysisSection headings
- Annual-report summary rejection

### Opportunity coverage

Track separately and do not block baseline development on missing examples:

- Non-Chinese or English rejection
- Hong Kong Chinese annual reports
- A/H-code reports
- Difficult table extraction
- Scanned PDFs
- Unusual but locatable ManagementDiscussionAnalysisSection structure
- Figure-heavy reports

## Ground Truth Rules

### Page numbers

- All page references use physical PDF page numbers starting from `1`.
- Ground-truth page numbers must match the page numbers shown in product evidence
  references such as `PDF 第 N 页`.

### Upload expectations

Each sample must state whether upload admission is expected to succeed.

- Accepted samples should record `normalized_stock_code`, `report_year`,
  `company_full_name`, and optional `company_short_name`.
- Rejected samples should record the expected business or format error code and
  the expected Chinese message.

### MDA section expectations

When upload is accepted, the ground-truth file must define the expected
ManagementDiscussionAnalysisSection boundaries:

- `start_page`
- `end_page`
- locator evidence expectation
- the expected source-section tree used by report detail and evidence mapping

### Evidence expectations

Ground-truth files should identify the evidence that must be recoverable from the
sample when applicable:

- text spans
- tables
- figures
- source-section ownership
- physical page references

These ground-truth files are not meant to pre-author every sentence of a generated
report. They define the minimum evidence anchors needed to decide whether
section location, extraction, referencing, and QA evidence validation are
working.

### QA expectations

Each accepted sample may include question cases that define:

- expected QA status: `answered`, `insufficient_evidence`, or `out_of_scope`
- required evidence ids when the status is `answered`
- forbidden evidence ids when a question should stay unanswered or out of scope

## Review Criteria

A sample should become `required` only after human review confirms all of the
following:

1. The source PDF is stable and legally usable for internal evaluation.
2. The sample exercises one or more target behaviors better than existing
   required samples.
3. Physical page numbers are unambiguous and cross-checked by a reviewer.
4. Upload expectation is clear enough that another reviewer would classify it
   the same way.
5. ManagementDiscussionAnalysisSection boundaries are explicit enough for
   section-location validation.
6. Required text/table/figure evidence anchors are specific, not vague theme
   descriptions.
7. QA cases are scoped to current-evidence behavior, not outside knowledge.

If a sample is useful but any criterion is still unclear, keep it in
`opportunity` until the ambiguity is resolved.

## Evaluation Reporting Contract

Evaluation runs should emit:

- machine-readable per-sample JSON results
- a human-readable Markdown summary

Every run summary should record:

- evaluation timestamp
- sample count
- pass rate
- failed samples
- failure reasons
- manual-review items
- model configuration
- application version
- prompt versions such as `mda_outline_v1`, `figure_summary_v1`, and
  `qa_answer_v1`
- total run time

Initial evaluation reporting is observational only. Hard pass thresholds should
not gate development until the dataset and metrics stabilize.
