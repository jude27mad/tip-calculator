from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple, TypeVar

from .formats import (
    print_results,
    results_to_dict,
    dict_to_csv_line,
    copy_to_clipboard,
    to_cents,
)
from .parsing import parse_money, parse_percentage, parse_int, parse_tax_entry
from .tip_core import compute_tip_split
from .qr import generate_qr_codes, QRGenerationError
from .tax_lookup import lookup_tax_rate, TaxLookupError, TaxLookupResult
from .profiles import get_profile, save_profile, ProfileError


@dataclass
class AppConfig:
    default_tip_percent: Decimal
    quick_picks: List[Decimal]
    last_tax_type: Optional[str] = None
    last_tax_value: Optional[Decimal] = None


def _default_config() -> AppConfig:
    return AppConfig(default_tip_percent=Decimal("18"), quick_picks=[Decimal("15"), Decimal("18"), Decimal("20")])


def _format_decimal(value: Decimal) -> str:
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"

def _summarize_source(source: object, *, limit: int = 60) -> str:
    text = str(source)
    return text if len(text) <= limit else text[: limit - 3] + "..."



STATE_FILENAME = "tipstate.json"

TAX_PRESETS: Dict[str, Tuple[str, Decimal]] = {
    "us": ("percent", Decimal("8.875")),
    "caon": ("percent", Decimal("13")),
    "cabc": ("percent", Decimal("12")),
    "euvat": ("percent", Decimal("20")),
}


def _tax_state_paths() -> List[Path]:
    return [Path.cwd() / STATE_FILENAME, Path(__file__).with_name(STATE_FILENAME)]


def _parse_tax_state_token(raw: str) -> Optional[Tuple[str, Decimal]]:
    parts = raw.strip().split(":", 1)
    if len(parts) != 2:
        return None
    label, value = parts[0].strip().lower(), parts[1].strip()
    if label not in {"percent", "amount"}:
        return None
    try:
        dec = Decimal(value)
    except Exception:
        return None
    if dec < Decimal("0"):
        return None
    return label, Decimal(value)


def _load_tax_state(cfg: AppConfig) -> None:
    env_val = os.environ.get("TIP_LAST_TAX")
    state: Optional[Tuple[str, Decimal]] = None
    if env_val:
        state = _parse_tax_state_token(env_val)
    if not state:
        for candidate in _tax_state_paths():
            try:
                if candidate.is_file():
                    data = json.loads(candidate.read_text())
                    label = data.get("tax_type")
                    raw_val = data.get("tax_value")
                    if label in {"percent", "amount"} and raw_val is not None:
                        state = (label, Decimal(str(raw_val)))
                        break
            except Exception:
                continue
    if state:
        cfg.last_tax_type, cfg.last_tax_value = state


def _save_tax_state(tax_type: Optional[str], tax_value: Optional[Decimal]) -> None:
    if tax_type not in {"percent", "amount"} or tax_value is None:
        return
    data = {"tax_type": tax_type, "tax_value": str(tax_value)}
    try:
        target = Path.cwd() / STATE_FILENAME
        target.write_text(json.dumps(data))
    except Exception:
        pass


def _format_tax_default(tax_type: Optional[str], tax_value: Optional[Decimal]) -> Optional[str]:
    if tax_type not in {"percent", "amount"} or tax_value is None:
        return None
    if tax_type == "percent":
        return f"{_format_decimal(tax_value)}%"
    cents = to_cents(tax_value)
    return f"${_format_decimal(cents)}"




def _maybe_generate_qr(per_person: Iterable[Decimal], qr_options: Optional[dict]) -> None:
    if not qr_options:
        return
    try:
        paths = generate_qr_codes(
            per_person=per_person,
            provider=qr_options["provider"],
            note=qr_options["note"],
            directory=qr_options["directory"],
            scale=qr_options["scale"],
        )
    except QRGenerationError as exc:
        print(f"QR generation failed: {exc}", file=sys.stderr)
        return
    print(f"Saved {len(paths)} QR code(s) to {qr_options['directory']}")
