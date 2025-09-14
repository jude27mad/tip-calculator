from __future__ import annotations

import argparse
import sys
import re
import json
import os
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING
import subprocess
import platform
from typing import Callable, List, Optional
from dataclasses import dataclass


# --- Money helpers ---
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
PERCENT_STEP = Decimal("0.01")  # display percent with up to 2 decimals


# --- Configuration ---
@dataclass
class AppConfig:
    default_tip_percent: Decimal = Decimal("20")
    quick_picks: List[Decimal] = None  # e.g., [15, 18, 20]


def _default_config() -> AppConfig:
    return AppConfig(
        default_tip_percent=Decimal("20"),
        quick_picks=[Decimal("15"), Decimal("18"), Decimal("20")],
    )


def _parse_env_quick_picks(text: str) -> List[Decimal]:
    vals: List[Decimal] = []
    for part in text.split(","):
        part = part.strip().replace("%", "")
        if not part:
            continue
        vals.append(Decimal(part).quantize(PERCENT_STEP, rounding=ROUND_HALF_UP))
    return vals or [Decimal("15"), Decimal("18"), Decimal("20")]


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load defaults for tip quick-picks and default tip.

    Sources (in order):
      - JSON file if provided via --config or found as 'tipconfig.json' in CWD
        or next to this script
      - .env file with TIP_DEFAULT_PERCENT and TIP_QUICK_PICKS
      - Built-in defaults (20% default; quick picks 15/18/20)
    """
    cfg = _default_config()

    # JSON source
    json_candidates: List[Path] = []
    if path:
        json_candidates.append(Path(path).expanduser())
    json_candidates.append(Path.cwd() / "tipconfig.json")
    json_candidates.append(Path(__file__).with_name("tipconfig.json"))
    for p in json_candidates:
        try:
            if p.is_file():
                data = json.loads(p.read_text())
                if "default_tip_percent" in data:
                    cfg.default_tip_percent = Decimal(str(data["default_tip_percent"]))\
                        .quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
                if "quick_picks" in data and isinstance(data["quick_picks"], list):
                    cfg.quick_picks = [
                        Decimal(str(v)).quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
                        for v in data["quick_picks"]
                    ]
                break
        except Exception:
            # Fall back silently to other sources
            pass

    # .env source
    env_candidates: List[Path] = []
    env_candidates.append(Path.cwd() / ".env")
    env_candidates.append(Path(__file__).with_name(".env"))
    for p in env_candidates:
        try:
            if p.is_file():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip()
                    if k == "TIP_DEFAULT_PERCENT":
                        cfg.default_tip_percent = Decimal(v.replace("%", "")).quantize(
                            PERCENT_STEP, rounding=ROUND_HALF_UP
                        )
                    elif k == "TIP_QUICK_PICKS":
                        cfg.quick_picks = _parse_env_quick_picks(v)
                break
        except Exception:
            pass

    # Ensure quick_picks present
    if not cfg.quick_picks:
        cfg.quick_picks = [Decimal("15"), Decimal("18"), Decimal("20")]
    return cfg


def to_cents(value: Decimal) -> Decimal:
    """Round a Decimal to two fractional digits using bankers-friendly rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(
    text: str,
    *,
    min_value: Decimal = Decimal("0.00"),
    strict: bool = False,
) -> Decimal:
    """Parse a US currency string into Decimal dollars.

    Always returns a non-negative Decimal rounded to cents. In permissive mode
    (default), accepts a loose format like "$1,234.56", "1234.56$", or
    "1,234.56" by stripping "$" and commas anywhere.

    If ``strict=True``, validates the canonical format before parsing:
      - Optional leading "$" only at the start
      - Digits without commas (e.g., 1234.56) OR properly grouped commas
        (e.g., 1,234.56 or 12,345,678)
      - Optional decimal point with 1–2 digits
      - No trailing characters
    """
    s = text.strip()
    if strict:
        # ^\s*\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*$
        money_strict_re = re.compile(
            r"^\s*\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*$"
        )
        if not money_strict_re.match(s):
            raise ValueError("Enter a valid dollar amount like $1,234.56")
    # In permissive mode, normalize common typos: remove all internal spaces
    # so inputs like "$ 1,234.5" or ".5" pass. Commas and "$" are ignored.
    raw = re.sub(r"\s+", "", s).replace(",", "").replace("$", "")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid dollar amount (e.g., 12.34)") from exc
    if value < min_value:
        raise ValueError(f"Amount must be >= ${to_cents(min_value)}")
    return to_cents(value)


