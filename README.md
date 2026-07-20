# LocalVault

A portable, self-hosted password manager that runs on your local machine and is accessible from any device on your local network.

## Features

- **Self-hosted** — all data stays on your machine, no cloud dependency
- **LAN-accessible** — access your vault from any browser on the same network
- **AES-256-GCM encryption** with Argon2id key derivation
- **Single-user** master-password authentication
- **Password generator** with configurable strength
- **Categories** to organize credentials
- **Trash** with recovery
- **Import/Export** (CSV)
- **Backup** with automatic retention
- **WebSocket** session management

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python, FastAPI, Uvicorn |
| Database | SQLite (encrypted envelope) |
| Crypto | cryptography, argon2-cffi |
| Icons | lucide-react |

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 20+

### Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
source .venv/bin/activate # macOS/Linux
pip install -r requirements.txt
python run.py
```

The server starts on `http://127.0.0.1:8741` by default.

### Frontend Setup (Development)

```bash
npm install
npm run dev
```

The Vite dev server proxies `/api` requests to the backend at `http://127.0.0.1:8741`.

### Production Build

```bash
npm run build
```

This compiles the frontend into `backend/localvault/static/`, so both the API and UI are served from the same origin.

## Project Structure

```
localvault/
├── src/              # React frontend source
├── backend/
│   ├── run.py        # Application launcher
│   ├── localvault/   # FastAPI backend package
│   │   ├── api/      # Route handlers
│   │   ├── crypto/   # Encryption primitives
│   │   ├── domain/   # Domain models
│   │   └── services/ # Business logic
│   └── requirements.txt
├── package.json
└── vite.config.ts
```

## License

MIT
