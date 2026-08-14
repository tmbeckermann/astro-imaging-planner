"""Place search: turn "st louis" into a latitude, longitude and elevation.

Two sources, in this order:

1. A bundled gazetteer (data/places.csv). Always present, needs no network,
   and carries the thing an online geocoder cannot tell you — a sky-quality
   figure for the observing sites astronomers actually drive to.
2. The Open-Meteo geocoding API, which is free, needs no API key and covers
   every populated place on Earth. Used only when the bundled list comes up
   short, and any failure (no network, blocked egress, timeout) degrades
   silently back to source 1.

Coordinates are good to about a kilometre, which is far below anything the
planner can notice: moving 10 km changes a target's altitude by ~0.1 deg.

Sky quality is the part that does not geocode. There is no free coordinate to
Bortle API — the underlying data is the World Atlas / VIIRS raster, which is a
large download and awkwardly licensed. So bundled observing sites carry a
measured Bortle class, and everywhere else gets `estimate_bortle`, a
population heuristic that is honest about being one. Check a real map
(lightpollutionmap.info) before trusting it for a site you have not visited.
"""

import csv
import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from importlib import resources

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_S = 6.0


@dataclass(frozen=True)
class Place:
    name: str
    admin: str            # state / region, may be blank
    country: str
    lat: float
    lon: float            # east positive
    elevation_m: float
    population: int = 0
    bortle: int | None = None    # only set where it has actually been measured
    kind: str = "city"           # city | observing site
    source: str = "bundled"

    @property
    def label(self) -> str:
        parts = [self.name] + [p for p in (self.admin, self.country) if p]
        return ", ".join(parts)

    @property
    def bortle_estimate(self) -> int:
        return self.bortle if self.bortle is not None else estimate_bortle(self.population)

    @property
    def bortle_basis(self) -> str:
        """How much to trust this place's sky class.

        `measured` is reserved for the observing sites, which have been
        characterised with a meter. A town carrying a stated value gets
        `typical` — a published figure for a place that size and that lit, not
        a reading at your parking spot. Everything else is `estimated` from
        population, which is a rule of thumb wearing a number.
        """
        if self.bortle is None:
            return "estimated"
        return "measured" if self.kind == "site" else "typical"

    @property
    def bortle_is_measured(self) -> bool:
        return self.bortle_basis == "measured"


def estimate_bortle(population: int) -> int:
    """Crude Bortle class from town size, for places with no measured value.

    This is a rule of thumb about the sky *in the middle of* a place of that
    size, and nothing more: it knows nothing about which way the city lies
    from you, terrain, or the ridge you park behind. Treat it as a starting
    value to correct, not a measurement.
    """
    if population >= 1_000_000:
        return 8
    if population >= 250_000:
        return 7
    if population >= 50_000:
        return 6
    if population >= 10_000:
        return 5
    if population > 0:
        return 4
    return 4


def load_places() -> list[Place]:
    path = resources.files("astroplanner").joinpath("data/places.csv")
    places = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            places.append(
                Place(
                    name=row["name"],
                    admin=row["admin"],
                    country=row["country"],
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    elevation_m=float(row["elevation_m"]),
                    population=int(row["population"]),
                    bortle=int(row["bortle"]) if row["bortle"] else None,
                    kind=row["kind"],
                )
            )
    return places


# Decimal pairs, degrees-minutes-seconds, and the @lat,lon or ?q=lat,lon that
# map applications put in their share links.
_DECIMAL = re.compile(
    r"(-?\d{1,3}(?:\.\d+)?)\s*[°]?\s*([NnSs])?[\s,]+(-?\d{1,3}(?:\.\d+)?)\s*[°]?\s*([EeWw])?\s*$"
)
_DMS = re.compile(
    r"""(\d{1,3})\s*[°:\s]\s*(\d{1,2})\s*['′:\s]\s*([\d.]+)?\s*["″]?\s*([NnSs])
        [\s,]+
        (\d{1,3})\s*[°:\s]\s*(\d{1,2})\s*['′:\s]\s*([\d.]+)?\s*["″]?\s*([EeWw])""",
    re.VERBOSE,
)
_URL_COORDS = re.compile(r"[@=/](-?\d{1,3}\.\d+),\s*(-?\d{1,3}\.\d+)")