def parse_percentage(
    text: str,
    *,
    min_value: Decimal = Decimal("0"),
    max_value: Decimal = Decimal("100"),
) -> Decimal:
    """Parse a percent string like "15%" into a Decimal percent (0-100)."""
    s = text.strip()
    # Normalize whitespace like "15 %" -> "15%" before removing the symbol.
    raw = re.sub(r"\s+", "", s).replace("%", "").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid percentage (e.g., 18 or 18%)") from exc
    if value < min_value or value > max_value:
        raise ValueError(f"Percentage must be between {min_value} and {max_value}")
    # Clamp to two decimal places for consistent math and display
    return value.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)


def parse_int(text: str, *, min_value: int = 1) -> int:
    """Parse an integer with a lower bound."""
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError("Enter a whole number") from exc
    if value < min_value:
        raise ValueError(f"Value must be >= {min_value}")
    return value


# --- Core calculation ---


@dataclass
class TipResult:
    """Structured result of a tip calculation.

    Attributes
    - bill_before_tax: Pre-tax subtotal used as the tip base.
    - tip: The computed tip amount.
    - final_total: Total bill including tax and tip.
    - per_person: Exact per-person amounts that sum to final_total.
    """
    bill_before_tax: Decimal
    tip: Decimal
    final_total: Decimal
    per_person: List[Decimal]
def compute_tip_split(
    *,
    total_bill: Decimal,
    tax_amount: Decimal,
    tip_percent: Decimal,
    people: int,
    tip_on_pretax: bool = True,
    round_mode: str = "nearest",
    granularity: Decimal = CENT,
    weights: Optional[List[Decimal]] = None,
)-> TipResult:
    """Compute tip (always on pre-tax subtotal) and an exact split by cents.

    Returns a TipResult with fields: bill_before_tax, tip, final_total, per_person.
    """
    if total_bill < Decimal("0.01"):
        raise ValueError("Total bill must be at least $0.01")
    if tax_amount < Decimal("0"):
        raise ValueError("Tax amount cannot be negative")
    if tax_amount >= total_bill:
        raise ValueError("Tax amount cannot be greater than or equal to the total bill")
    if people < 1:
        raise ValueError("People must be at least 1")

    bill_before_tax = to_cents(total_bill - tax_amount)
    tip_base = bill_before_tax if tip_on_pretax else total_bill
    tip = to_cents(tip_base * (tip_percent / HUNDRED))
    final_total = to_cents(total_bill + tip)

    # Split the final total into exact cents that sum to the total
    def _round_to_step(value: Decimal, step: Decimal, mode: str) -> Decimal:
        steps = (value / step)
        if mode == "nearest":
            n = steps.quantize(Decimal(0), rounding=ROUND_HALF_UP)
        elif mode == "up":
            n = steps.to_integral_value(rounding=ROUND_CEILING)
        elif mode == "down":
            n = steps.to_integral_value(rounding=ROUND_FLOOR)
        else:
            raise ValueError("round_mode must be one of: nearest, up, down")
        return to_cents(n * step)

    # First, compute an exact split by cents
    total_cents = int((final_total / CENT).to_integral_value(rounding=ROUND_HALF_UP))
    if weights:
        if len(weights) != people:
            raise ValueError("Length of weights must equal number of people")
        w = [Decimal(str(x)) for x in weights]
        if any(x <= 0 for x in w):
            raise ValueError("Weights must be positive numbers")
        w_sum = sum(w, Decimal("0"))
        raw_shares = [(Decimal(total_cents) * x) / w_sum for x in w]
        floors = [int(s) for s in raw_shares]
        remainder = total_cents - sum(floors)
        # Distribute remaining cents to largest fractional parts
        fracs = [(i, raw_shares[i] - floors[i]) for i in range(people)]
        fracs.sort(key=lambda t: t[1], reverse=True)
        shares_cents = floors[:]
        for i in range(remainder):
            shares_cents[fracs[i][0]] += 1
    else:
        base = total_cents // people
        remainder = total_cents % people
        shares_cents = [base + (1 if i < remainder else 0) for i in range(people)]
    per_person = [to_cents(Decimal(c) * CENT) for c in shares_cents]

    # Apply optional rounding preference for per-person amounts
    if granularity != CENT or round_mode != "nearest":
        if people == 1:
            # Nothing to round for single person; keep total exact
            per_person = [final_total]
        else:
            rounded: List[Decimal] = []
            for i in range(people - 1):
                rounded.append(_round_to_step(per_person[i], granularity, round_mode))
            rounded_sum = to_cents(sum(rounded, Decimal("0")))
            # If we overshot the total, reduce earlier shares by granularity until feasible
            if rounded_sum > final_total:
                diff = rounded_sum - final_total
                step = granularity
                i = 0
                while diff > Decimal("0") and i < len(rounded):
                    dec = min(step, diff)
                    if rounded[i] - dec >= Decimal("0"):
                        rounded[i] = to_cents(rounded[i] - dec)
                        diff = to_cents(diff - dec)
                    i += 1
                rounded_sum = to_cents(sum(rounded, Decimal("0")))
            last = to_cents(final_total - rounded_sum)
            per_person = rounded + [last]

    # Sanity check: the split must add up exactly to the total
    if to_cents(sum(per_person, Decimal("0"))) != final_total:
        raise AssertionError("Split calculation error: per-person amounts do not sum to total")

    return TipResult(
        bill_before_tax=bill_before_tax,
        tip=tip,
        final_total=final_total,
        per_person=per_person,
    )


