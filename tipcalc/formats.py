from __future__ import annotations

import platform
import subprocess
from decimal import Decimal, ROUND_HALF_UP
from typing import List, Optional

try:  # Optional dependency for locale-aware currency formatting
    from babel.numbers import format_currency as _babel_format_currency  # type: ignore
except Exception:  # pragma: no cover - optional at runtime
    _babel_format_currency = None


# --- Money helpers & constants ---
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
PERCENT_STEP = Decimal("0.01")  # display percent with up to 2 decimals


def to_cents(value: Decimal) -> Decimal:
    """Round a Decimal to two fractional digits using ROUND_HALF_UP."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# --- Formatting ---
def currency_symbol(code: str) -> str:
    code = (code or "USD").upper()
    return {"USD": "$", "EUR": "\u20ac", "GBP": "\u00a3", "CAD": "C$"}.get(code, "$")


def fmt_money(
    value: Decimal,
    *,
    symbol: str = "$",
    currency: str = "USD",
    locale: Optional[str] = None,
) -> str:
    """Format money for display.

    - If Babel is installed and a ``locale`` is provided, use locale-aware
      formatting (e.g., thousands separators, proper symbol placement).
    - Otherwise, fall back to a simple symbol + 2-decimal format with commas.
    """
    amount = to_cents(value)
    if _babel_format_currency and locale:
        try:
            return _babel_format_currency(amount, currency, locale=locale)
        except Exception:
            pass
    # Fallback: place symbol first and use commas
    return f"{symbol}{amount:,.2f}"


def fmt_percent(value: Decimal) -> str:
    """Format a percentage with up to two decimals, trimming zeros."""
    q = value.quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
    return f"{q:.2f}".rstrip("0").rstrip(".")


def print_results(
    *,
    bill_before_tax: Decimal,
    tax_amount: Decimal,
    tax_percent: Optional[Decimal] = None,
    original_total: Decimal,
    tip_percent: Decimal,
    tip_base_label: str,
    tip: Decimal,
    final_total: Decimal,
    per_person: List[Decimal],
    currency: str = "USD",
    locale: Optional[str] = None,
) -> str:
    lines: List[str] = []
    lines.append("\n--- Results ---")
    sym = currency_symbol(currency)
    lines.append(
        f"Subtotal (pre-tax): {fmt_money(bill_before_tax, symbol=sym, currency=currency, locale=locale)}"
    )
    if tax_percent is not None:
        lines.append(
            f"Tax: {fmt_percent(tax_percent)}% of {fmt_money(bill_before_tax, symbol=sym, currency=currency, locale=locale)} -> {fmt_money(tax_amount, symbol=sym, currency=currency, locale=locale)}"
        )
    else:
        lines.append(
            f"Tax: {fmt_money(tax_amount, symbol=sym, currency=currency, locale=locale)} (entered amount)"
        )
    lines.append(
        f"After-tax total (before tip): {fmt_money(original_total, symbol=sym, currency=currency, locale=locale)}"
    )
    lines.append(
        f"Tip ({tip_base_label} at {fmt_percent(tip_percent)}%): {fmt_money(tip, symbol=sym, currency=currency, locale=locale)}"
    )
    lines.append(
        f"Total with tip: {fmt_money(final_total, symbol=sym, currency=currency, locale=locale)}"
    )
    lines.append(
        f"Breakdown: {fmt_money(bill_before_tax, symbol=sym, currency=currency, locale=locale)} + {fmt_money(tax_amount, symbol=sym, currency=currency, locale=locale)} + {fmt_money(tip, symbol=sym, currency=currency, locale=locale)} = {fmt_money(final_total, symbol=sym, currency=currency, locale=locale)}"
    )
    if len(per_person) == 1:
        lines.append(
            f"Each person pays: {fmt_money(per_person[0], symbol=sym, currency=currency, locale=locale)}"
        )
    else:
        shares = ", ".join(
            fmt_money(p, symbol=sym, currency=currency, locale=locale) for p in per_person
        )
        lines.append(f"Each person pays: {shares}")
    return "\n".join(lines) + "\n"


# --- Data export helpers ---
def decimals_to_strings(items: List[Decimal]) -> List[str]:
    return [f"{to_cents(x):.2f}" for x in items]


def results_to_dict(
    *,
    bill_before_tax: Decimal,
    tax_amount: Decimal,
    tax_percent: Optional[Decimal] = None,
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
        "tax_percent": f"{tax_percent:.2f}" if tax_percent is not None else "",
        "original_total": f"{to_cents(original_total):.2f}",
        "tip_percent": f"{tip_percent:.2f}",
        "tip": f"{to_cents(tip):.2f}",
        "final_total": f"{to_cents(final_total):.2f}",
        "people": people,
        "weights": [str(w) for w in (weights or [])],
        "per_person": decimals_to_strings(per_person),
    }


def dict_to_csv_line(d: dict) -> str:
    cols = [
        "currency",
        "tip_base",
        "bill_before_tax",
        "tax_amount",
        "tax_percent",
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
            if p.stdin:
                p.stdin.write(text.encode("utf-16le"))
                p.stdin.close()
            return p.wait() == 0
        elif system == "Darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            if p.stdin:
                p.communicate(input=text.encode())
            return p.returncode == 0
        else:
            for cmd in (["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    if p.stdin:
                        p.communicate(input=text.encode())
                    if p.returncode == 0:
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False
