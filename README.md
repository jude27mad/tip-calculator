# Tip Calculator
Simple, precise tip calculator in Python. Uses Decimal for money-safe math. By default, tip is calculated on the pre-tax subtotal (switchable with `--post-tax`).

## Install
- Python 3.9+ recommended
- Optional clipboard: `pip install pyperclip` to enable `--copy`
- Optional locale/currency formatting: `pip install Babel` (or install the `i18n` extra below)
- Tests: `pip install pytest`

## Quick Start
- Interactive: `python tip.py --interactive`
  - Options work in interactive too: `--post-tax`, `--round-per-person up|down|nearest`, `--granularity 0.01|0.05|0.25`, `--currency USD|EUR|GBP|CAD`
- One-shot CLI: `python tip.py --total 123.45 --tax 10.23 --people 3`
  - Use explicit tip: `--tip 18.5` (fractional OK)
  - Uneven split: `--weights 2,1,1` (people inferred from weights)
- Machine output: `--json` or `--csv` (combine with `--copy` to clipboard)

### Package entry point (optional)
After installing in editable mode you can run the CLI anywhere as `tipcalc`:

```
pip install -e .
# with optional extras
pip install -e .[clipboard]
pip install -e .[i18n]

tipcalc --help
```

## Flags
- `--total`: Total bill amount including tax (e.g., `123.45`, `$1,234.56`).
- `--tax`: Sales tax amount (default `0`).
- `--tip`: Tip percent (0–100, fractional allowed). If omitted, default comes from config (20% unless overridden).
- `--people`: Number of people (>=1). Ignored if `--weights` is provided.
- `--weights`: Comma-separated positive numbers for proportional split (e.g., `2,1,1`).
- `--post-tax`: Compute tip on the total (post-tax) instead of the pre-tax subtotal.
- `--round-per-person`: Rounding mode for per-person amounts: `nearest` (default), `up`, or `down`.
- `--granularity`: Rounding step for per-person amounts: `0.01`, `0.05`, or `0.25`.
- `--currency`: Display currency symbol: `USD|EUR|GBP|CAD`.
- `--locale`: Locale for number/currency formatting (e.g., `en_US`). Requires Babel to be installed. If omitted, a simple fallback formatter is used.
- `--json` / `--csv`: Output machine-readable results.
- `--copy`: Copy the printed output to the clipboard (requires clipboard support or `pyperclip`).
- `--config`: Path to a config file (see below).

## Configurable Defaults
Defaults for the interactive quick-picks and default tip can be set via a JSON file or `.env`.

JSON (`tipconfig.json`):
```
{
  "default_tip_percent": 20,
  "quick_picks": [15, 18, 20]
}
```

.env:
```
TIP_DEFAULT_PERCENT=20
TIP_QUICK_PICKS=15,18,20
```
Pass a custom path with `--config path/to/tipconfig.json`.

## Parsing, Currency & Rounding Notes
- Money parsing is permissive by default: accepts `$`, commas, spaces, and inputs like `.5` (=$0.50). A strict validator is available in code for canonical `$1,234.56` format.
- Percentages accept fractional values and are clamped to 2 decimals for math/display.
- Splits always sum exactly to the final total. With rounding steps, the last person adjusts to preserve the exact sum.

Currency assumptions:
- Calculations are performed in two decimal places (cents). This matches `USD/EUR/GBP/CAD`.
- If you use `--locale` and have Babel installed, printed amounts use locale-aware formatting (thousands separators, symbol placement). The numeric precision remains two decimals. Currencies with non‑two‑decimal minor units (e.g., JPY) are not fully supported by the math at this time.

## Testing
- Run all tests: `pytest -q`
