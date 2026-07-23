import os
import uvicorn
from localvault.main import create_app

DATA_DIR = os.environ.get("LOCALVAULT_DATA_DIR", os.path.join(os.path.dirname(__file__), "LocalVault-Data"))
PORT = int(os.environ.get("LOCALVAULT_PORT", os.environ.get("PORT", "8741")))
HOST = os.environ.get("LOCALVAULT_HOST", os.environ.get("HOST", "0.0.0.0"))


def run() -> int:
    os.makedirs(DATA_DIR, exist_ok=True)
    app = create_app(DATA_DIR)
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
