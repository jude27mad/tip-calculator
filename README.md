# Tip Calculator
Simple, precise tip calculator in Python. Uses Decimal for money-safe math. By default, tip is calculated on the pre-tax subtotal (switchable with `--post-tax`).

## Install
- Python 3.9+ recommended
- Optional clipboard: `pip install pyperclip` to enable `--copy`
- Optional locale/currency formatting: `pip install Babel` (or install the `i18n` extra below)
- Optional QR codes: `pip install segno` (or install the `qr` extra below)
- Tests: `pip install pytest`

## Quick Start
- Interactive: `python tip.py --interactive`
  - Quick tax presets: US 8.875%, CA-ON 13%, CA-BC 12%, EU-VAT 20% (remembers the last choice)
  - Live lookup: type `lookup 94105` (or any ZIP/postal code) to fetch and cache the local sales tax
  - Options work in interactive too: `--post-tax`, `--round-per-person up|down|nearest`, `--granularity 0.01|0.05|0.25`, `--currency USD|EUR|GBP|CAD`
- One-shot CLI: `python tip.py --total 123.45 --tax 10.23 --people 3`
  - Auto tax lookup: `python tip.py --total 108.00 --lookup-tax 94105 --tip 18 --people 2` (requires lookup API credentials)
  - Generate QR codes: `python tip.py --total 108.00 --tip 18 --people 2 --qr --qr-note "Dinner"`
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
- `--qr`: Generate per-person QR code PNGs for payment links.
- `--qr-provider`: Provider for the QR payload (`venmo` or `generic`).
- `--qr-dir`: Directory path to store generated QR images.
- `--qr-note`: Note text embedded in the payment link.
- `--qr-scale`: Pixel scale for QR modules (default `5`).
- `--lookup-tax`: Fetch sales tax percent by ZIP/postal code (hits the configured API and caches for 24h).
- `--tax-country`: ISO country code for lookups (default `US`).
- `--tip`: Tip percent (0–100, fractional allowed). If omitted, default comes from config (18% unless overridden).
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
- `--strict-money`: Enforce canonical money format (`$1,234.56`) instead of permissive parsing.
- `--format`: `auto|simple|locale` — if `locale` (or `auto` with `--locale` provided), uses locale-aware formatting for output; otherwise uses a simple formatter.
- `--locale`: Locale used when `--format locale` (e.g., `en_US`). Requires Babel.

## Configurable Defaults
Defaults for the interactive quick-picks and default tip can be set via a JSON file or `.env`.

JSON (`tipconfig.json`):
```
{
  "default_tip_percent": 18,
  "quick_picks": [15, 18, 20]
}
```

.env:
```
TIP_DEFAULT_PERCENT=18
TIP_QUICK_PICKS=15,18,20
```

### Tax defaults & persistence

Interactive mode remembers the last tax type/value you entered. The value is stored in `tipstate.json` in your working directory (or alongside the installed package) and offered as the default the next time you run the calculator. You can preseed it with the `TIP_LAST_TAX` environment variable, e.g. `TIP_LAST_TAX=percent:13` or `TIP_LAST_TAX=amount:5.25`. Quick presets are available for US 8.875%, CA-ON 13%, CA-BC 12%, and EU-VAT 20% for one-key selection.

### Live tax lookup

- Use `--lookup-tax ZIP` for batch commands or type `lookup 94105` during interactive prompts to fetch the current combined rate.
- The default provider is https://api.api-ninjas.com/v1/salestax - export `TIP_TAX_API_KEY` (and optionally `TIP_TAX_API_BASE`) before running.
- Lookup results are cached for 24h in `tax_cache.json`. Override with `TIP_TAX_CACHE_PATH` or disable with `TIP_TAX_CACHE_PATH=/dev/null`.
- Set `--tax-country` when your provider supports non-US regions.

### QR codes

- Install the optional dependency with `pip install tip-calculator[qr]` to enable image generation.
- Run with `--qr` to emit PNGs (default directory `qr_codes/`) for each per-person share.
- Adjust the link provider (`--qr-provider`), note (`--qr-note`), output folder (`--qr-dir`), and image scale (`--qr-scale`).

Pass a custom path with `--config path/to/tipconfig.json`.

## Parsing, Currency & Rounding Notes
- Money parsing is permissive by default: accepts `$`, commas, spaces, and inputs like `.5` (=$0.50). A strict validator is available in code for canonical `$1,234.56` format.
- Percentages accept fractional values and are clamped to 2 decimals for math/display.
- Splits always sum exactly to the final total. With rounding steps, the last person adjusts to preserve the exact sum.

Currency assumptions:
- Calculations are performed in two decimal places (cents). This matches `USD/EUR/GBP/CAD`.
- If you use `--locale` and have Babel installed, printed amounts use locale-aware formatting (thousands separators, symbol placement). The numeric precision remains two decimals. Currencies with non‑two‑decimal minor units (e.g., JPY) are not fully supported by the math at this time.

## Examples

| Use case | Command |
|---|---|
| Interactive pre-tax 18% | `tipcalc --interactive` |
| One-shot, equal split | `tipcalc --total 123.45 --tax 10.23 --people 3` |
| Auto tax lookup (ZIP) | `tipcalc --total 108.00 --lookup-tax 94105 --tip 18 --people 2` |
| Weighted split (2,1,1) | `tipcalc --total 123.45 --tax 10 --weights 2,1,1` |
| Post-tax tip | `tipcalc --total 123.45 --tax 10 --post-tax` |
| Round per-person to quarters | `tipcalc --total 123.45 --tax 10 --people 3 --granularity 0.25` |
| Locale display (en_US) | `tipcalc --total 12345.67 --tax 100.25 --currency USD --format locale --locale en_US` |
| JSON output + copy | `tipcalc --total 123.45 --tax 10 --people 2 --json --copy` |
| Strict money parsing | `tipcalc --total "$1,234.56" --tax 100 --strict-money` |

## Design Notes

- Exact-sum invariant: All calculations use Decimal and rounding that guarantees `sum(per_person) == final_total`.
- Rounding preferences: When a granularity (e.g., `0.25`) is chosen, the first `n-1` shares are rounded according to the selected mode (`nearest|up|down`), and the last share absorbs any remainder so the sum remains exact.
- Weights: For `--weights a,b,c`, each person’s share is proportional to their weight; cents are distributed to those with the largest fractional remainders first.

## Testing
- Run all tests: `pytest -q`