# --- Presentation ---
def currency_symbol(code: str) -> str:
    code = (code or "USD").upper()
    return {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "C$"}.get(code, "$")


def fmt_money(value: Decimal, *, symbol: str = "$") -> str:
    return f"{symbol}{to_cents(value):.2f}"


def fmt_percent(value: Decimal) -> str:
    """Format a percentage with up to two decimal places, trimming trailing zeros.

    Examples: 18 -> "18", 18.5 -> "18.5", 18.00 -> "18"
    """
    q = value.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
    return f"{q:.2f}".rstrip("0").rstrip(".")

def print_results(
    *,
    bill_before_tax: Decimal,
    tax_amount: Decimal,
    original_total: Decimal,
    tip_percent: Decimal,
    tip_base_label: str,
    tip: Decimal,
    final_total: Decimal,
    per_person: List[Decimal],
    currency: str = "USD",
)-> str:
    lines: List[str] = []
    lines.append("\n--- Results ---")
    sym = currency_symbol(currency)
    lines.append(f"Subtotal (pre-tax): {fmt_money(bill_before_tax, symbol=sym)}")
    lines.append(f"Tax: {fmt_money(tax_amount, symbol=sym)}")
    lines.append(f"Original total (incl. tax): {fmt_money(original_total, symbol=sym)}")
    lines.append(f"Tip ({tip_base_label} at {fmt_percent(tip_percent)}%): {fmt_money(tip, symbol=sym)}")
    lines.append(f"Total with tip: {fmt_money(final_total, symbol=sym)}")
    lines.append(
        f"Breakdown: {fmt_money(bill_before_tax, symbol=sym)} + {fmt_money(tax_amount, symbol=sym)} + {fmt_money(tip, symbol=sym)} = {fmt_money(final_total, symbol=sym)}"
    )
    if len(per_person) == 1:
        lines.append(f"Each person pays: {fmt_money(per_person[0], symbol=sym)}")
    else:
        shares = ", ".join(fmt_money(p, symbol=sym) for p in per_person)
        lines.append(f"Each person pays: {shares}")
    return "\n".join(lines) + "\n"


def decimals_to_strings(items: List[Decimal]) -> List[str]:
    return [f"{to_cents(x):.2f}" for x in items]


def results_to_dict(*,
    bill_before_tax: Decimal,
    tax_amount: Decimal,
    original_total: Decimal,
    tip_percent: Decimal,
    tip_base: str,
    tip: Decimal,
    final_total: Decimal,
    per_person: List[Decimal],
    currency: str,
    people: int,
    weights: Optional[List[Decimal]],
) -> dict:
    return {
        "currency": currency,
        "tip_base": tip_base,
        "bill_before_tax": f"{to_cents(bill_before_tax):.2f}",
        "tax_amount": f"{to_cents(tax_amount):.2f}",
        "original_total": f"{to_cents(original_total):.2f}",
        "tip_percent": f"{tip_percent:.2f}",
        "tip": f"{to_cents(tip):.2f}",
        "final_total": f"{to_cents(final_total):.2f}",
        "people": people,
        "weights": [str(w) for w in (weights or [])],
        "per_person": decimals_to_strings(per_person),
    }


