from astroplanner.sessionlog import SessionLog


def test_add_and_list(tmp_path):
    log = SessionLog(tmp_path / "s.db")
    log.add("2026-08-02", "M31", "none", 120, 90, "clear night")
    log.add("2026-08-03", "NGC7000", "duoband", 300, 24)
    entries = log.list()
    assert len(entries) == 2
    assert entries[0].target == "NGC7000"          # newest first
    assert entries[0].total_minutes == 120
    assert entries[1].total_minutes == 180
    assert log.list("M31")[0].notes == "clear night"
    log.close()
