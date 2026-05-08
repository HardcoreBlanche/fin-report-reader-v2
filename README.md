# Fin Report Reader v2

[English](#english) | [中文](#chinese)

<a id="english"></a>
## English

Chinese annual-report reader centered on AnnualReport and FileVersion.

### Contents

- [Backend](#en-backend)
- [Frontend](#en-frontend)
- [Verification](#en-verification)
- [Mocked CI Journey (Deterministic)](#en-mocked-ci-journey-deterministic)

<a id="en-backend"></a>
### Backend

```powershell
python -m pip install -e ".[dev]"
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

<a id="en-frontend"></a>
### Frontend

```powershell
cd frontend
npm install
npm run dev
```

<a id="en-verification"></a>
### Verification

```powershell
python -m pytest -q
cd frontend
npm run build
```

<a id="en-mocked-ci-journey-deterministic"></a>
### Mocked CI Journey (Deterministic)

```powershell
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
cd frontend
npm test
```

Coverage mapping and evaluation boundaries are documented in
`docs/testing/mocked-ci-workflow.md`.

---

<a id="chinese"></a>
## 中文

以 `AnnualReport` 和 `FileVersion` 为核心的中文年报阅读与分析工具。

### 目录

- [后端](#zh-backend)
- [前端](#zh-frontend)
- [验证](#zh-verification)
- [Mocked CI 旅程（可重复）](#zh-mocked-ci)

<a id="zh-backend"></a>
### 后端

```powershell
python -m pip install -e ".[dev]"
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

<a id="zh-frontend"></a>
### 前端

```powershell
cd frontend
npm install
npm run dev
```

<a id="zh-verification"></a>
### 验证

```powershell
python -m pytest -q
cd frontend
npm run build
```

<a id="zh-mocked-ci"></a>
### Mocked CI 旅程（可重复）

```powershell
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
cd frontend
npm test
```

自动化覆盖范围与评估边界见：
`docs/testing/mocked-ci-workflow.md`。
