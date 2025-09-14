from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import List, Optional

from .formats import to_cents, CENT, HUNDRED


@dataclass
class TipResult:
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
) -> TipResult:
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

    if granularity != CENT or round_mode != "nearest":
        if people == 1:
            per_person = [final_total]
        else:
            rounded: List[Decimal] = []
            for i in range(people - 1):
                rounded.append(_round_to_step(per_person[i], granularity, round_mode))
            rounded_sum = to_cents(sum(rounded, Decimal("0")))
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

    if to_cents(sum(per_person, Decimal("0"))) != final_total:
        raise AssertionError("Split calculation error: per-person amounts do not sum to total")

    return TipResult(
        bill_before_tax=bill_before_tax,
        tip=tip,
        final_total=final_total,
        per_person=per_person,
    )

