from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeVar

from .formats import (
    print_results,
    results_to_dict,
    dict_to_csv_line,
    copy_to_clipboard,
)
from .parsing import parse_money, parse_percentage, parse_int
from .tip_core import compute_tip_split


@dataclass
class AppConfig:
    default_tip_percent: Decimal
    quick_picks: List[Decimal]


def _default_config() -> AppConfig:
    return AppConfig(default_tip_percent=Decimal("18"), quick_picks=[Decimal("15"), Decimal("18"), Decimal("20")])


def _format_decimal(value: Decimal) -> str:
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def _parse_env_quick_picks(text: str) -> List[Decimal]:
    vals: List[Decimal] = []
    for part in text.split(","):
        part = part.strip().replace("%", "")
        if not part:
            continue
        vals.append(Decimal(part).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return vals or [Decimal("15"), Decimal("18"), Decimal("20")]


def load_config(path: Optional[str] = None) -> AppConfig:
    cfg = _default_config()

    # JSON candidates
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
                    cfg.default_tip_percent = Decimal(str(data["default_tip_percent"]))
                if "quick_picks" in data and isinstance(data["quick_picks"], list):
                    cfg.quick_picks = [Decimal(str(v)) for v in data["quick_picks"]]
                break
        except Exception:
            pass

    # .env candidates
    env_candidates: List[Path] = [Path.cwd() / ".env", Path(__file__).with_name(".env")]
    for p in env_candidates:
        try:
            if p.is_file():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip()
                    if k == "TIP_DEFAULT_PERCENT":
                        cfg.default_tip_percent = Decimal(v.replace("%", ""))
                    elif k == "TIP_QUICK_PICKS":
                        cfg.quick_picks = _parse_env_quick_picks(v)
                break
        except Exception:
            pass

    if not cfg.quick_picks:
        cfg.quick_picks = [Decimal("15"), Decimal("18"), Decimal("20")]
    return cfg


T = TypeVar("T")


def prompt_loop(prompt: str, parser: Callable[[str], T]) -> T:
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
    picks = [_format_decimal(p) for p in config.quick_picks]
    menu = "  ".join(f"[{i+1}] {p}%" for i, p in enumerate(picks))
    default_str = _format_decimal(config.default_tip_percent)
    while True:
        s = input(f"Tip: {menu}  [Enter={default_str}% or custom]: ").strip().lower()
        quick_map = {str(i + 1): picks[i] for i in range(len(picks))}
        quick_map[""] = default_str
        s = quick_map.get(s, s)
        try:
            return parse_percentage(s, min_value=Decimal("0"), max_value=Decimal("100"))
        except ValueError as e:
            print(f"Error: {e}")


def run_interactive(
    config: AppConfig,
    *,
    round_mode: str,
    granularity: Decimal,
    tip_on_pretax: bool,
    currency: str,
    locale: Optional[str],
    strict_money: bool,
) -> None:
    print("--- Tip Calculator ---")
    while True:
        subtotal: Decimal = prompt_loop(
            "Bill subtotal (before tax): $",
            lambda s: parse_money(s, min_value=Decimal("0.01"), strict=strict_money),
        )
        tax_amount: Decimal = prompt_loop(
            "Sales tax amount (enter 0 if none): $",
            lambda s: parse_money(s, min_value=Decimal("0.00"), strict=strict_money),
        )
        total_bill = subtotal + tax_amount

        tip_percent = prompt_tip_percent(config)
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.")
        people: int = prompt_loop(
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
                currency=currency,
                locale=locale,
            )
        )

        if not yes_no("Calculate another tip?", default_yes=False):
            break


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tip Calculator with exact split and Decimal precision. Default: tip on pre-tax subtotal (use --post-tax to tip on total)."
    )
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
    parser.add_argument("--locale", help="Locale for formatting (e.g., en_US). Requires Babel if provided.")
    parser.add_argument("--format", choices=["auto", "simple", "locale"], default="auto", help="Output formatting style: simple (fallback) or locale-aware (requires --locale)")
    parser.add_argument("--strict-money", action="store_true", help="Validate canonical money format ($1,234.56); reject loose inputs")
    parser.add_argument("--interactive", action="store_true", help="Force interactive mode regardless of provided flags.")
    return parser


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = load_config(args.config)
    round_mode = args.round_per_person
    granularity = Decimal(args.granularity)
    tip_on_pretax = not args.post_tax
    currency = args.currency
    locale = args.locale
    fmt_mode = args.format
    # Determine whether to use locale-aware formatting for output
    output_locale = locale if (fmt_mode == "locale" or (fmt_mode == "auto" and locale)) else None
    strict_money = args.strict_money

    weights: Optional[List[Decimal]] = None
    if args.weights:
        try:
            parts = [p.strip() for p in args.weights.split(",") if p.strip()]
            weights = [Decimal(p) for p in parts]
            if not weights:
                raise ValueError
        except Exception:
            parser.error("--weights must be a comma-separated list of positive numbers")

    if args.interactive or args.total is None:
        try:
            run_interactive(
                config,
                round_mode=round_mode,
                granularity=granularity,
                tip_on_pretax=tip_on_pretax,
                currency=currency,
                locale=output_locale,
                strict_money=strict_money,
            )
            return 0
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            return 0

    try:
        total_bill = parse_money(args.total, min_value=Decimal("0.01"), strict=strict_money)
        tax_amount = parse_money(args.tax, min_value=Decimal("0.00"), strict=strict_money)
        tip_input = args.tip if args.tip is not None else str(config.default_tip_percent)
        tip_percent = parse_percentage(tip_input, min_value=Decimal("0"), max_value=Decimal("100"))
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.", file=sys.stderr)
        if tax_amount >= total_bill:
            print("Warning: Tax amount is greater than or equal to the total bill; this will be rejected.", file=sys.stderr)
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
        return 2

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
            locale=output_locale,
        )
    print(out)
    if args.copy:
        if not copy_to_clipboard(out):
            print("(Could not copy to clipboard on this system)", file=sys.stderr)
    return 0
