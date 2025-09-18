from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Optional, Tuple

from .formats import to_cents, PERCENT_STEP


def parse_money(
    text: str,
    *,
    min_value: Decimal = Decimal("0.00"),
    strict: bool = False,
) -> Decimal:
    s = text.strip()
    if strict:
        money_strict_re = re.compile(r"^\s*\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s*$")
        if not money_strict_re.match(s):
            raise ValueError("Enter a valid dollar amount like $1,234.56")
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
    s = text.strip()
    raw = re.sub(r"\s+", "", s).replace("%", "").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Enter a valid percentage (e.g., 18 or 18%)") from exc
    if value < min_value or value > max_value:
        raise ValueError(f"Percentage must be between {min_value} and {max_value}")
    return value.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)


def parse_int(text: str, *, min_value: int = 1) -> int:
    try:
        value = int(text.strip())
    except ValueError as exc:
        raise ValueError("Enter a whole number") from exc
    if value < min_value:
        raise ValueError(f"Value must be >= {min_value}")
    return value



def parse_tax_entry(
    text: str,
    *,
    strict: bool = False,
    max_percent: Decimal = Decimal("100"),
) -> Tuple[str, Decimal]:
    s = text.strip()
    if not s:
        raise ValueError("Enter a tax amount or percentage")
    if s == "0":
        return "amount", Decimal("0")

    if s.startswith("$"):
        return "amount", parse_money(s, min_value=Decimal("0.00"), strict=strict)

    lowered = s.lower()
    if lowered.endswith("%"):
        percent_text = s.rstrip().rstrip("%")
        percent = parse_percentage(percent_text, min_value=Decimal("0"), max_value=max_percent)
        return "percent", percent
    if lowered.endswith(" percent"):
        percent_text = s[: -len(" percent")]
        percent = parse_percentage(percent_text, min_value=Decimal("0"), max_value=max_percent)
        return "percent", percent
    if lowered.endswith(" pct"):
        percent_text = s[: -len(" pct")]
        percent = parse_percentage(percent_text, min_value=Decimal("0"), max_value=max_percent)
        return "percent", percent

    normalized = s.replace(",", "")
    if normalized.startswith("0.") or normalized.startswith("."):
        value = normalized if normalized.startswith("0") else f"0{normalized}"
        return "amount", parse_money(value, min_value=Decimal("0.00"), strict=strict)

    try:
        percent_candidate = parse_percentage(s, min_value=Decimal("0"), max_value=max_percent)
    except ValueError:
        amount = parse_money(s, min_value=Decimal("0.00"), strict=strict)
        return "amount", amount
    else:
        if percent_candidate <= max_percent:
            return "percent", percent_candidate
        amount = parse_money(s, min_value=Decimal("0.00"), strict=strict)
        return "amount", amount
