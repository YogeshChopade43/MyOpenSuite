import os
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from backend.api import create_app, probe
from backend.catalog import load_catalog
from backend.compose import Compose

app = create_app(load_catalog(Path(os.environ.get("MOS_CATALOG", "catalog"))), Compose(), probe,
                 show_dev=os.environ.get("MOS_DEV") == "1")

if Path("frontend/dist").is_dir():
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="ui")
