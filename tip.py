from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Callable, List, Optional


# --- Money helpers ---
CENT = Decimal("0.01")
HUNDRED = Decimal("100")


def to_cents(value: Decimal) -> Decimal:
    """Round a Decimal to two fractional digits using bankers-friendly rounding."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_money(text: str, *, min_value: Decimal = Decimal("0.00")) -> Decimal:
    """Parse a currency string like "$1,234.56" into Decimal dollars.

    Accepts "$", commas, and whitespace. Enforces a non-negative minimum.
    """
    raw = text.strip().replace(",", "").replace("$", "")
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
    raw = text.strip().replace("%", "").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid percentage (e.g., 18 or 18%)") from exc
    if value < min_value or value > max_value:
        raise ValueError(f"Percentage must be between {min_value} and {max_value}")
    return value


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
def compute_tip_split(
    *,
    total_bill: Decimal,
    tax_amount: Decimal,
    tip_percent: Decimal,
    people: int,
):
    """Compute tip (always on pre-tax subtotal) and an exact split by cents.

    Returns a dict with keys: bill_before_tax, tip, final_total, per_person (List[Decimal]).
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
    tip = to_cents(bill_before_tax * (tip_percent / HUNDRED))
    final_total = to_cents(total_bill + tip)

    # Split the final total into exact cents that sum to the total
    total_cents = int((final_total / CENT).to_integral_value(rounding=ROUND_HALF_UP))
    base = total_cents // people
    remainder = total_cents % people
    shares_cents = [base + (1 if i < remainder else 0) for i in range(people)]
    per_person = [to_cents(Decimal(c) * CENT) for c in shares_cents]

    # Sanity check: the split must add up exactly to the total
    if to_cents(sum(per_person, Decimal("0"))) != final_total:
        raise AssertionError("Split calculation error: per-person amounts do not sum to total")

    return {
        "bill_before_tax": bill_before_tax,
        "tip": tip,
        "final_total": final_total,
        "per_person": per_person,
    }


# --- Presentation ---
def fmt_money(value: Decimal) -> str:
    return f"${to_cents(value):.2f}"


def print_results(
    *,
    bill_before_tax: Decimal,
    tax_amount: Decimal,
    original_total: Decimal,
    tip_percent: Decimal,
    tip: Decimal,
    final_total: Decimal,
    per_person: List[Decimal],
):
    print("\n--- Results ---")
    print(f"Subtotal (pre-tax): {fmt_money(bill_before_tax)}")
    print(f"Tax: {fmt_money(tax_amount)}")
    print(f"Original total (incl. tax): {fmt_money(original_total)}")
    print(f"Tip (pre-tax at {to_cents(tip_percent)}%): {fmt_money(tip)}")
    print(f"Total with tip: {fmt_money(final_total)}")
    print(
        f"Breakdown: {fmt_money(bill_before_tax)} + {fmt_money(tax_amount)} + {fmt_money(tip)} = {fmt_money(final_total)}"
    )
    if len(per_person) == 1:
        print(f"Each person pays: {fmt_money(per_person[0])}\n")
    else:
        shares = ", ".join(fmt_money(p) for p in per_person)
        print(f"Each person pays: {shares}\n")


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


def prompt_tip_percent() -> Decimal:
    """Prompt for a tip percentage with common quick-picks and a sensible default."""
    while True:
        s = input("Tip: [1] 15%  [2] 18%  [3] 20%  [Enter=20% or custom]: ").strip().lower()
        quick = {"": "20", "1": "15", "2": "18", "3": "20"}
        s = quick.get(s, s)
        try:
            return parse_percentage(s, min_value=Decimal("0"), max_value=Decimal("100"))
        except ValueError as e:
            print(f"Error: {e}")


def run_interactive() -> None:
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

        tip_percent = prompt_tip_percent()
        people = prompt_loop(
            "Split between how many people? [1]: ",
            lambda s: 1 if not s.strip() else parse_int(s, min_value=1),
        )

        results = compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
        )
        print_results(
            bill_before_tax=results["bill_before_tax"],
            tax_amount=tax_amount,
            original_total=total_bill,
            tip_percent=tip_percent,
            tip=results["tip"],
            final_total=results["final_total"],
            per_person=results["per_person"],
        )

        if not yes_no("Calculate another tip?", default_yes=False):
            break


# --- CLI ---
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tip Calculator with exact split and Decimal precision. Tip is calculated on the pre-tax subtotal.")
    parser.add_argument("--total", help="Total bill amount (including tax), e.g. 123.45 or $123.45")
    parser.add_argument("--tax", default="0", help="Tax amount, e.g. 10.23. Default: 0")
    parser.add_argument("--tip", default="20", help="Tip percentage, e.g. 20 or 20% (0-100). Default: 20")
    parser.add_argument("--people", type=int, default=1, help="Number of people to split between (>=1). Default: 1")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Force interactive mode regardless of provided flags.",
    )
    return parser


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Interactive if explicitly requested or if --total is not provided
    if args.interactive or args.total is None:
        try:
            run_interactive()
            return 0
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            return 0

    try:
        total_bill = parse_money(args.total, min_value=Decimal("0.01"))
        tax_amount = parse_money(args.tax, min_value=Decimal("0.00"))
        tip_percent = parse_percentage(args.tip, min_value=Decimal("0"), max_value=Decimal("100"))
        people = parse_int(str(args.people), min_value=1)
        results = compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
        )
    except ValueError as e:
        parser.error(str(e))
        return 2  # parser.error raises SystemExit

    print_results(
        bill_before_tax=results["bill_before_tax"],
        tax_amount=tax_amount,
        original_total=total_bill,
        tip_percent=tip_percent,
        tip=results["tip"],
        final_total=results["final_total"],
        per_person=results["per_person"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
