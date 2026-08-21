# Schema constants for AROL capping-machine telemetry.

from __future__ import annotations

import re

TIMESTAMP_COLUMN = "timestamp"
MAX_HEADS = 48
HEAD_COLUMN_RE = re.compile(r"^(H\d{2})\s+(Count|AppTorque|Status)$")

# status_code -> (short label, is_reject, description)
STATUS_TABLE: dict[int, tuple[str, bool, str]] = {
    0: ("Closure OK", False, "Closure OK"),
    2: ("No Load", False, "No Load"),
    3: ("SlowTorque", True, "SlowTorque — failed to reach first torque threshold"),
    4: ("No Closure", False, "No Closure"),
    5: ("ClosureTorque", True, "ClosureTorque — failed to reach final torque"),
    8: ("No InTorque", False, "No InTorque"),
    9: ("EarlyRaise", True, "Head raised before TimeInTorque elapsed"),
    16: ("No CapTurns", False, "No CapTurns"),
    17: ("InsufficientCapTurns", True, "Closed with fewer degrees than CapTurns"),
    32: ("Following Error", False, "Following Error"),
    33: ("TrackingError", True, "Tracking error between real and controlled position"),
    64: ("Bad Closure", False, "Bad Closure"),
    65: ("RotatingAtRaise", True, "ClosureTorque reached but cap still rotating at head raise"),
}

VALID_STATUS_CODES: frozenset[int] = frozenset(STATUS_TABLE.keys())
REJECT_STATUS_CODES: frozenset[int] = frozenset(
    code for code, (_, is_reject, _) in STATUS_TABLE.items() if is_reject
)
STATUS_LABELS: dict[int, str] = {code: label for code, (label, _, _) in STATUS_TABLE.items()}

IDLE_STATUS_CODE = 2
SUCCESS_STATUS_CODE = 0

# thresholds -> this are values that we choose
IDLE_MIN_ROWS = 30
IDLE_MIN_SECONDS = 30.0
GAP_FACTOR = 2.0  # a gap is flagged when > GAP_FACTOR * median sampling interval
FILE_BOUNDARY_TOLERANCE_SECONDS = 5.0  # max gap to treat two files as time-contiguous

# closure-event data_quality labels (see ingestion/closures.py)
DATA_QUALITY_SINGLE = "single"          # one closure, normal sampling interval
DATA_QUALITY_AGGREGATED = "aggregated"  # counter jumped by >1 within a normal interval
DATA_QUALITY_GAP = "gap"                # the transition spans a detected sampling gap
