from __future__ import annotations
# ruff: noqa: E402  # allow sys.path/bootstrap and docstring before imports

"""Public API and CLI entrypoint for the tip calculator package.

Re-exports the main API from `tipcalc` so that

    import tip as tipmod

continues to work after modularization. Also provides `python tip.py` entry.
"""

from tipcalc import (
    TipResult,
    compute_tip_split,
    parse_money,
    parse_percentage,
    parse_int,
    to_cents,
    CENT,
    HUNDRED,
    PERCENT_STEP,
    fmt_money,
    fmt_percent,
    print_results,
)
from tipcalc.cli import run_cli

import sys

__all__ = [
    "TipResult",
    "compute_tip_split",
    "parse_money",
    "parse_percentage",
    "parse_int",
    "to_cents",
    "CENT",
    "HUNDRED",
    "PERCENT_STEP",
    "fmt_money",
    "fmt_percent",
    "print_results",
    "run_cli",
]

if __name__ == "__main__":
    sys.exit(run_cli())
