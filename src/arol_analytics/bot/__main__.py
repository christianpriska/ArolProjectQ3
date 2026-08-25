# Run as: PYTHONPATH=src python -m arol_analytics.bot [data_dir]

from __future__ import annotations

import sys

from arol_analytics.bot.terminal_sim import main

if __name__ == "__main__":
    sys.exit(main())
