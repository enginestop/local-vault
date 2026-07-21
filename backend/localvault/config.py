import json
import os
from typing import Optional

CONFIG_FILE = "config.json"
ALLOWED_KEYS = {"format_version", "port", "language", "autostart", "log_level", "instance_id"}


class ConfigError(RuntimeError):
    pass


class Config:
    def __init__(self, data_dir: str) -> None:
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, CONFIG_FILE)
        self.format_version = 1
        self.port: int = 8741
        self.language: str = "id"
        self.autostart: bool = False
        self.log_level: str = "INFO"
        self.instance_id: str = ""
        self._loaded = False

    def load(self) -> None:
        if not os.path.exists(self.path):
            self._ensure_instance_id()
            self.save()
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigError("config.json is unreadable or invalid JSON") from exc
        if not isinstance(data, dict) or set(data) - ALLOWED_KEYS:
            raise ConfigError("config.json contains unsupported fields")
        if data.get("format_version", 1) != 1:
            raise ConfigError("unsupported config format_version")
        port = data.get("port", 8741)
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ConfigError("config port must be an integer from 1024 to 65535")
        language = data.get("language", "id")
        if language not in {"id", "en"}:
            raise ConfigError("config language must be id or en")
        autostart = data.get("autostart", False)
        if not isinstance(autostart, bool):
            raise ConfigError("config autostart must be boolean")
        log_level = data.get("log_level", "INFO")
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("unsupported config log_level")
        instance_id = data.get("instance_id", "")
        try:
            if instance_id:
                import uuid
                instance_id = str(uuid.UUID(instance_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ConfigError("config instance_id must be a UUID") from exc
        self.port = port
        self.language = language
        self.autostart = autostart
        self.log_level = log_level
        self.instance_id = instance_id
        self._ensure_instance_id()
        self._loaded = True

    def save(self) -> None:
        data = {
            "format_version": self.format_version,
            "port": self.port,
            "language": self.language,
            "autostart": self.autostart,
            "log_level": self.log_level,
            "instance_id": self.instance_id,
        }
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def _ensure_instance_id(self) -> None:
        if not self.instance_id:
            import uuid

            self.instance_id = str(uuid.uuid4())
