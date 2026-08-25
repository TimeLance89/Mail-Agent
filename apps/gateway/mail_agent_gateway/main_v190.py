from __future__ import annotations

from . import main_v180 as previous

APP_VERSION = "0.19.0"
base = previous.base
owner_profile_store = previous.owner_profile_store

versioned_module = previous
while True:
    versioned_module.APP_VERSION = APP_VERSION
    if not hasattr(versioned_module, "previous"):
        break
    versioned_module = versioned_module.previous
base.APP_VERSION = APP_VERSION
base.app.version = APP_VERSION

app = base.app
