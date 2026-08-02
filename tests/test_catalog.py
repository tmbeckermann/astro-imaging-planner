from astroplanner.catalog import load_targets


def test_catalog_loads_and_is_sane():
    targets = load_targets()
    assert len(targets) >= 50
    ids = [t.id for t in targets]
    assert len(ids) == len(set(ids))
    for t in targets:
        assert 0 <= t.ra_deg < 360
        assert -90 <= t.dec_deg <= 90
        assert t.size_arcmin > 0
        assert t.type in {"emission", "reflection", "galaxy", "planetary", "cluster", "snr"}


def test_line_emitter_flags():
    by_id = {t.id: t for t in load_targets()}
    assert by_id["NGC7000"].line_emitter        # emission
    assert by_id["NGC6960"].line_emitter        # SNR
    assert by_id["M27"].line_emitter            # planetary
    assert not by_id["M31"].line_emitter        # galaxy
    assert not by_id["M45"].line_emitter        # reflection