def dict_to_csv_line(d: dict) -> str:
    # A simple CSV with fixed columns; per_person joined by spaces; weights by commas
    cols = [
        "currency",
        "tip_base",
        "bill_before_tax",
        "tax_amount",
        "original_total",
        "tip_percent",
        "tip",
        "final_total",
        "people",
        "weights",
        "per_person",
    ]
    row = {
        **d,
        "weights": ",".join(d.get("weights", [])),
        "per_person": ",".join(d.get("per_person", [])),
    }
    return ",".join(str(row.get(k, "")) for k in cols)


def copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    try:
        system = platform.system()
        if system == "Windows":
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, close_fds=True)
            p.stdin.write(text.encode("utf-16le"))
            p.stdin.close()
            return p.wait() == 0
        elif system == "Darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode())
            return p.returncode == 0
        else:
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(input=text.encode())
                    if p.returncode == 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


# --- Interactive prompts ---
def prompt_loop(prompt: str, parser: Callable[[str], object]) -> object:
    """Prompt until the parser succeeds, showing the parser's error message when it fails."""
    while True:
        try:
            return parser(input(prompt))
        except ValueError as e:
            print(f"Error: {e}")


def yes_no(prompt: str, *, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        ans = input(f"{prompt} {suffix} ").strip().lower()
        if not ans:
            return default_yes
        if ans in {"y", "yes"}:
            return True
        if ans in {"n", "no"}:
            return False
        print("Please answer 'y' or 'n'.")


def prompt_tip_percent(config: AppConfig) -> Decimal:
    """Prompt for a tip percentage using config-driven quick-picks and default."""
    picks = [str(p.normalize()) for p in config.quick_picks]
    # Build a dynamic menu like: [1] 15%  [2] 18%  [3] 20%
    menu = "  ".join(f"[{i+1}] {p}%" for i, p in enumerate(picks))
    default_str = str(config.default_tip_percent.normalize())
    while True:
        s = input(f"Tip: {menu}  [Enter={default_str}% or custom]: ").strip().lower()
        quick_map = {str(i + 1): picks[i] for i in range(len(picks))}
        quick_map[""] = default_str
        s = quick_map.get(s, s)
        try:
            return parse_percentage(s, min_value=Decimal("0"), max_value=Decimal("100"))
        except ValueError as e:
            print(f"Error: {e}")


def run_interactive(config: AppConfig, *, round_mode: str, granularity: Decimal, tip_on_pretax: bool) -> None:
    print("--- Tip Calculator ---")
    while True:
        total_bill = prompt_loop(
            "Total bill (including tax): $",
            lambda s: parse_money(s, min_value=Decimal("0.01")),
        )
        # Tax must be >= 0 and < total
        while True:
            tax_amount = prompt_loop(
                "Sales tax amount (enter 0 if none): $",
                lambda s: parse_money(s, min_value=Decimal("0.00")),
            )
            if tax_amount >= total_bill:
                print("Error: Tax amount cannot be greater than or equal to the total bill.")
            else:
                break

        tip_percent = prompt_tip_percent(config)
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.")
        people = prompt_loop(
            "Split between how many people? [1]: ",
            lambda s: 1 if not s.strip() else parse_int(s, min_value=1),
        )

        results = compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
            tip_on_pretax=tip_on_pretax,
            round_mode=round_mode,
            granularity=granularity,
        )
        print(
            print_results(
                bill_before_tax=results.bill_before_tax,
                tax_amount=tax_amount,
                original_total=total_bill,
                tip_percent=tip_percent,
                tip_base_label=("pre-tax" if tip_on_pretax else "post-tax"),
                tip=results.tip,
                final_total=results.final_total,
                per_person=results.per_person,
            )
        )

        if not yes_no("Calculate another tip?", default_yes=False):
            break


