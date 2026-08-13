"""mrsearch — research loops joining MNEMON data with METRON metrics,
plus the Phase 3 risk-engine write side (MNEMON output tables)."""

from mrsearch.mnemon_reader import SnapshotReader
from mrsearch.outputs import LIQ_CAPACITY, OutputStore, OutputTable
from mrsearch.protocol import lif_from_lltv, max_slippage_threshold
from mrsearch.snapshot import (
    Manifest,
    installed_metron_version,
    read_manifest,
    write_manifest,
)

__all__ = [
    "LIQ_CAPACITY",
    "Manifest",
    "OutputStore",
    "OutputTable",
    "SnapshotReader",
    "installed_metron_version",
    "lif_from_lltv",
    "max_slippage_threshold",
    "read_manifest",
    "write_manifest",
]

__version__ = "0.1.0"
