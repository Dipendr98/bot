"""
Stripe Auth (/au, /mau) gate selector.
Stores current gate per user: nomade-studio.be (primary) | grownetics.com (secondary)
"""

import json
import os

DATA_DIR = "DATA"
AU_GATE_PATH = os.path.join(DATA_DIR, "au_gate.json")

# Gate key -> base URL
AU_GATES = {
    "nomade": "https://shop.nomade-studio.be",
    "grownetics": "https://grownetics.com",
}

DEFAULT_GATE = "nomade"  # Nomade is now primary


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _load_store() -> dict:
    _ensure_data_dir()
    if not os.path.exists(AU_GATE_PATH):
        return {}
    try:
        with open(AU_GATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_store(data: dict) -> None:
    _ensure_data_dir()
    with open(AU_GATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_au_gate(user_id: str) -> str:
    """Current gate key for user. Default: nomade."""
    data = _load_store()
    gate = data.get(str(user_id), DEFAULT_GATE)
    if gate not in AU_GATES:
        return DEFAULT_GATE
    return gate


def set_au_gate(user_id: str, gate: str) -> bool:
    """Set gate for user. Returns True if valid."""
    if gate not in AU_GATES:
        return False
    data = _load_store()
    data[str(user_id)] = gate
    _save_store(data)
    return True


def get_au_gate_url(user_id: str) -> str:
    """Current gate URL for user."""
    return AU_GATES[get_au_gate(user_id)]


def toggle_au_gate(user_id: str) -> str:
    """Switch nomade <-> grownetics. Returns new gate key."""
    current = get_au_gate(user_id)
    new = "grownetics" if current == "nomade" else "nomade"
    set_au_gate(user_id, new)
    return new


def gate_display_name(gate_key: str) -> str:
    """Short label for UI."""
    if gate_key == "nomade":
        return "nomade-studio.be"
    if gate_key == "grownetics":
        return "grownetics.com"
    return gate_key
