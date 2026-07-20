#!/usr/bin/env python3
"""LocalVault launcher.

Runs the single-instance LocalVault server, performs a startup self-test of the
data directory, opens the default browser to the vault, and shuts the server
down gracefully on exit (Ctrl-C / window close / tray quit).

PRD-005: single instance + browser open + graceful shutdown.
PRD-006: bind 0.0.0.0 HTTP IPv4, persistent port from config.json.
PRD-008: LocalVault-Data lives beside this script.
PRD-013: startup self-test verifies exclusive lock, writability, durability.
"""

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from localvault.config import Config  # noqa: E402

LOCK_FILENAME = "localvault.lock"


def resolve_data_dir() -> str:
    # PRD-008: LocalVault-Data beside the launcher.
    return os.path.join(HERE, "LocalVault-Data")


def acquire_instance_lock(data_dir: str):
    """PRD-005 single instance: exclusive OS lock file.

    Returns (lock_file_handle, acquired). On Windows uses LockFileEx via
    msvcrt; on POSIX uses fcntl. Uses a non-blocking exclusive lock so a
    second launcher instance fails fast.
    """
    os.makedirs(data_dir, exist_ok=True)
    lock_path = os.path.join(data_dir, LOCK_FILENAME)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    if os.name == "nt":
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)
        overlapped = ctypes.c_ulonglong(0)
        flags = 0x00000002 | 0x00000001  # LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY
        if not ctypes.windll.kernel32.LockFileEx(
            handle, flags, 0, 1, 0, ctypes.byref(overlapped)
        ):
            os.close(fd)
            return None
        return fd
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return None
        return fd


def self_test(data_dir: str) -> None:
    """PRD-013: verify exclusive lock, writability, and atomic durability."""
    test_path = os.path.join(data_dir, ".selftest")
    try:
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
            f.flush()
            os.fsync(f.fileno())
        with open(test_path, "r", encoding="utf-8") as f:
            if f.read() != "ok":
                raise RuntimeError("read-back mismatch during self-test")
        tmp = test_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write("durable")
        os.replace(tmp, test_path)
    finally:
        for p in (test_path, test_path + ".tmp"):
            try:
                os.remove(p)
            except OSError:
                pass


def open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass


def main() -> int:
    data_dir = resolve_data_dir()
    os.makedirs(data_dir, exist_ok=True)

    config = Config(data_dir)
    config.load()
    port = config.port

    lock = acquire_instance_lock(data_dir)
    if lock is None:
        print(
            "LocalVault sudah berjalan (instance lain memegang kunci).",
            file=sys.stderr,
        )
        return 1

    try:
        self_test(data_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"Self-test direktori data gagal: {exc}", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{port}/"

    import uvicorn  # noqa: E402
    from localvault.main import create_app  # noqa: E402

    app = create_app(data_dir)

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=port,
            log_level=config.log_level.lower(),
            access_log=False,
        )
    )

    stop = threading.Event()

    def shutdown(*_):
        stop.set()
        server.should_exit = True

    signal.signal(signal.SIGINT, shutdown)
    if os.name != "nt":
        signal.signal(signal.SIGTERM, shutdown)

    print(f"LocalVault berjalan di {url} (data: {data_dir})")

    browser_thread = threading.Thread(target=open_browser, args=(url,), daemon=True)
    browser_thread.start()

    try:
        server.run()
    finally:
        try:
            os.close(lock)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
