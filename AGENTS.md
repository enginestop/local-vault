# LocalVault — Agent Guide

## Stack & entrypoints
- **Frontend:** Vite + React 19 + TypeScript → `src/main.tsx`
- **Backend:** FastAPI (Python 3.13, asyncpg) → `backend/run.py` (port 8741)
- **State monolitik** di `src/App.tsx` (~337 baris), bukan router/lib state
- **Token sesi** di `sessionStorage` (bukan localStorage) — `src/api.ts`
- **Build output** frontend: `backend/localvault/static/` (dilayani FastAPI)

## Commands
```bash
npm run dev          # Vite dev (proksi /api → :8741)
npm run build        # tsc --noEmit + vite build
npm test             # vitest run (jsdom, 4 file, 7 tests)
npm run test:e2e     # playwright test
npm run audit        # npm audit --audit-level=high
```

### Menjalankan backend lokal
Backend butuh PostgreSQL 18 dan `DATABASE_URL`的环境 variabel. Di Windows dengan PostgreSQL default:
```powershell
$env:DATABASE_URL='postgresql://postgres:postgres@localhost:5432/localvault'
.\backend\.venv313\Scripts\python.exe backend\run.py
```
Backend akan otomatis buat/tabel skema saat startup. `localvault` database harus sudah ada (CREATE DATABASE localvault sekali).

Backend test:
```bash
cd backend && .venv313/bin/python -m pytest -q
```
Audit dependency Python:
```bash
uvx pip-audit -r backend/requirements.lock
```

## Setup
```powershell
py -3.13 -m venv backend/.venv313
.\backend\.venv313\Scripts\python.exe -m pip install --require-hashes -r backend/requirements.lock
npm ci
```

## Arsitektur penting
- Semua route API: `/api/v1/*` (13 file route di `backend/localvault/api/`)
- Session **in-memory** (hilang saat server restart)
- DB: asyncpg + PostgreSQL 18, `DATABASE_URL` env, schema v3
- Kripto: AES-256-GCM (payload), Argon2id (KDF), CSPRNG
- Launcher Qt6 opsional (`backend/localvault/launcher/`, butuh PySide6)
- No TLS by design (v1, LAN-only); **jangan expose ke internet tanpa HTTPS**

## Konvensi
- Bahasa utama: **Indonesia** (UI, README, komentar)
- Tidak ada ESLint/Prettier — hanya `tsc` untuk type-checking
- Tidak ada `pyproject.toml` — dependency via `requirements*.txt` + `requirements.lock` (hashed)
- `LOCALVAULT_DATA_DIR` default: `backend/LocalVault-Data/` (gitignored)
- User pertama = Superadmin; registrasi berikutnya `pending`
- Recovery key ditampilkan **sekali saja**

## Testing quirks
- Backend tests: butuh PostgreSQL 18 running, `DATABASE_URL` eksplisit
- Frontend tests: vitest + jsdom via `npm test`
- E2E: Playwright, butuh `npx playwright install` dulu
- **Tidak ada file test backend** saat ini (hanya frontend tests)
- Test wajib pakai direktori terisolasi, jangan sentuh `LocalVault-Data/`

## Docker
```bash
cd deployment
cp .env.example .env   # isi LOCALVAULT_SECRET minimal
docker compose up --build
```
Multi-stage: `node:24-alpine` (build) → `python:3.13-slim` (runtime).
