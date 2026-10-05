"""The zones and borders the Kosovo scenario models; the one place to add a country or border.

BORDERS lists every physical interconnector between COUNTRIES once, covering both
directions, with the source expected to publish its daily auction, or None when no
daily auction data is known. A border direction is open in a scenario only when the
database holds a result for that hour, whatever the source (MANUAL rows included);
otherwise its capacity is 0. The expected source only decides whether missing data
is reported as a warning.
"""

# id: (name, lat, lon, max_supply MW); max_supply values are placeholders.
COUNTRIES = {
    "XK": ("Kosovo", 42.6, 20.9, None),
    "AL": ("Albania", 41.1, 20.0, 300),
    "MK": ("North Macedonia", 41.6, 21.7, 200),
    "ME": ("Montenegro", 42.7, 19.3, 200),
    "RS": ("Serbia", 44.0, 21.6, 700),
    "BA": ("Bosnia", 44.2, 17.8, 500),
    "BG": ("Bulgaria", 42.7, 25.3, 800),
    "GR": ("Greece", 39.1, 21.8, 600),
    "RO": ("Romania", 45.9, 25.0, 900),
    "HU": ("Hungary", 47.2, 19.4, 800),
    "HR": ("Croatia", 45.6, 16.2, 600),
    "TR": ("Türkiye", 40.9, 29.0, 800),
}
DEMAND_NODE = "XK"

# (a, b) with a < b: expected source of the daily auction, or None.
BORDERS = {
    ("AL", "GR"): "SEECAO",
    ("AL", "ME"): "SEECAO",
    ("AL", "MK"): None,      # no daily auction found on JAO/SEECAO
    ("AL", "XK"): None,      # implicit allocation, no explicit daily auction
    ("BA", "HR"): "SEECAO",
    ("BA", "ME"): "SEECAO",
    ("BA", "RS"): None,      # no daily auction found on JAO/SEECAO
    ("BG", "GR"): None,      # no daily auction found on JAO/SEECAO
    ("BG", "MK"): "JAO",
    ("BG", "RO"): None,      # market coupled
    ("BG", "RS"): "JAO",
    ("BG", "TR"): None,      # no daily auction found on JAO/SEECAO
    ("GR", "MK"): "SEECAO",
    ("GR", "TR"): "SEECAO",
    ("HR", "HU"): None,      # no daily auction found on JAO/SEECAO
    ("HR", "RS"): "JAO",
    ("HU", "RO"): None,      # market coupled
    ("HU", "RS"): "JAO",
    ("ME", "RS"): "JAO",
    ("ME", "XK"): "SEECAO",
    ("MK", "RS"): "JAO",
    ("MK", "XK"): "SEECAO",
    ("RO", "RS"): None,      # market coupled
    ("RS", "XK"): None,      # not in operation
}


def is_modeled(out_area: str, in_area: str) -> bool:
    """Both ends are modeled countries; only such auctions are crawled."""
    return out_area in COUNTRIES and in_area in COUNTRIES


def border_of(out_area: str, in_area: str) -> tuple[str, str] | None:
    """The BORDERS key covering this direction, or None if the border isn't listed."""
    key = tuple(sorted((out_area, in_area)))
    return key if key in BORDERS else None
