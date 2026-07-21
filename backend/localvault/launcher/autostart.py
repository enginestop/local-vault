from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

ENTRY_NAME = "LocalVault"


class AutostartManager:
    def __init__(self, executable: str, platform: str | None = None, home: str | None = None) -> None:
        self.executable = str(Path(executable).resolve())
        self.platform = platform or sys.platform
        self.home = Path(home).resolve() if home else Path.home()

    def set_enabled(self, enabled: bool) -> None:
        if self.platform == "win32":
            self._windows(enabled)
        elif self.platform == "darwin":
            self._macos(enabled)
        else:
            self._linux(enabled)

    def _windows(self, enabled: bool) -> None:
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        shortcut = startup / f"{ENTRY_NAME}.lnk"
        if not enabled:
            shortcut.unlink(missing_ok=True)
            return
        startup.mkdir(parents=True, exist_ok=True)
        target = self.executable.replace("'", "''")
        link = str(shortcut).replace("'", "''")
        working = str(Path(self.executable).parent).replace("'", "''")
        script = f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');$s.TargetPath='{target}';$s.WorkingDirectory='{working}';$s.Save()"
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _macos(self, enabled: bool) -> None:
        path = self.home / "Library" / "LaunchAgents" / "app.localvault.plist"
        if not enabled:
            path.unlink(missing_ok=True)
            return
        payload = {"Label": "app.localvault", "ProgramArguments": [self.executable], "RunAtLoad": True}
        _atomic_write(path, plistlib.dumps(payload))

    def _linux(self, enabled: bool) -> None:
        path = self.home / ".config" / "autostart" / "localvault.desktop"
        if not enabled:
            path.unlink(missing_ok=True)
            return
        quoted = self.executable.replace("\\", "\\\\").replace('"', '\\"')
        content = f'[Desktop Entry]\nType=Application\nName=LocalVault\nExec="{quoted}"\nTerminal=false\nX-GNOME-Autostart-enabled=true\n'
        _atomic_write(path, content.encode("utf-8"))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
