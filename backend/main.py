import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from backend.api import create_app, probe
from backend.catalog import load_catalog
from backend.compose import Compose
from backend.netinfo import default_gateway
from backend.secrets_store import SecretStore

store = SecretStore(Path(os.environ.get("MOS_STATE", "state")) / "secrets.json")
app = create_app(load_catalog(Path(os.environ.get("MOS_CATALOG", "catalog"))), Compose(env_for=store.env_for),
                 probe, show_dev=os.environ.get("MOS_DEV") == "1", secrets=store,
                 allowed_clients={"127.0.0.1", gw} if (gw := default_gateway()) else None)

if Path("frontend/dist").is_dir():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