# --- CLI ---
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tip Calculator with exact split and Decimal precision. Default: tip on pre-tax subtotal (use --post-tax to tip on total).")
    parser.add_argument("--total", help="Total bill amount (including tax), e.g. 123.45 or $123.45")
    parser.add_argument("--tax", default="0", help="Tax amount, e.g. 10.23. Default: 0")
    parser.add_argument("--tip", default=None, help="Tip percentage, e.g. 20 or 20% (0-100). Default comes from config")
    parser.add_argument("--people", type=int, default=1, help="Number of people to split between (>=1). Default: 1")
    parser.add_argument("--post-tax", action="store_true", help="Compute tip on total (post-tax) instead of pre-tax subtotal")
    parser.add_argument("--round-per-person", choices=["nearest", "up", "down"], default="nearest", help="Rounding mode for per-person amounts")
    parser.add_argument("--granularity", choices=["0.01", "0.05", "0.25"], default="0.01", help="Rounding step for per-person amounts")
    parser.add_argument("--config", help="Path to JSON or .env with TIP_DEFAULT_PERCENT and TIP_QUICK_PICKS")
    parser.add_argument("--weights", help="Comma-separated weights, e.g., 2,1,1 to split unevenly")
    parser.add_argument("--currency", choices=["USD", "EUR", "GBP", "CAD"], default="USD", help="Currency for display and symbol")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--csv", action="store_true", help="Output results as CSV")
    parser.add_argument("--copy", action="store_true", help="Copy the output to clipboard")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive mode regardless of provided flags.",
    )
    return parser


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = load_config(args.config)
    round_mode = args.round_per_person
    granularity = Decimal(args.granularity)
    tip_on_pretax = not args.post_tax
    currency = args.currency

    # Parse weights if provided
    weights: Optional[List[Decimal]] = None
    if args.weights:
        try:
            parts = [p.strip() for p in args.weights.split(",") if p.strip()]
            weights = [Decimal(p) for p in parts]
            if not weights:
                raise ValueError
        except Exception:
            parser.error("--weights must be a comma-separated list of positive numbers")

    # Interactive if explicitly requested or if --total is not provided
    if args.interactive or args.total is None:
        try:
            run_interactive(config, round_mode=round_mode, granularity=granularity, tip_on_pretax=tip_on_pretax)
            return 0
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            return 0

    try:
        total_bill = parse_money(args.total, min_value=Decimal("0.01"))
        tax_amount = parse_money(args.tax, min_value=Decimal("0.00"))
        tip_input = args.tip if args.tip is not None else str(config.default_tip_percent)
        tip_percent = parse_percentage(tip_input, min_value=Decimal("0"), max_value=Decimal("100"))
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.", file=sys.stderr)
        if tax_amount >= total_bill:
            # compute_tip_split will error; surface a clearer pre-check message as well
            print(
                "Warning: Tax amount is greater than or equal to the total bill; this will be rejected.",
                file=sys.stderr,
            )
        people = len(weights) if weights is not None else parse_int(str(args.people), min_value=1)
        results = compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
            tip_on_pretax=tip_on_pretax,
            round_mode=round_mode,
            granularity=granularity,
            weights=weights,
        )
    except ValueError as e:
        parser.error(str(e))
        return 2  # parser.error raises SystemExit

    # Decide output format
    d = results_to_dict(
        bill_before_tax=results.bill_before_tax,
        tax_amount=tax_amount,
        original_total=total_bill,
        tip_percent=tip_percent,
        tip_base=("pre-tax" if tip_on_pretax else "post-tax"),
        tip=results.tip,
        final_total=results.final_total,
        per_person=results.per_person,
        currency=currency,
        people=people,
        weights=weights,
    )
    if args.json:
        out = json.dumps(d)
    elif args.csv:
        # Print header + row for convenience
        header = "currency,tip_base,bill_before_tax,tax_amount,original_total,tip_percent,tip,final_total,people,weights,per_person"
        out = header + "\n" + dict_to_csv_line(d)
    else:
        out = print_results(
            bill_before_tax=results.bill_before_tax,
            tax_amount=tax_amount,
            original_total=total_bill,
            tip_percent=tip_percent,
            tip_base_label=("pre-tax" if tip_on_pretax else "post-tax"),
            tip=results.tip,
            final_total=results.final_total,
            per_person=results.per_person,
            currency=currency,
        )
    print(out)
    if args.copy:
        if not copy_to_clipboard(out):
            print("(Could not copy to clipboard on this system)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
