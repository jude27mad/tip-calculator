from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

PROFILE_FILENAME = "tip_profiles.json"


class ProfileError(RuntimeError):
    """Raised when profile operations fail."""


def _profiles_path() -> Path:
    override = os.environ.get("TIP_PROFILES_PATH")
    if override:
        return Path(override).expanduser()
    return Path.cwd() / PROFILE_FILENAME


def load_profiles() -> Dict[str, dict]:
    path = _profiles_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProfileError(f"Failed to parse profiles file: {path}") from exc
    if not isinstance(data, dict):
        raise ProfileError("Profiles file must contain a JSON object")
    return {str(k): v for k, v in data.items() if isinstance(v, dict)}


def get_profile(name: str) -> Optional[dict]:
    return load_profiles().get(name)


def save_profile(name: str, payload: dict) -> None:
    profiles = load_profiles()
    profiles[name] = payload
    path = _profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, indent=2, sort_keys=True))
