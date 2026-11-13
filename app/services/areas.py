"""Device areas of the dashboard (Network, Services, Controllers, …) and their icons.

A link tile shows its area's icon until the device delivers its own picture. The
area is set on the tile, or found from the tile's group name: each area has a list
of group names (Settings › Device areas); the first area with a name that occurs
as a whole word in the group wins. Without a match a tile is a network device.
"""
import re

# key, label, default group names; the icon is static/area-<key>.svg
AREAS = [
    ("network", "Network", ["Network", "Netzwerk", "Netz", "LAN", "Router", "Switch"]),
    ("services", "Services", ["Services", "Dienste", "Server", "Datenbank", "Database"]),
    ("controllers", "Controllers", ["Controllers", "Controller", "SPS", "PLC", "Steuerung"]),
    ("clients", "Clients", ["Clients", "Client", "PC", "HMI", "Bedienung"]),
    ("field", "Field devices", ["Field devices", "Feldgeräte", "Antriebe", "Motoren", "Drives"]),
    ("meters", "Meters", ["Meters", "Zähler", "Messung", "Messgeräte", "Energie"]),
]
KEYS = [k for k, _, _ in AREAS]
LABELS = {k: label for k, label, _ in AREAS}
DEFAULT = "network"


def group_names(configured: dict[str, list[str]]) -> dict[str, list[str]]:
    """Group names per area: the configured ones, else the defaults."""
    return {k: configured[k] if k in configured else names for k, _, names in AREAS}


def area_of(tile: dict, configured: dict[str, list[str]]) -> str:
    if (tile.get("area") or "") in KEYS:
        return tile["area"]
    group = tile.get("group") or ""
    for key, names in group_names(configured).items():
        if any(n and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", group, re.I) for n in names):
            return key
    return DEFAULT
