"""Tests for scripts/backup_data.py — dated tar of data/, keep last N."""
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backup_data import create_backup, prune_backups


def _make_data(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "paper_positions.yaml").write_text("positions: []\n")
    (data / "signal_log.jsonl").write_text('{"ticker": "AGX"}\n')
    return data


def test_create_backup_produces_readable_tarball(tmp_path):
    data = _make_data(tmp_path)
    backups = tmp_path / "backups"
    out = create_backup(data, backups, "20260705")

    assert out.name == "data_20260705.tar.gz"
    assert out.exists()
    # no tmp left behind
    assert list(backups.glob("*.tmp")) == []
    # archive is valid and contains the data files under data/
    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert any(n.endswith("paper_positions.yaml") for n in names)
    assert any(n.endswith("signal_log.jsonl") for n in names)
    print("  ✓ create_backup writes a readable tarball with the data tree")


def test_create_backup_same_day_overwrites(tmp_path):
    data = _make_data(tmp_path)
    backups = tmp_path / "backups"
    create_backup(data, backups, "20260705")
    create_backup(data, backups, "20260705")
    archives = list(backups.glob("data_*.tar.gz"))
    assert len(archives) == 1     # same day → one file, not two
    print("  ✓ same-day backup overwrites rather than duplicating")


def test_prune_keeps_last_n(tmp_path):
    data = _make_data(tmp_path)
    backups = tmp_path / "backups"
    for day in range(1, 34):      # 33 dated backups
        create_backup(data, backups, f"202601{day:02d}")

    pruned = prune_backups(backups, keep=30)
    remaining = sorted(p.name for p in backups.glob("data_*.tar.gz"))

    assert len(pruned) == 3
    assert len(remaining) == 30
    # oldest three (01,02,03) removed; newest retained (names sort chronologically)
    assert remaining[0] == "data_20260104.tar.gz"
    assert remaining[-1] == "data_20260133.tar.gz"
    print("  ✓ prune keeps the newest 30 and removes the rest")


def test_prune_noop_when_under_limit(tmp_path):
    data = _make_data(tmp_path)
    backups = tmp_path / "backups"
    create_backup(data, backups, "20260705")
    pruned = prune_backups(backups, keep=30)
    assert pruned == []
    assert len(list(backups.glob("data_*.tar.gz"))) == 1
    print("  ✓ prune is a no-op when under the retention limit")


def test_prune_missing_dir_is_safe(tmp_path):
    assert prune_backups(tmp_path / "nope", keep=30) == []
    print("  ✓ prune on a missing backups dir returns [] (no crash)")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tp = Path(td)
        test_create_backup_produces_readable_tarball(tp)
    print("Backup tests passed (run via pytest for full coverage).")
