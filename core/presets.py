"""
presets.py
----------
Save and load InversionParams presets as JSON files.
Presets are stored in the user's home directory under ~/.filmscan/presets/.
"""

import json
from pathlib import Path
from dataclasses import asdict, fields
from core.negative_inverter import InversionParams


_PRESET_DIR = Path.home() / ".filmscan" / "presets"


def _ensure_dir() -> Path:
    _PRESET_DIR.mkdir(parents=True, exist_ok=True)
    return _PRESET_DIR


def save_preset(name: str, params: InversionParams) -> Path:
    """Serialise InversionParams → JSON preset file."""
    _ensure_dir()
    data = asdict(params)
    filepath = _PRESET_DIR / f"{name}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump({"name": name, "params": data}, f, indent=2)
    return filepath


def load_preset(name: str) -> InversionParams:
    """Load a preset by name and return InversionParams."""
    filepath = _PRESET_DIR / f"{name}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Preset '{name}' not found at {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_params(data["params"])


def load_preset_from_file(filepath: str | Path) -> InversionParams:
    """Load a preset from an arbitrary JSON file path."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_params(data["params"])


def list_presets() -> list[str]:
    """Return names of all saved presets."""
    _ensure_dir()
    return [p.stem for p in sorted(_PRESET_DIR.glob("*.json"))]


def _dict_to_params(d: dict) -> InversionParams:
    """Convert a plain dict to InversionParams, ignoring unknown keys."""
    valid_keys = {f.name for f in fields(InversionParams)}
    filtered = {k: v for k, v in d.items() if k in valid_keys}
    return InversionParams(**filtered)
