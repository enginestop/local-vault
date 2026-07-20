import json
import os
from typing import Optional

CONFIG_FILE = "config.json"


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
        except Exception:
            # Corrupt config: keep defaults but do not overwrite blindly
            self._ensure_instance_id()
            return
        self.format_version = int(data.get("format_version", 1))
        port = int(data.get("port", 8741))
        if 1024 <= port <= 65535:
            self.port = port
        self.language = data.get("language", "id")
        self.autostart = bool(data.get("autostart", False))
        self.log_level = data.get("log_level", "INFO")
        self.instance_id = data.get("instance_id", "")
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
