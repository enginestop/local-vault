import json
import os
import sys
import threading

import pytest

from localvault.config import Config, ConfigError
from localvault.launcher.autostart import AutostartManager
from localvault.launcher.control import ControlBridge
from localvault.launcher.main import filesystem_probe
from localvault.launcher.server import ServerWorker
from localvault.logging_setup import configure_file_logging


def test_control_bridge_is_thread_safe():
    bridge = ControlBridge()
    worker = threading.Thread(target=lambda: bridge.process_one({"sum": lambda payload: payload["a"] + payload["b"]}, timeout=1))
    worker.start()
    assert bridge.request("sum", {"a": 2, "b": 3}, timeout=2) == 5
    worker.join(timeout=2)


def test_linux_autostart_only_manages_localvault_entry(tmp_path):
    home = tmp_path / "home"
    other = home / ".config" / "autostart" / "other.desktop"
    other.parent.mkdir(parents=True)
    other.write_text("keep", encoding="utf-8")
    manager = AutostartManager(str(tmp_path / "LocalVault"), platform="linux", home=str(home))
    manager.set_enabled(True)
    entry = other.parent / "localvault.desktop"
    assert 'Name=LocalVault' in entry.read_text(encoding="utf-8")
    manager.set_enabled(False)
    assert not entry.exists()
    assert other.read_text(encoding="utf-8") == "keep"


def test_config_corruption_is_fatal_and_not_overwritten(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"port": "not-a-port"}', encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ConfigError):
        Config(str(tmp_path)).load()
    assert path.read_bytes() == original


def test_filesystem_probe_leaves_no_plaintext_probe(tmp_path):
    filesystem_probe(str(tmp_path))
    assert sorted(item.name for item in tmp_path.iterdir()) == ["backups", "logs"]


def test_windowed_server_does_not_require_console_streams(tmp_path, monkeypatch):
    configure_file_logging(str(tmp_path), "INFO")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    worker = ServerWorker(str(tmp_path), 8741, "INFO", ControlBridge(), sys.executable)
    assert worker.server.config.log_config is None
    assert (tmp_path / "logs" / "localvault.log").is_file()
