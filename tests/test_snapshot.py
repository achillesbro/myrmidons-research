"""manifest.json round-trip."""

import pytest

from mrsearch.snapshot import Manifest, read_manifest, write_manifest


def test_manifest_round_trips(tmp_path):
    manifest = Manifest(
        snapshot_date="2026-08-06",
        mnemon_commit="601d1f62308f70efa625d6caa7104b5ce5e6bfe7",
        metron_version="v1.0.0",
        tables=("market_state", "markets", "prices"),
    )
    path = write_manifest(tmp_path, manifest)
    assert path == tmp_path / "manifest.json"
    assert read_manifest(tmp_path) == manifest


def test_read_manifest_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="record provenance before computing"):
        read_manifest(tmp_path)
