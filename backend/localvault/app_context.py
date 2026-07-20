import os
import sqlite3
from dataclasses import dataclass

from .config import Config
from .db import connect, init_schema
from .services.session_manager import SessionManager
from .services.backup_manager import BackupManager
from .services.vault_service import VaultService
from .services.import_service import ImportPreviewStore


@dataclass
class AppContext:
    data_dir: str
    config: Config
    conn: sqlite3.Connection
    sessions: SessionManager
    backups: BackupManager
    imports: ImportPreviewStore
    vault: VaultService


def build_context(data_dir: str) -> AppContext:
    os.makedirs(data_dir, exist_ok=True)
    for sub in ("backups", "logs"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
    config = Config(data_dir)
    config.load()
    conn = connect(os.path.join(data_dir, "vault.sqlite3"))
    init_schema(conn)
    sessions = SessionManager()
    backups = BackupManager(data_dir, conn)
    imports = ImportPreviewStore()
    vault = VaultService(conn, data_dir, backups, sessions)
    vault.load()
    return AppContext(
        data_dir=data_dir,
        config=config,
        conn=conn,
        sessions=sessions,
        backups=backups,
        imports=imports,
        vault=vault,
    )
