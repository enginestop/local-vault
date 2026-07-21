from __future__ import annotations

import queue
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ControlCommand:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    response: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))


class ControlBridge:
    """Thread-safe launcher/server bridge; never exposed over HTTP or LAN."""

    def __init__(self) -> None:
        self.commands: queue.Queue[ControlCommand] = queue.Queue()

    def request(self, name: str, payload: dict[str, Any] | None = None, timeout: float = 10) -> Any:
        command = ControlCommand(name, payload or {})
        self.commands.put(command)
        result = command.response.get(timeout=timeout)
        if isinstance(result, BaseException):
            raise result
        return result

    def process_one(self, handlers: dict[str, Callable[[dict[str, Any]], Any]], timeout: float = 0.2) -> bool:
        try:
            command = self.commands.get(timeout=timeout)
        except queue.Empty:
            return False
        try:
            handler = handlers.get(command.name)
            if handler is None:
                raise ValueError(f"unknown control command: {command.name}")
            command.response.put(handler(command.payload))
        except BaseException as exc:
            command.response.put(exc)
        return True
