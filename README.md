# Tip Calculator

Simple, precise tip calculator in Python. Uses Decimal for money-safe math.
By default, tip is calculated on the pre-tax subtotal (switchable with
`--post-tax`).

## Install

- Python 3.9+ recommended
- Optional clipboard support: `pip install pyperclip` to enable `--copy`
- Optional locale and currency formatting: `pip install Babel` (or install
  the `i18n` extra below)
- Optional QR codes: `pip install segno` (or install the `qr` extra below)
- Tests: `pip install pytest`

## Quick Start

- Interactive: `tip --interactive` (or `python tip.py --interactive`)
  - Quick tax presets: US 8.875%, CA-ON 13%, CA-BC 12%, EU-VAT 20% (remembers
    the last choice)
  - Live lookup: type `lookup 94105` (or any ZIP/postal code) to fetch and
    cache the local sales tax
  - Options work in interactive too: `--post-tax`, `--round-per-person
    up|down|nearest`, `--granularity 0.01|0.05|0.25`, `--currency
    USD|EUR|GBP|CAD`
- One-shot CLI: `tip --total 123.45 --tax 10.23 --people 3`
  - Auto tax lookup: `tip --total 108.00 --lookup-tax 94105 --tip 18 --people 2`
    (requires lookup API credentials)
  - Generate QR codes: `tip --total 108.00 --tip 18 --people 2 --qr --qr-note
    "Dinner"`
  - Manage profiles: `tip --profile dinner --total 80 --tip 20`
  - Use explicit tip: `--tip 18.5` (fractional values are allowed)
  - Uneven split: `--weights 2,1,1` (people inferred from weights)
- Machine output: `--json` or `--csv` (combine with `--copy` to clipboard)

### Package Entry Points

After installing the package you can run the CLI anywhere as `tip` (preferred)
or `tipcalc`:

```bash
pip install -e .
# with optional extras
pip install -e .[clipboard]
pip install -e .[i18n]

tip --help
python -c "import tip; print(tip.__version__)"
```

## Flags

- `--total`: Total bill amount including tax (for example `123.45` or
  `$1,234.56`).
- `--tax`: Sales tax amount (default `0`).
- `--qr`: Generate per-person QR code PNGs for payment links.
- `--qr-provider`: Provider for the QR payload (`venmo` or `generic`).
- `--qr-dir`: Directory path to store generated QR images.
- `--qr-note`: Note text embedded in the payment link.
- `--qr-scale`: Pixel scale for QR modules (default `5`).
- `--lookup-tax`: Fetch sales tax percent by ZIP or postal code (hits the
  configured API and caches for 24 hours).
- `--tax-country`: ISO country code for lookups (default `US`).
- `--tip`: Tip percent (0-100, fractional values allowed). If omitted, the
  default comes from config (18% unless overridden).
- `--people`: Number of people (>=1). Ignored if `--weights` is provided.
- `--weights`: Comma-separated positive numbers for proportional splits (for
  example `2,1,1`).
- `--post-tax`: Compute tip on the total (post-tax) instead of the pre-tax
  subtotal.
- `--round-per-person`: Rounding mode for per-person amounts: `nearest`
  (default), `up`, or `down`.
- `--granularity`: Rounding step for per-person amounts: `0.01`, `0.05`, or
  `0.25`.
- `--currency`: Display currency symbol: `USD`, `EUR`, `GBP`, or `CAD`.
- `--locale`: Locale for number and currency formatting (for example
  `en_US`). Requires Babel; with `--format auto|locale` it switches to
  locale-aware output, otherwise it falls back to the simple formatter.
- `--json` / `--csv`: Output machine-readable results.
- `--copy`: Copy the printed output to the clipboard (requires clipboard
  support or `pyperclip`).
- `--config`: Path to a config file (see below).
- `--profile`: Load saved defaults (people, rounding, locale) by name.
- `--save-profile`: Persist the current defaults under a name for later
  recall.
- `--strict-money`: Enforce canonical money format (`$1,234.56`) instead of
  permissive parsing.
- `--format`: Choose `auto`, `simple`, or `locale`. When `locale` (or `auto`
  with `--locale` provided) is selected, the output uses locale-aware
  formatting; otherwise it uses the simple formatter.

## Configurable Defaults

Defaults for the interactive quick picks and default tip can be set via a JSON
file or `.env` file.

JSON (`tipconfig.json`):

```json
{
  "default_tip_percent": 18,
  "quick_picks": [15, 18, 20]
}
```

Environment file (`.env`):

```dotenv
TIP_DEFAULT_PERCENT=18
TIP_QUICK_PICKS=15,18,20
```

### Tax Defaults and Persistence

