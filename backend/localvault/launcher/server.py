from __future__ import annotations

import queue
import threading
from typing import Any

import uvicorn

from ..main import create_app
from ..logging_setup import make_logger
from .autostart import AutostartManager
from .control import ControlBridge

logger = make_logger("localvault.launcher")


class ServerWorker(threading.Thread):
    def __init__(self, data_dir: str, port: int, log_level: str, bridge: ControlBridge, executable: str) -> None:
        super().__init__(name="localvault-server", daemon=False)
        self.data_dir = data_dir
        self.bridge = bridge
        self.status: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self.app = create_app(data_dir, control=bridge)
        # The local host launcher may run without standard streams, so avoid
        # Uvicorn's console log configuration and use the application logger.
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host="0.0.0.0",
                port=port,
                log_level=log_level.lower(),
                access_log=False,
                log_config=None,
            )
        )
        self.autostart = AutostartManager(executable)
        self._control_thread: threading.Thread | None = None

    def run(self) -> None:
        self._control_thread = threading.Thread(target=self._control_loop, name="localvault-control", daemon=True)
        self._control_thread.start()
        self.status.put(("starting", None))
        logger.info("server worker starting on port %s", self.server.config.port)
        try:
            self.server.run()
            logger.info("server worker stopped")
            self.status.put(("stopped", None))
        except BaseException as exc:
            logger.exception("server worker failed: %s", type(exc).__name__)
            self.status.put(("error", str(exc)))

    def _control_loop(self) -> None:
        handlers = {
            "lock_all": self._lock_all,
            "session_count": self._session_count,
            "set_autostart": self._set_autostart,
            "stop": self._stop,
        }
        while not self.server.should_exit:
            self.bridge.process_one(handlers)

    def _context(self):
        context = getattr(self.app.state, "ctx", None)
        if context is None:
            raise RuntimeError("server is not ready")
        return context

    def _lock_all(self, _payload: dict[str, Any]) -> bool:
        context = self._context()
        context.sessions.lock_all()
        context.vault.lock_all()
        return True

    def _session_count(self, _payload: dict[str, Any]) -> int:
        return len(self._context().sessions.active_session_ids())

    def _set_autostart(self, payload: dict[str, Any]) -> bool:
        self.autostart.set_enabled(bool(payload["enabled"]))
        return True

    def _stop(self, _payload: dict[str, Any]) -> bool:
        try:
            self._lock_all({})
        finally:
            self.server.should_exit = True
        return True
