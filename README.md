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

### First-time setup on WSL / Linux

Create and activate the local virtual environment:

```bash
cd /home/xsw/projects/fin-report-reader-v2
python3 -m venv .venv
source .venv/bin/activate
```

Install backend dependencies:

```bash
python -m pip install -e ".[dev]"
```

Create the local SQLite data directory used by Alembic:

```bash
mkdir -p backend/data
```

Apply database migrations:

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

Install frontend dependencies:

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm install
```

### Daily startup on WSL / Linux

Backend:

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

Optional local figure-vision integration for manual MDA analysis:

```bash
export MDA_FIGURE_VISION_BASE_URL="https://api.openai.com/v1"
export MDA_FIGURE_VISION_API_KEY="sk-..."
export MDA_FIGURE_VISION_MODEL="gpt-4.1-mini"
export MDA_OUTLINE_GENERATION_BASE_URL="https://api.openai.com/v1"
export MDA_OUTLINE_GENERATION_API_KEY="sk-..."
export MDA_OUTLINE_GENERATION_MODEL="gpt-4.1"
```

Notes:

- Figure visual analysis uses the `MDA_FIGURE_VISION_*` variables and sends one figure candidate per Chat Completions-compatible request with an inline data URL image.
- Outline generation keeps its own `MDA_OUTLINE_GENERATION_*` keys for future separation, even though this issue only wires the Figure analyzer.
- CI should continue to inject mocks instead of real model credentials.
- If the figure-vision variables are missing, the app still starts normally, but an analysis run that reaches required figure analysis fails with `VISION_MODEL_UNAVAILABLE`.

Frontend:

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm run dev
```

Open the app at [http://127.0.0.1:5173](http://127.0.0.1:5173).

Notes:

- If `.venv` already exists in the project root, reuse it instead of creating a new one.
- You do not need a separate MySQL or PostgreSQL service. The project uses a local SQLite file at `backend/data/app.db`.
- You do not need to run Alembic on every startup. Run it the first time and again only when new files are added under `backend/migrations/versions/`.

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

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### Database migration issues

Make sure `backend/data` exists, then run Alembic again:

```bash
cd /home/xsw/projects/fin-report-reader-v2
mkdir -p backend/data
source .venv/bin/activate
python -m alembic -c backend/alembic.ini upgrade head
```

### Frontend dependency issues

Reinstall frontend dependencies:

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm install
```

<a id="verification"></a>

## Verification

Run backend tests:

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m pytest -q
```

Build the frontend:

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm run build
```

Run the deterministic mocked CI workflow test:

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
```

Run frontend tests:

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm test
```

Coverage mapping and evaluation boundaries are documented in:

```text
docs/testing/mocked-ci-workflow.md
docs/evaluation/README.md
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

### WSL / Linux 首次安装

创建并激活项目虚拟环境：

```bash
cd /home/xsw/projects/fin-report-reader-v2
python3 -m venv .venv
source .venv/bin/activate
```

安装后端依赖：

```bash
python -m pip install -e ".[dev]"
```

创建 Alembic 使用的本地 SQLite 目录：

```bash
mkdir -p backend/data
```

执行数据库迁移：

```bash
python -m alembic -c backend/alembic.ini upgrade head
```

安装前端依赖：

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm install
```

### WSL / Linux 日常启动

启动后端：

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

启动前端：

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm run dev
```

浏览器打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。

说明：

- 如果项目根目录下已经有 `.venv`，直接复用，不要重复创建。
- 项目使用本地 SQLite 文件 `backend/data/app.db`，不需要额外安装 MySQL 或 PostgreSQL。
- 不需要每次启动都执行 Alembic。首次安装时执行一次；之后只有 `backend/migrations/versions/` 下新增迁移文件时才需要再次执行。

### 验证

运行后端测试：

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m pytest -q
```

构建前端：

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm run build
```

运行可重复的 Mocked CI 工作流测试：

```bash
cd /home/xsw/projects/fin-report-reader-v2
source .venv/bin/activate
python -m pytest -q backend/tests/test_mocked_ci_workflow_journey.py
```

运行前端测试：

```bash
cd /home/xsw/projects/fin-report-reader-v2/frontend
npm test
```

自动化覆盖范围与评估边界见：

```text
docs/testing/mocked-ci-workflow.md
```