def parse_coordinates(text: str) -> tuple[float, float] | None:
    """Read a latitude/longitude out of whatever the user pasted.

    The realistic way to "pick a point on a map" without shipping a map: drop a
    pin in whatever mapping app you already use, copy, paste. Handles
    `36.1627, -86.7816`, `36.1627 N, 86.7816 W`, `36°09'46"N 86°46'54"W`, and
    the coordinates embedded in a Google or Apple Maps URL.

    Returns None if the text is a place name rather than a position, so callers
    can fall through to the gazetteer.
    """
    raw = text.strip()
    if not raw:
        return None

    if "://" in raw or "maps" in raw.lower():
        m = _URL_COORDS.search(raw)
        if m:
            return _validate(float(m.group(1)), float(m.group(2)))

    m = _DMS.search(raw)
    if m:
        lat = int(m.group(1)) + int(m.group(2)) / 60 + float(m.group(3) or 0) / 3600
        lon = int(m.group(5)) + int(m.group(6)) / 60 + float(m.group(7) or 0) / 3600
        if m.group(4).upper() == "S":
            lat = -lat
        if m.group(8).upper() == "W":
            lon = -lon
        return _validate(lat, lon)

    m = _DECIMAL.match(raw)
    if m:
        lat, lat_hem, lon, lon_hem = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        if lat_hem and lat_hem.upper() == "S":
            lat = -abs(lat)
        if lon_hem and lon_hem.upper() == "W":
            lon = -abs(lon)
        return _validate(lat, lon)
    return None


def _validate(lat: float, lon: float) -> tuple[float, float] | None:
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None


def place_from_coordinates(lat: float, lon: float, label: str = "") -> Place:
    """A Place for a bare position. Sky class is unknown, so it says so."""
    return Place(
        name=label or f"{lat:.4f}, {lon:.4f}",
        admin="", country="", lat=lat, lon=lon, elevation_m=0.0,
        population=0, bortle=None, kind="pin", source="coordinates",
    )


# People type "st louis" and "Mt. Wilson"; the gazetteer spells them out.
_ABBREVIATIONS = {"st": "saint", "ste": "sainte", "mt": "mount", "ft": "fort", "pt": "point"}


def normalize(text: str) -> str:
    """Casefold, drop punctuation, expand the usual place-name abbreviations."""
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
    return " ".join(_ABBREVIATIONS.get(w, w) for w in cleaned.split())


def _match_score(query: str, place: Place) -> float:
    """Rank bundled matches: prefix beats substring, big places beat small."""
    q = normalize(query)
    name = normalize(place.name)
    label = normalize(place.label)
    if not q:
        return 0.0
    if name == q:
        base = 100.0
    elif name.startswith(q):
        base = 80.0
    elif q in name:
        base = 60.0
    elif q in label:
        base = 40.0
    elif all(tok in label for tok in q.split()):
        base = 20.0   # every word appears somewhere: "louis missouri"
    else:
        return 0.0
    # Observing sites outrank same-named towns; then population.
    site_bonus = 8.0 if place.kind == "site" else 0.0
    return base + site_bonus + math.log10(max(place.population, 1))


def search_bundled(query: str, limit: int = 8) -> list[Place]:
    scored = [(s, p) for p in load_places() if (s := _match_score(query, p)) > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [p for _, p in scored[:limit]]


def search_online(query: str, limit: int = 8, timeout: float = TIMEOUT_S) -> list[Place]:
    """Query the Open-Meteo geocoder. Raises on any network/parse failure."""
    url = f"{GEOCODE_URL}?" + urllib.parse.urlencode(
        {"name": query, "count": limit, "language": "en", "format": "json"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "astro-imaging-planner/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.load(resp)
    out = []
    for r in payload.get("results", []):
        out.append(
            Place(
                name=r.get("name", query),
                admin=r.get("admin1", "") or "",
                country=r.get("country", "") or "",
                lat=float(r["latitude"]),
                lon=float(r["longitude"]),
                elevation_m=float(r.get("elevation") or 0.0),
                population=int(r.get("population") or 0),
                bortle=None,
                kind="city",
                source="open-meteo",
            )
        )
    return out


def search(query: str, limit: int = 8, online: bool = True) -> list[Place]:
    """Bundled matches first, topped up from the online geocoder if allowed."""
    pin = parse_coordinates(query)
    if pin is not None:                      # a pasted position is not a search
        return [place_from_coordinates(*pin)]
    results = search_bundled(query, limit)
    if len(results) >= limit or not online:
        return results
    try:
        extra = search_online(query, limit)
    except Exception:
        return results          # offline is a normal state, not an error
    seen = {(round(p.lat, 2), round(p.lon, 2)) for p in results}
    for p in extra:
        key = (round(p.lat, 2), round(p.lon, 2))
        if key not in seen:
            seen.add(key)
            results.append(p)
        if len(results) >= limit:
            break
    return results


def resolve(query: str, online: bool = True) -> Place:
    """The single best match for a place name, or KeyError."""
    hits = search(query, limit=1, online=online)
    if not hits:
        raise KeyError(
            f"No place matched '{query}'. Try 'astroplanner places {query}' to see "
            f"candidates, or pass --lat/--lon directly."
        )
    return hits[0]
