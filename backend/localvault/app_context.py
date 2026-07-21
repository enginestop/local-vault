import os
from dataclasses import dataclass, field
from typing import Any

from .config import Config
from .database.pool import get_pool
from .database.schema import init_schema
from .services.session_manager import SessionManager
from .services.backup_manager import BackupManager
from .services.vault_service import VaultService
from .services.import_service import ImportPreviewStore


@dataclass
class AppContext:
    data_dir: str
    config: Config
    sessions: SessionManager
    backups: BackupManager
    imports: ImportPreviewStore
    vault: VaultService


async def build_context(data_dir: str) -> AppContext:
    os.makedirs(data_dir, exist_ok=True)
    for sub in ("backups", "logs"):
        os.makedirs(os.path.join(data_dir, sub), exist_ok=True)
    config = Config(data_dir)
    config.load()
    pool = get_pool()
    await init_schema(pool)
    sessions = SessionManager()
    backups = BackupManager(data_dir)
    imports = ImportPreviewStore()
    vault = VaultService(data_dir, backups, sessions)
    return AppContext(
        data_dir=data_dir,
        config=config,
        sessions=sessions,
        backups=backups,
        imports=imports,
        vault=vault,
    )
