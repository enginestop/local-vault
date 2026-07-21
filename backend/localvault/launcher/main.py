from __future__ import annotations

import ctypes
import os
import socket
import sys
import webbrowser
from pathlib import Path

from ..config import Config, ConfigError
from ..logging_setup import configure_file_logging
from .control import ControlBridge
from .server import ServerWorker

LOCK_FILENAME = "localvault.lock"


def portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_data_dir() -> str:
    return str(portable_root() / "LocalVault-Data")


def acquire_instance_lock(data_dir: str):
    os.makedirs(data_dir, exist_ok=True)
    descriptor = os.open(os.path.join(data_dir, LOCK_FILENAME), os.O_RDWR | os.O_CREAT, 0o600)
    if os.name == "nt":
        import msvcrt
        handle = msvcrt.get_osfhandle(descriptor)
        overlapped = ctypes.c_ulonglong(0)
        if not ctypes.windll.kernel32.LockFileEx(handle, 0x3, 0, 1, 0, ctypes.byref(overlapped)):
            os.close(descriptor)
            return None
    else:
        import fcntl
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            return None
    return descriptor


def filesystem_probe(data_dir: str) -> None:
    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    for name in ("backups", "logs"):
        (root / name).mkdir(exist_ok=True)
    source = root / ".localvault-probe"
    target = root / ".localvault-probe-renamed"
    try:
        with source.open("xb") as handle:
            handle.write(b"localvault-probe")
            handle.flush()
            os.fsync(handle.fileno())
        if source.read_bytes() != b"localvault-probe":
            raise OSError("filesystem read-back failed")
        os.replace(source, target)
        if not target.is_file():
            raise OSError("filesystem atomic rename failed")
    finally:
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def addresses(port: int) -> list[str]:
    found = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    return [f"http://{address}:{port}" for address in sorted(found, key=lambda item: (item != "127.0.0.1", item))]


def run() -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QStyle, QSystemTrayIcon

    app = QApplication(sys.argv)
    app.setApplicationName("LocalVault")
    QApplication.setQuitOnLastWindowClosed(False)
    data_dir = resolve_data_dir()
    lock = acquire_instance_lock(data_dir)
    if lock is None:
        QMessageBox.critical(None, "LocalVault", "LocalVault sudah berjalan.\nLocalVault is already running.")
        return 1
    try:
        filesystem_probe(data_dir)
        config = Config(data_dir)
        config.load()
        configure_file_logging(data_dir, config.log_level)
    except (OSError, ConfigError) as exc:
        QMessageBox.critical(None, "LocalVault", f"Startup gagal / failed:\n{exc}")
        os.close(lock)
        return 2

    bridge = ControlBridge()
    worker = ServerWorker(data_dir, config.port, config.log_level, bridge, sys.executable)
    worker.start()
    urls = addresses(config.port)

    tray = QSystemTrayIcon(app.style().standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon), app)
    tray.setToolTip("LocalVault — starting")
    menu = QMenu()
    open_action = menu.addAction("Buka LocalVault" if config.language == "id" else "Open LocalVault")
    open_action.triggered.connect(lambda: webbrowser.open(urls[0], new=2))
    address_menu = menu.addMenu("Alamat host/LAN" if config.language == "id" else "Host/LAN addresses")
    for url in urls:
        item = address_menu.addMenu(url)
        item.addAction("Buka" if config.language == "id" else "Open").triggered.connect(lambda _checked=False, value=url: webbrowser.open(value, new=2))
        item.addAction("Salin alamat" if config.language == "id" else "Copy address").triggered.connect(lambda _checked=False, value=url: QGuiApplication.clipboard().setText(value))
    lock_action = menu.addAction("Lock semua sesi" if config.language == "id" else "Lock all sessions")
    lock_action.triggered.connect(lambda: _notify_control(tray, bridge, "lock_all"))
    autostart_action = menu.addAction("Mulai otomatis saat login" if config.language == "id" else "Start automatically at login")
    autostart_action.setCheckable(True)
    autostart_action.setChecked(config.autostart)

    def toggle_autostart(enabled: bool) -> None:
        try:
            bridge.request("set_autostart", {"enabled": enabled}, timeout=5)
            config.autostart = enabled
            config.save()
        except Exception as exc:
            autostart_action.setChecked(not enabled)
            tray.showMessage("LocalVault", str(exc), QSystemTrayIcon.MessageIcon.Critical)

    autostart_action.toggled.connect(toggle_autostart)
    menu.addSeparator()
    stop_action = menu.addAction("Stop LocalVault")

    def stop() -> None:
        try:
            count = bridge.request("session_count", timeout=2)
        except Exception:
            count = 0
        if count and QMessageBox.question(None, "LocalVault", "Masih ada sesi aktif. Stop LocalVault?" if config.language == "id" else "Sessions are active. Stop LocalVault?") != QMessageBox.StandardButton.Yes:
            return
        try:
            bridge.request("stop", timeout=10)
        except Exception:
            worker.server.should_exit = True
        worker.join(timeout=10)
        tray.hide()
        app.quit()

    stop_action.triggered.connect(stop)
    tray.setContextMenu(menu)
    tray.show()

    def poll() -> None:
        while not worker.status.empty():
            state, detail = worker.status.get_nowait()
            tray.setToolTip(f"LocalVault — {state}")
            if state == "error":
                tray.showMessage("LocalVault", detail or "Server error", QSystemTrayIcon.MessageIcon.Critical)
        if worker.server.started:
            tray.setToolTip("LocalVault — ready")

    timer = QTimer(app)
    timer.timeout.connect(poll)
    timer.start(250)
    QTimer.singleShot(700, lambda: webbrowser.open(urls[0], new=2))
    try:
        return app.exec()
    finally:
        if worker.is_alive():
            worker.server.should_exit = True
            worker.join(timeout=10)
        os.close(lock)


def _notify_control(tray, bridge: ControlBridge, command: str) -> None:
    try:
        bridge.request(command, timeout=5)
        tray.showMessage("LocalVault", "Berhasil / Completed")
    except Exception as exc:
        tray.showMessage("LocalVault", str(exc))


if __name__ == "__main__":
    raise SystemExit(run())
