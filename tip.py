from __future__ import annotations
# ruff: noqa: E402  # allow sys.path/bootstrap and docstring before imports

"""Public API and CLI entrypoint for the tip calculator package.

Re-exports the main API from `tipcalc` so that

    import tip as tipmod

continues to work after modularization. Also provides `python tip.py` entry.
"""

import importlib.metadata as importlib_metadata
import sys

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
    lookup_tax_rate,
    TaxLookupError,
    TaxLookupResult,
    generate_qr_codes,
    QRGenerationError,
)
from tipcalc.cli import run_cli

try:
    _distribution_version = importlib_metadata.version("tip-calculator")
except importlib_metadata.PackageNotFoundError:
    __version__ = "0+unknown"
else:
    __version__ = _distribution_version or "0+unknown"

__all__ = [
    "__version__",
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
    "lookup_tax_rate",
    "TaxLookupError",
    "TaxLookupResult",
    "generate_qr_codes",
    "QRGenerationError",
    "run_cli",
]

if __name__ == "__main__":
    sys.exit(run_cli())
