from astroplanner.catalog import load_targets
from astroplanner.messier import best_month, messier_targets, monthly_visibility


def test_messier_targets_are_only_m_prefixed_ids():
    targets = messier_targets()
    assert targets  # the bundled catalog carries several
    assert all(t.id[0] == "M" and t.id[1:].isdigit() for t in targets)
    all_ids = {t.id for t in load_targets()}
    assert {"NGC7000", "IC5070"} & all_ids  # sanity: non-Messier ids exist
    assert not any(t.id in {"NGC7000", "IC5070"} for t in targets)


def test_messier_targets_sorted_numerically_not_lexically():
    ids = [t.id for t in messier_targets()]
    # Numeric order, e.g. M5 before M13 before M104 — a plain string sort
    # would put M104 before M13 before M5.
    numbers = [int(i[1:]) for i in ids]
    assert numbers == sorted(numbers)


def test_monthly_visibility_covers_all_twelve_months():
    m31 = next(t for t in load_targets() if t.id == "M31")
    months = monthly_visibility(m31, lat=41.66, lon=-77.82, ref_year=2026)
    assert [mv.month for mv in months] == list(range(1, 13))
    assert all(mv.usable_hours >= 0 for mv in months)


def test_high_dec_target_visible_most_months_at_mid_latitude():
    # M81 (Dec +69) is near-circumpolar from a mid-northern site: it should
    # clear 30 deg during darkness in most months of the year, unlike a
    # target near the celestial equator which has a real dead season.
    m81 = next(t for t in load_targets() if t.id == "M81")
    months = monthly_visibility(m81, lat=41.66, lon=-77.82, ref_year=2026)
    visible_months = sum(1 for mv in months if mv.usable_hours > 0)
    assert visible_months >= 9


def test_best_month_picks_the_highest_usable_hours():
    m31 = next(t for t in load_targets() if t.id == "M31")
    months = monthly_visibility(m31, lat=41.66, lon=-77.82, ref_year=2026)
    best = best_month(months)
    assert best.usable_hours == max(mv.usable_hours for mv in months)


def test_best_month_breaks_ties_on_altitude():
    from astroplanner.messier import MonthVisibility
    months = [
        MonthVisibility(month=1, usable_hours=5.0, max_alt_deg=40.0, dark_hours=10.0),
        MonthVisibility(month=2, usable_hours=5.0, max_alt_deg=60.0, dark_hours=10.0),
    ]
    assert best_month(months).month == 2
