"""Guard behaviour of the smoke scenario runner."""

from __future__ import annotations

from pathlib import Path

from homefile.smoke import run_smoke


def test_reused_work_dir_is_refused_instead_of_reporting_false_failures(tmp_path: Path) -> None:
    work_dir = tmp_path / "smoke"
    (work_dir / "library").mkdir(parents=True)
    (work_dir / "library" / "homefile.sqlite3").write_bytes(b"")

    report = run_smoke(work_dir)

    assert report["ok"] is False
    assert report["steps"] == []
    assert len(report["failures"]) == 1
    message = report["failures"][0]
    assert str(work_dir) in message
    assert "--work-dir" in message
