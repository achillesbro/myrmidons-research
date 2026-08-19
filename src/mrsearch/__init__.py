"""mrsearch — research loops joining MNEMON data with METRON metrics.

The production compute side (SnapshotReader, OutputStore, protocol algebra,
orchestrators) lives in myrmidons-api (tag-pinned dependency); import it
directly: ``from myrmidons_api import SnapshotReader``. This package keeps
only the loop-provenance machinery.
"""

from mrsearch.snapshot import (
    Manifest,
    installed_metron_version,
    read_manifest,
    write_manifest,
)

__all__ = [
    "Manifest",
    "installed_metron_version",
    "read_manifest",
    "write_manifest",
]

__version__ = "0.2.0"
