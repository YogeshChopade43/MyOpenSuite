"""Per-app secrets: generated once, persisted as JSON, injected as compose environment."""
import json
import os
import secrets
import threading
import time
from pathlib import Path

from backend.catalog import App


class SecretStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _read(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text())
        except ValueError:
            # Keep the unreadable file for the owner instead of silently losing their keys.
            self.path.rename(self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}"))
            return {}

    def _write(self, data: dict[str, dict[str, str]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def env_for(self, app: App) -> dict[str, str]:
        if not app.secrets:
            return {}
        with self._lock:
            data = self._read()
            mine = data.setdefault(app.id, {})
            missing = [k for k in app.secrets if k not in mine]
            for k in missing:
                mine[k] = secrets.token_urlsafe(32)
            if missing or not self.path.exists():
                self._write(data)
            return {k: mine[k] for k in app.secrets}
