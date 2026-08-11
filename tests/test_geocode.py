"""Place search: bundled gazetteer, name normalisation, and the online path."""

import io
import json

import pytest

from astroplanner import geocode


def test_bundled_search_handles_the_way_people_type_place_names():
    hits = geocode.search_bundled("st louis")
    assert hits and hits[0].name == "Saint Louis"
    assert geocode.normalize("St. Louis") == "saint louis"
    assert geocode.normalize("Mt Wilson") == "mount wilson"


def test_observing_sites_are_searchable_and_carry_a_measured_bortle():
    site = geocode.search_bundled("cherry springs")[0]
    assert site.kind == "site"
    assert site.bortle_is_measured and site.bortle_estimate == 2


def test_towns_fall_back_to_a_population_estimate_clearly_labelled():
    p = geocode.Place("Nowhere", "", "Testland", 0.0, 0.0, 0.0, population=3000)
    assert not p.bortle_is_measured
    assert p.bortle_estimate == geocode.estimate_bortle(3000) == 4
    assert geocode.estimate_bortle(2_000_000) == 8
    assert geocode.estimate_bortle(0) == 4


def test_search_can_be_told_to_stay_offline(monkeypatch):
    def explode(*a, **k):
        raise AssertionError("offline search must not hit the network")
    monkeypatch.setattr(geocode, "search_online", explode)
    assert geocode.search("paris", online=False)


def test_a_broken_network_degrades_to_the_bundled_list(monkeypatch):
    def fail(*a, **k):
        raise OSError("egress blocked")
    monkeypatch.setattr(geocode, "search_online", fail)
    hits = geocode.search("rolla", limit=8, online=True)
    assert hits and hits[0].name == "Rolla"


def test_online_results_are_parsed_and_merged(monkeypatch):
    payload = {
        "results": [
            {
                "name": "Wentzville",
                "latitude": 38.81,
                "longitude": -90.85,
                "elevation": 180.0,
                "country": "United States",
                "admin1": "Missouri",
                "population": 44000,
            }
        ]
    }
    monkeypatch.setattr(
        geocode.urllib.request,
        "urlopen",
        lambda *a, **k: io.StringIO(json.dumps(payload)),
    )
    hits = geocode.search_online("wentzville")
    assert len(hits) == 1
    got = hits[0]
    assert got.source == "open-meteo"
    assert (got.lat, got.lon) == (38.81, -90.85)
    assert got.label == "Wentzville, Missouri, United States"
    assert got.bortle_estimate == 5 and not got.bortle_is_measured


def test_resolve_returns_one_place_or_explains_itself():
    assert geocode.resolve("big bend", online=False).name.startswith("Big Bend")
    with pytest.raises(KeyError, match="astroplanner places"):
        geocode.resolve("qqzzx nowhere", online=False)


def test_bundled_gazetteer_is_well_formed():
    places = geocode.load_places()
    assert len(places) > 50
    for p in places:
        assert -90 <= p.lat <= 90 and -180 <= p.lon <= 180, p.name
        assert p.kind in {"city", "site"}
        assert p.bortle is None or 1 <= p.bortle <= 9
