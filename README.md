# Fin Report Reader v2

Chinese annual-report reader centered on AnnualReport and FileVersion.

## Backend

```powershell
python -m pip install -e ".[dev]"
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.asgi:app --host 127.0.0.1 --port 8000
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Verification

```powershell
python -m pytest -q
cd frontend
npm run build
```
