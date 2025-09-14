from decimal import Decimal, ROUND_HALF_UP
import random

import tip as tipmod


def cents(value: Decimal) -> int:
    return int((value / Decimal("0.01")).to_integral_value(rounding=ROUND_HALF_UP))


def test_parse_money_permissive_variants():
    assert tipmod.parse_money("$1,234.56") == Decimal("1234.56")
    assert tipmod.parse_money(" 1234.56 $") == Decimal("1234.56")
    assert tipmod.parse_money(" .5 ") == Decimal("0.50")
    assert tipmod.parse_money("$ 1,234.5") == Decimal("1234.50")


def test_parse_money_strict_validation():
    # Valid strict formats
    assert tipmod.parse_money("$1,234.56", strict=True) == Decimal("1234.56")
    assert tipmod.parse_money("1234.5", strict=True) == Decimal("1234.50")
    # Invalid: trailing symbol, bad comma grouping
    for bad in ["1234.56$", "$12,34.56", "1 234.56", "$.50."]:
        try:
            tipmod.parse_money(bad, strict=True)
        except ValueError:
            pass
        else:
            raise AssertionError(f"strict should reject: {bad}")


def test_parse_percentage_clamps_and_spaces():
    assert tipmod.parse_percentage("18.567%") == Decimal("18.57")
    assert tipmod.parse_percentage("15 %") == Decimal("15.00")
    assert tipmod.parse_percentage("100") == Decimal("100.00")
    try:
        tipmod.parse_percentage("120%")
    except ValueError:
        pass
    else:
        raise AssertionError("percentage > 100 should raise")


def test_compute_tip_split_equal_basic():
    res = tipmod.compute_tip_split(
        total_bill=Decimal("110.00"),
        tax_amount=Decimal("10.00"),
        tip_percent=Decimal("20.00"),
        people=3,
    )
    assert res.bill_before_tax == Decimal("100.00")
    assert res.tip == Decimal("20.00")
    assert res.final_total == Decimal("130.00")
    assert len(res.per_person) == 3
    assert sum(res.per_person, Decimal("0")) == Decimal("130.00")
    # Differences at most one cent for equal split
    diff = max(res.per_person) - min(res.per_person)
    assert diff <= Decimal("0.01")


def test_error_when_tax_ge_total():
    for tax in ["10.00", "10.01"]:
        try:
            tipmod.compute_tip_split(
                total_bill=Decimal("10.00"),
                tax_amount=Decimal(tax),
                tip_percent=Decimal("20.00"),
                people=2,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("tax >= total should raise")


def test_property_equal_split_randomized():
    rnd = random.Random(1234)
    for _ in range(200):
        # Random totals between 0.01 and 1000 with two decimals
        dollars = rnd.uniform(0.01, 1000.0)
        total = Decimal(f"{dollars:.2f}")
        # Tax less than total
        tax = Decimal(f"{rnd.uniform(0, float(total) - 0.01):.2f}")
        tip_pct = Decimal(f"{rnd.uniform(0, 100):.2f}")
        people = rnd.randint(1, 50)
        res = tipmod.compute_tip_split(
            total_bill=total,
            tax_amount=tax,
            tip_percent=tip_pct,
            people=people,
        )
        # Sum invariant
        assert sum(res.per_person, Decimal("0")) == res.final_total
        # For equal splits the per-person amounts differ by at most one cent
        if people > 1:
            assert max(res.per_person) - min(res.per_person) <= Decimal("0.01")


def test_property_weighted_split_randomized():
    rnd = random.Random(4321)
    for _ in range(100):
        dollars = rnd.uniform(1.00, 500.0)
        total = Decimal(f"{dollars:.2f}")
        tax = Decimal(f"{rnd.uniform(0, float(total) * 0.2):.2f}")
        tip_pct = Decimal(f"{rnd.uniform(0, 40):.2f}")
        people = rnd.randint(2, 8)
        weights = [Decimal(rnd.randint(1, 5)) for _ in range(people)]
        res = tipmod.compute_tip_split(
            total_bill=total,
            tax_amount=tax,
            tip_percent=tip_pct,
            people=people,
            weights=weights,
        )
        assert sum(res.per_person, Decimal("0")) == res.final_total
        # In cents, each share deviates from its exact proportion by at most 1 cent
        total_cents = cents(res.final_total)
        wsum = sum(weights, Decimal("0"))
        for i, amt in enumerate(res.per_person):
            exact = (Decimal(total_cents) * weights[i]) / wsum
            diff_cents = abs(cents(amt) - int(exact))
            assert diff_cents in (0, 1)


def test_rounding_preferences_quarters_up_down_nearest():
    total = Decimal("99.99")
    tax = Decimal("9.99")
    tip_pct = Decimal("18.00")
    people = 4
    for mode in ("nearest", "up", "down"):
        res = tipmod.compute_tip_split(
            total_bill=total,
            tax_amount=tax,
            tip_percent=tip_pct,
            people=people,
            round_mode=mode,
            granularity=Decimal("0.25"),
        )
        # Sum invariant
        assert sum(res.per_person, Decimal("0")) == res.final_total
        # All but the last are multiples of the step
        step = Decimal("0.25")
        for amt in res.per_person[:-1]:
            mult = (amt / step).quantize(Decimal(0), rounding=ROUND_HALF_UP)
            assert (mult * step).quantize(Decimal("0.01")) == amt

