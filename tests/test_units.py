"""Unit presentation and local clock time."""

from datetime import datetime, timezone

import pytest

from astroplanner import geocode
from astroplanner.units import (
    DEFAULT_TZ,
    IMPERIAL,
    METRIC,
    format_aperture,
    format_elevation,
    get_zone,
    local_hhmm,
    to_local,
    zone_abbrev,
)

# 03:00 UTC on an August night — the middle of a summer session in Nashville.
SUMMER = datetime(2026, 8, 12, 3, 0, tzinfo=timezone.utc)
WINTER = datetime(2026, 1, 12, 3, 0, tzinfo=timezone.utc)


def test_default_timezone_is_central():
    assert DEFAULT_TZ == "America/Chicago"


def test_utc_becomes_a_time_you_would_actually_set_an_alarm_for():
    central = get_zone("America/Chicago")
    assert local_hhmm(SUMMER, central) == "22:00"     # the night before, locally
    assert zone_abbrev(SUMMER, central) == "CDT"
    assert zone_abbrev(WINTER, central) == "CST"      # the offset moves with DST


def test_naive_datetimes_are_read_as_utc():
    # astropy hands back naive UTC datetimes; treating them as local would put
    # the whole night hours off.
    central = get_zone("America/Chicago")
    naive = SUMMER.replace(tzinfo=None)
    assert local_hhmm(naive, central) == local_hhmm(SUMMER, central)


def test_other_zones_still_work():
    assert local_hhmm(SUMMER, get_zone("UTC")) == "03:00"
    assert local_hhmm(SUMMER, get_zone("America/New_York")) == "23:00"
    assert to_local(SUMMER, get_zone("Australia/Sydney")).strftime("%H:%M") == "13:00"


def test_unknown_timezone_says_what_to_type():
    with pytest.raises(SystemExit, match="America/Chicago"):
        get_zone("Central")


def test_elevation_reads_in_feet_by_default():
    assert format_elevation(169) == "554 ft"
    assert format_elevation(169, IMPERIAL) == "554 ft"
    assert format_elevation(169, METRIC) == "169 m"


def test_aperture_shows_both_because_telescopes_are_sold_both_ways():
    assert format_aperture(203) == '8.0" (203 mm)'
    assert format_aperture(71) == '2.8" (71 mm)'
    assert format_aperture(203, METRIC) == "203 mm"


def test_sky_class_says_how_much_to_trust_it():
    # A meter reading at a dark-sky park, a published figure for a city, and a
    # guess from population are three different claims.
    site = geocode.search_bundled("cherry springs")[0]
    city = geocode.search_bundled("nashville")[0]
    guess = geocode.Place("Nowhere", "", "Testland", 0.0, 0.0, 0.0, population=3000)
    assert site.bortle_basis == "measured" and site.bortle_is_measured
    assert city.bortle_basis == "typical" and not city.bortle_is_measured
    assert guess.bortle_basis == "estimated" and not guess.bortle_is_measured


def test_nashville_is_in_the_gazetteer_and_is_central():
    city = geocode.search_bundled("nashville")[0]
    assert (round(city.lat, 1), round(city.lon, 1)) == (36.2, -86.8)
    # Longitude puts it squarely in the default zone the CLI ships with.
    assert -105 < city.lon < -82


def test_small_optics_are_not_quoted_in_inches():
    # A 2.8 mm wide-angle entrance pupil is 0.1 inches. Nobody writes that, and
    # printing it invites the reader to think a digit was lost.
    assert format_aperture(2.8) == "2.8 mm"
    assert format_aperture(2.8, METRIC) == "2.8 mm"
    assert format_aperture(24) == "24 mm"           # the DWARF II's telephoto
    # An inch is the cutoff: above it, both figures are useful.
    assert format_aperture(30) == '1.2" (30 mm)'
    assert format_aperture(203) == '8.0" (203 mm)'  


def test_short_focal_lengths_keep_their_decimal():
    from astroplanner.units import format_focal_length
    assert format_focal_length(6.7) == "6.7 mm"     # not "7 mm"
    assert format_focal_length(150) == "150 mm"


def test_a_constellation_sized_field_is_quoted_in_degrees():
    from astroplanner.units import format_fov
    assert format_fov(45, 34) == "45' x 34'"        # a telescope's field
    assert format_fov(2857, 1607) == "47.6° x 26.8°"  # a wide-angle lens's
