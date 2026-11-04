import os
import threading
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from backend.api import create_app, probe
from backend.catalog import CatalogError, load_catalog
from backend.compose import Compose
from backend.importer import GitHub
from backend.netinfo import default_gateway
from backend.secrets_store import SecretStore

idle_minutes = float(os.environ.get("MOS_IDLE_MINUTES", "30"))  # 0 turns auto-stop off
state = Path(os.environ.get("MOS_STATE", "state"))
store = SecretStore(state / "secrets.json")
apps = load_catalog(Path(os.environ.get("MOS_CATALOG", "catalog")))
try:
    apps |= load_catalog(state / "catalog")
except CatalogError as e:  # one bad import must not take the dashboard down
    print(f"imported apps not loaded: {e}", flush=True)
app = create_app(apps, Compose(env_for=store.env_for),
                 probe, show_dev=os.environ.get("MOS_DEV") == "1", secrets=store,
                 allowed_clients={"127.0.0.1", gw} if (gw := default_gateway()) else None,
                 idle_seconds=idle_minutes * 60, imports=state / "catalog", github=GitHub())
if idle_minutes:
    threading.Thread(target=app.state.idle.run_forever, daemon=True).start()

if Path("frontend/dist").is_dir():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
