# Mocked CI Workflow: Complete Annual-Report Journey

## Goal

Keep CI deterministic while still covering the supported
AnnualReport/FileVersion/MDA journey end to end.

## Deterministic policy

- CI uses fixtures and fake collaborators only.
- CI does not call real LLM, embedding, visual-model, or external PDF services.
- CI does not run manual evaluation harnesses.

## Automated CI coverage

### Backend mocked journey

- Command: `python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py`
- Test coverage:
  - `test_mocked_ci_journey_covers_complete_annual_report_flow`
  - `test_mocked_ci_rejects_annual_report_summary_with_stable_error_contract`
- Behaviors covered:
  - Valid upload
  - AnnualReport-first browsing and FileVersion selection
  - Duplicate upload handling
  - Analysis start/progress states
  - Report detail retrieval
  - Markdown/ZIP download
  - QA
  - AnalysisResult deletion
  - Stop and re-analyze
  - FileVersion deletion
  - AnnualReport deletion
  - Annual-report summary rejection
  - API contracts, state transitions, and artifact lifecycle outcomes

### Frontend deterministic behavior

- Command: `npm --prefix frontend test`
- Relevant assertions in `frontend/tests/uploadPresentation.test.cjs`:
  - Foreground report auto-open on `ready`
  - Background completion notification without focus stealing
  - Duplicate upload message formatting
  - Display-status action gating

## Quality behavior kept in evaluation (not CI-gated)

- Real-PDF extraction robustness on diverse production documents
- Real model quality for outline generation, figure interpretation, and QA answer quality
- Evaluation dataset pass/fail trends and annotation quality checks

## Local run

```powershell
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
cd frontend
npm test
```
