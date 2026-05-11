<h1 align="center">Fin Report Reader v2</h1>

<p align="center">
  Chinese annual-report reader centered on <code>AnnualReport</code> and <code>FileVersion</code>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/backend-Python%20%2F%20ASGI-blue" alt="Backend" />
  <img src="https://img.shields.io/badge/frontend-Node.js%20based-green" alt="Frontend" />
  <img src="https://img.shields.io/badge/tests-pytest%20%2F%20npm%20test-orange" alt="Tests" />
  <img src="https://img.shields.io/badge/status-active-lightgrey" alt="Status" />
</p>

<p align="center">
  <a href="#english">英文</a> ·
  <a href="#chinese">中文</a> ·

</p>

---

<a id="english"></a>

## English

**Fin Report Reader v2** is a Chinese annual-report reading and analysis project.

The project is organized around two core concepts:

- `AnnualReport`: the business-level annual report entity
- `FileVersion`: the file-level version record associated with a report

It is designed to support PDF upload, report metadata management, deterministic workflow verification, and later AI-assisted report analysis.

<a id="website"></a>

## Website

Project website: not configured yet.

<a id="installation"></a>

## Installation

### Backend

Install the project in editable mode with development dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Apply database migrations:

```powershell
python -m alembic -c backend/alembic.ini upgrade head
```

Start the backend service:

```powershell
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

### Frontend

Install frontend dependencies:

```powershell
cd frontend
npm install
```

Start the frontend development server:

```powershell
npm run dev
```

<a id="architecture"></a>

## Architecture

```text
fin-report-reader-v2/
├─ backend/                         # Backend application and tests
├─ frontend/                        # Frontend application
├─ docs/
│  └─ testing/
│     └─ mocked-ci-workflow.md       # Mocked CI workflow notes
├─ README.md
└─ ...
```

The current architecture is centered on:

- backend service layer
- annual-report business entity
- file-version management
- deterministic test workflow
- frontend interface for future report reading and analysis features

<a id="troubleshooting"></a>

## Troubleshooting

### Backend dependency issues

Try reinstalling the project in editable mode:

```powershell
python -m pip install -e ".[dev]"
```

### Database migration issues

Run Alembic migration again:

```powershell
python -m alembic -c backend/alembic.ini upgrade head
```

### Frontend dependency issues

Reinstall frontend dependencies:

```powershell
cd frontend
npm install
```

<a id="verification"></a>

## Verification

Run backend tests:

```powershell
python -m pytest -q
```

Build the frontend:

```powershell
cd frontend
npm run build
```

Run the deterministic mocked CI workflow test:

```powershell
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
```

Run frontend tests:

```powershell
cd frontend
npm test
```

Coverage mapping and evaluation boundaries are documented in:

```text
docs/testing/mocked-ci-workflow.md
```

<a id="discord"></a>

## Discord

Discord community: not configured yet.

---

<a id="chinese"></a>

## 中文

**Fin Report Reader v2** 是一个面向中文年报的阅读与分析项目。

项目围绕两个核心概念组织：

- `AnnualReport`：年报的业务实体
- `FileVersion`：与年报关联的文件版本记录

该项目当前重点支持 PDF 文件管理、年报元信息建模、可重复的流程验证，并为后续 AI 辅助年报分析提供基础。

### 后端

安装项目及开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

执行数据库迁移：

```powershell
python -m alembic -c backend/alembic.ini upgrade head
```

启动后端服务：

```powershell
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

### 前端

安装前端依赖：

```powershell
cd frontend
npm install
```

启动前端开发服务：

```powershell
npm run dev
```

### 验证

运行后端测试：

```powershell
python -m pytest -q
```

构建前端：

```powershell
cd frontend
npm run build
```

运行可重复的 Mocked CI 工作流测试：

```powershell
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
```

运行前端测试：

```powershell
cd frontend
npm test
```

自动化覆盖范围与评估边界见：

```text
docs/testing/mocked-ci-workflow.md
```