def _normalize_preset_key(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _prompt_tax_preset(
    default_type: Optional[str],
    default_value: Optional[Decimal],
    *,
    enable_lookup: bool,
    tax_country: str,
) -> Tuple[Optional[str], Optional[Decimal]]:
    parts = ["[N]one", "[US] 8.875%", "[CA-ON] 13%", "[CA-BC] 12%", "[EU-VAT] 20%"]
    if enable_lookup:
        parts.append("[Lookup] ZIP/postal")
    if default_type in {"percent", "amount"} and default_value is not None:
        previous_display = _format_tax_default(default_type, default_value)
        if previous_display:
            parts.append(f"[Last] {previous_display}")
    prompt = "Quick presets? " + ", ".join(parts) + " (Enter to skip): "
    while True:
        choice = input(prompt).strip()
        if not choice:
            return default_type, default_value
        key = _normalize_preset_key(choice)
        if key in {"n", "none"}:
            return None, None
        if key == "last":
            if default_type in {"percent", "amount"} and default_value is not None:
                return default_type, default_value
            print("No previous tax rate stored.")
            continue
        if key in {"lookup", "zip", "postal"} and enable_lookup:
            code = input("ZIP/postal code to lookup: ").strip()
            if not code:
                print("Enter a ZIP/postal code.")
                continue
            try:
                result = lookup_tax_rate(code, country=tax_country)
            except TaxLookupError as exc:
                print(f"Lookup failed: {exc}")
                continue
            print(
                f"Using {_format_decimal(result.value)}% sales tax for {code.upper()} (cached via {_summarize_source(result.source)})."
            )
            return result.tax_type, result.value
        if key in TAX_PRESETS:
            return TAX_PRESETS[key]
        print("Unknown preset. Please try again.")


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
    _load_tax_state(cfg)
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


def prompt_tip_base(default_pre_tax: bool) -> bool:
    prompt = "Tip base: [1] pre-tax (default), [2] after-tax: "
    while True:
        ans = input(prompt).strip().lower()
        if not ans:
            return default_pre_tax
        if ans in {"1", "pre", "pretax", "pre-tax"}:
            return True
        if ans in {"2", "post", "after", "aftertax", "after-tax"}:
            return False
        if ans in {"default", "d"}:
            return default_pre_tax
        print("Choose 1 for pre-tax or 2 for after-tax.")


def run_interactive(
    config: AppConfig,
    *,
    round_mode: str,
    granularity: Decimal,
    tip_on_pretax: bool,
    currency: str,
    locale: Optional[str],
    tax_country: str,
    strict_money: bool,
    qr_options: Optional[dict] = None,
    default_people: int = 1,
) -> None:
    print("--- Tip Calculator ---")
    tip_base_default = tip_on_pretax
    while True:
        subtotal: Decimal = prompt_loop(
            "Bill subtotal (before tax): $",
            lambda s: parse_money(s, min_value=Decimal("0.01"), strict=strict_money),
        )

        default_tax_type, default_tax_value = _prompt_tax_preset(
            config.last_tax_type,
            config.last_tax_value,
            enable_lookup=True,
            tax_country=tax_country,
        )
        default_display = _format_tax_default(default_tax_type, default_tax_value)
        base_prompt = "Tax: enter % (e.g., 13), $ amount (e.g., 13.00), type 'lookup 94105', or 0 for none"
        tax_prompt = (
            f"{base_prompt} [Enter={default_display}]: "
            if default_display
            else f"{base_prompt}: "
        )

        def _parse_tax(user_input: str) -> Tuple[str, Decimal]:
            text = user_input.strip()
            if not text:
                if default_tax_type in {"percent", "amount"} and default_tax_value is not None:
                    return default_tax_type, default_tax_value
                raise ValueError("Enter a tax amount or percentage")
            lowered = text.lower()
            if lowered.startswith("lookup"):
                parts = text.split(None, 1)
                code = parts[1] if len(parts) > 1 else input("ZIP/postal code to lookup: ").strip()
                if not code:
                    raise ValueError("Enter a ZIP/postal code to lookup")
                try:
                    result = lookup_tax_rate(code, country=tax_country)
                except TaxLookupError as exc:
                    raise ValueError(f"Lookup failed: {exc}")
                print(
                    f"Using {_format_decimal(result.value)}% sales tax for {code.upper()} (cached via {_summarize_source(result.source)})."
                )
                return result.tax_type, result.value
            tax_type, tax_val = parse_tax_entry(text, strict=strict_money)
            return tax_type, tax_val

        tax_type, tax_value = prompt_loop(tax_prompt, _parse_tax)
        if tax_type == "percent":
            tax_percent = tax_value
            tax_amount = to_cents(subtotal * (tax_percent / Decimal("100")))
        else:
            tax_percent = None
            tax_amount = to_cents(tax_value)
        total_bill = subtotal + tax_amount

        config.last_tax_type = tax_type
        config.last_tax_value = tax_value
        _save_tax_state(tax_type, tax_value)

        tip_percent = prompt_tip_percent(config)
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.")

        tip_on_pretax_choice = prompt_tip_base(tip_base_default)
        tip_base_default = tip_on_pretax_choice

        people_prompt = f"Split between how many people? [{default_people}]: "
        people: int = prompt_loop(
            people_prompt,
            lambda s: default_people if not s.strip() else parse_int(s, min_value=1),
        )

        results = compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
            tip_on_pretax=tip_on_pretax_choice,
            round_mode=round_mode,
            granularity=granularity,
        )
        print(
            print_results(
                bill_before_tax=results.bill_before_tax,
                tax_amount=tax_amount,
                tax_percent=tax_percent,
                original_total=total_bill,
                tip_percent=tip_percent,
                tip_base_label=("pre-tax" if tip_on_pretax_choice else "post-tax"),
                tip=results.tip,
                final_total=results.final_total,
                per_person=results.per_person,
                currency=currency,
                locale=locale,
            )
        )
        _maybe_generate_qr(results.per_person, qr_options)

        if not yes_no("Calculate another tip?", default_yes=False):
            break


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Tip Calculator with exact split and Decimal precision. Default: tip on pre-tax subtotal (use --post-tax to tip on total)."
    )
    parser.add_argument("--total", help="Total bill amount (including tax), e.g. 123.45 or $123.45")
    parser.add_argument("--tax", default="0", help="Tax amount, e.g. 10.23. Default: 0")
    parser.add_argument("--qr", action="store_true", help="Generate per-person payment QR codes")
    parser.add_argument("--qr-provider", choices=["venmo", "generic"], default="venmo", help="QR link provider to use")
    parser.add_argument("--qr-dir", default="qr_codes", help="Directory to write QR code PNG files")
    parser.add_argument("--qr-note", default="tipcalc split", help="Note text embedded in the QR payload")
    parser.add_argument("--qr-scale", type=int, default=5, help="Pixel scale for generated QR images")
    parser.add_argument(
        "--lookup-tax",
        metavar="ZIP",
        help="Lookup sales-tax percent by ZIP/postal code (requires API key)",
    )
    parser.add_argument(
        "--tax-country",
        default="US",
        help="ISO country code for tax lookup (default: US)",
    )
    parser.add_argument("--tip", default=None, help="Tip percentage, e.g. 20 or 20% (0-100). Default comes from config")
    parser.add_argument("--people", type=int, default=None, help="Number of people to split between (>=1). Default: profile or 1")
    parser.add_argument("--post-tax", action="store_true", help="Compute tip on total (post-tax) instead of pre-tax subtotal")
    parser.add_argument("--round-per-person", choices=["nearest", "up", "down"], default=None, help="Rounding mode for per-person amounts")
    parser.add_argument("--granularity", choices=["0.01", "0.05", "0.25"], default=None, help="Rounding step for per-person amounts")
    parser.add_argument("--config", help="Path to JSON or .env with TIP_DEFAULT_PERCENT and TIP_QUICK_PICKS")
    parser.add_argument("--profile", help="Load saved scenario defaults by name")
    parser.add_argument("--save-profile", help="Save current scenario defaults under a name")
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
    tax_country = (args.tax_country or "US").upper()

    try:
        profile_data = get_profile(args.profile) if args.profile else {}
    except ProfileError as exc:
        parser.error(str(exc))
    if args.profile and not profile_data:
        parser.error(f"Profile '{args.profile}' not found")

    def _profile_value(key: str):
        if isinstance(profile_data, dict):
            return profile_data.get(key)
        return None

    people_pref = args.people if args.people is not None else _profile_value("people")
    if people_pref is None:
        people_pref = 1
    people_pref = int(people_pref)

    round_mode = args.round_per_person or _profile_value("round_mode") or "nearest"
    granularity_raw = args.granularity or _profile_value("granularity") or "0.01"
    if isinstance(granularity_raw, (int, float)):
        granularity_raw = str(granularity_raw)
    granularity = Decimal(str(granularity_raw))

    currency = args.currency
    locale_value = args.locale or _profile_value("locale")
    fmt_mode = args.format
    output_locale = locale_value if (fmt_mode == "locale" or (fmt_mode == "auto" and locale_value)) else None
    strict_money = args.strict_money

    qr_options: Optional[dict] = None
    if args.qr:
        qr_options = {
            "provider": args.qr_provider,
            "note": args.qr_note,
            "directory": Path(args.qr_dir),
            "scale": max(1, args.qr_scale),
        }

    if args.save_profile:
        payload = {
            "people": people_pref,
            "round_mode": round_mode,
            "granularity": format(granularity, 'f'),
        }
        if locale_value:
            payload["locale"] = locale_value
        try:
            save_profile(args.save_profile, payload)
        except ProfileError as exc:
            parser.error(str(exc))

    lookup_result: Optional[TaxLookupResult] = None
    if args.lookup_tax:
        try:
            lookup_result = lookup_tax_rate(args.lookup_tax, country=tax_country)
        except TaxLookupError as exc:
            parser.error(str(exc))
        config.last_tax_type = "percent"
        config.last_tax_value = lookup_result.value
        _save_tax_state("percent", lookup_result.value)
        print(
            f"Using {_format_decimal(lookup_result.value)}% sales tax for {args.lookup_tax.upper()} (cached via {_summarize_source(lookup_result.source)})."
        )

    if lookup_result and not (args.interactive or args.total):
        parser.error("--lookup-tax requires --total unless you use --interactive")
    weights: Optional[List[Decimal]] = None
    if args.weights:
        try:
            parts = [p.strip() for p in args.weights.split(",") if p.strip()]
            weights = [Decimal(p) for p in parts]
            if not weights:
                raise ValueError
        except Exception:
            parser.error("--weights must be a comma-separated list of positive numbers")

    tip_on_pretax = not args.post_tax

    if args.interactive or args.total is None:
        try:
            run_interactive(
                config,
                round_mode=round_mode,
                granularity=granularity,
                tip_on_pretax=tip_on_pretax,
                currency=currency,
                locale=output_locale,
                tax_country=tax_country,
                strict_money=strict_money,
                qr_options=qr_options,
                default_people=people_pref,
            )
            return 0
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            return 0

    try:
        total_bill = parse_money(args.total, min_value=Decimal("0.01"), strict=strict_money)
        if lookup_result:
            rate_fraction = lookup_result.value / Decimal("100")
            bill_before_tax = to_cents(total_bill / (Decimal("1") + rate_fraction))
            tax_amount = to_cents(total_bill - bill_before_tax)
            tax_percent_display: Optional[Decimal] = lookup_result.value.quantize(Decimal("0.01"))
        else:
            tax_amount = parse_money(args.tax, min_value=Decimal("0.00"), strict=strict_money)
            tax_percent_display = None

        tip_input = args.tip if args.tip is not None else str(config.default_tip_percent)
        tip_percent = parse_percentage(tip_input, min_value=Decimal("0"), max_value=Decimal("100"))
        if tip_percent > Decimal("50"):
            print("Warning: Tip percentage exceeds 50%.", file=sys.stderr)
        if tax_amount >= total_bill:
            print("Warning: Tax amount is greater than or equal to the total bill; this will be rejected.", file=sys.stderr)
        people = len(weights) if weights is not None else parse_int(str(people_pref), min_value=1)
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

    if tax_percent_display is None and results.bill_before_tax > Decimal("0"):
        tax_percent_display = (tax_amount / results.bill_before_tax * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    d = results_to_dict(
        bill_before_tax=results.bill_before_tax,
        tax_amount=tax_amount,
        tax_percent=tax_percent_display,
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
        header = "currency,tip_base,bill_before_tax,tax_amount,tax_percent,original_total,tip_percent,tip,final_total,people,weights,per_person"
        out = header + "\n" + dict_to_csv_line(d)
    else:
        out = print_results(
            bill_before_tax=results.bill_before_tax,
            tax_amount=tax_amount,
            tax_percent=tax_percent_display,
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
    if qr_options:
        _maybe_generate_qr(results.per_person, qr_options)
    if args.copy:
        if not copy_to_clipboard(out):
            print("(Could not copy to clipboard on this system)", file=sys.stderr)
    return 0


    try:
        total_bill = parse_money(args.total, min_value=Decimal("0.01"), strict=strict_money)
        if lookup_result:
            rate_fraction = lookup_result.value / Decimal("100")
            bill_before_tax = to_cents(total_bill / (Decimal("1") + rate_fraction))
            tax_amount = to_cents(total_bill - bill_before_tax)
            tax_percent_display: Optional[Decimal] = lookup_result.value.quantize(Decimal("0.01"))
        else:
            tax_amount = parse_money(args.tax, min_value=Decimal("0.00"), strict=strict_money)
            tax_percent_display = None

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

    if tax_percent_display is None and results.bill_before_tax > Decimal("0"):
        tax_percent_display = (tax_amount / results.bill_before_tax * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    d = results_to_dict(
        bill_before_tax=results.bill_before_tax,
        tax_amount=tax_amount,
        tax_percent=tax_percent_display,
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
        header = "currency,tip_base,bill_before_tax,tax_amount,tax_percent,original_total,tip_percent,tip,final_total,people,weights,per_person"
        out = header + "\n" + dict_to_csv_line(d)
    else:
        out = print_results(
            bill_before_tax=results.bill_before_tax,
            tax_amount=tax_amount,
            tax_percent=tax_percent_display,
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
    if qr_options:
        _maybe_generate_qr(results.per_person, qr_options)
    if args.copy:
        if not copy_to_clipboard(out):
            print("(Could not copy to clipboard on this system)", file=sys.stderr)
    return 0