Interactive mode remembers the last tax type and value you entered. The value
is stored in `tipstate.json` in your working directory (or alongside the
installed package) and is offered as the default the next time you run the
calculator. You can preseed it with the `TIP_LAST_TAX` environment variable,
for example `TIP_LAST_TAX=percent:13` or `TIP_LAST_TAX=amount:5.25`. Quick
presets are available for US 8.875%, CA-ON 13%, CA-BC 12%, and EU-VAT 20% for
one-key selection.

### Live Tax Lookup

- Use `--lookup-tax ZIP` for batch commands or type `lookup 94105` during
  interactive prompts to fetch the current combined rate.
- The default provider is the
  [api-ninjas sales tax API](https://api.api-ninjas.com/v1/salestax). Export
  `TIP_TAX_API_KEY` (and optionally `TIP_TAX_API_BASE`) before running.
- Lookup results are cached for 24 hours in `tax_cache.json`. Override with
  `TIP_TAX_CACHE_PATH` or disable with `TIP_TAX_CACHE_PATH=/dev/null`.
- Set `--tax-country` when your provider supports non-US regions.

### QR Codes

- Install the optional dependency with `pip install tip-calculator[qr]` to
  enable image generation.
- Run with `--qr` to emit PNGs (default directory `qr_codes/`) for each
  per-person share.
- Adjust the link provider (`--qr-provider`), note (`--qr-note`), output
  folder (`--qr-dir`), and image scale (`--qr-scale`).

Pass a custom path with `--config path/to/tipconfig.json`.

### Profiles

- Store your go-to setup with `--save-profile dinner --people 4 --round-per-
  person nearest --granularity 0.25 --locale en_US`.
- Reuse it anytime using `--profile dinner` (you can still override
  individual flags).
- Profiles are saved to `tip_profiles.json` in the current directory; override
  with `TIP_PROFILES_PATH` if needed.

## Parsing, Currency, and Rounding Notes

- Money parsing is permissive by default: accepts `$`, commas, spaces, and
  inputs like `.5` (which is interpreted as `$0.50`). A strict validator is
  available in code for canonical `$1,234.56` format.
- Percentages accept fractional values and are clamped to two decimals for
  calculations and display.
- Splits always sum exactly to the final total. With rounding steps, the last
  person adjusts to preserve the exact sum.

### Currency Assumptions

- Calculations are performed in two decimal places (cents). This matches USD,
  EUR, GBP, and CAD.
### Cash Rounding (Canada)

Cash payments in Canada round **only the final total after tax and tip** to the nearest five cents.
Per-person amounts stay at cent precision for convenience;
nickel rounding happens once on the grand total.

| Payment method | Rounding rule | Example |
| --- | --- | --- |
| Cash (CA) | Round final total to the nearest $0.05 | $67.32 -> $67.30, $67.33 -> $67.35 |
| Card / digital | No additional rounding | $67.33 stays $67.33 |

When you settle in cash, apply the nickel rounding once to the grand total rather than to each line item or per-person share.

- If you use `--locale` and have Babel installed, printed amounts use
  locale-aware formatting for separators and symbol placement. The numeric
  precision remains two decimals. Currencies with non-two-decimal minor units
  (for example JPY) are not fully supported by the math at this time.

## Examples

- Interactive pre-tax 18%: `tip --interactive`
- One-shot, equal split: `tip --total 123.45 --tax 10.23 --people 3`
- Auto tax lookup (ZIP): `tip --total 108.00 --lookup-tax 94105 --tip 18
  --people 2`
- Weighted split (2,1,1): `tip --total 123.45 --tax 10 --weights 2,1,1`
- Post-tax tip: `tip --total 123.45 --tax 10 --post-tax`
- Round per-person to quarters: `tip --total 123.45 --tax 10 --people 3
  --granularity 0.25`
- Locale display (`en_US`): `tip --total 12345.67 --tax 100.25 --currency USD
  --format locale --locale en_US`
- JSON output plus copy: `tip --total 123.45 --tax 10 --people 2 --json
  --copy`
- Strict money parsing: `tip --total "$1,234.56" --tax 100 --strict-money`

## Design Notes

- Exact-sum invariant: All calculations use `Decimal` and rounding that
  guarantees `sum(per_person) == final_total`.
- Rounding preferences: When a granularity (for example `0.25`) is chosen, the
  first `n-1` shares are rounded according to the selected mode (`nearest`,
  `up`, or `down`), and the last share absorbs any remainder so the sum remains
  exact.
- Weights: For `--weights a,b,c`, each person's share is proportional to their
  weight; cents are distributed to those with the largest fractional remainders
  first.

## Testing

- Run all tests: `pytest -q`


