import random
import types
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from tipcalc import profiles

try:
    from hypothesis import given
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - optional dependency
    given = cast(Any, None)
    st = cast(Any, None)


import importlib.metadata as importlib_metadata

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


def test_lookup_tax_rate_caches(monkeypatch, tmp_path):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setenv("TIP_TAX_CACHE_PATH", str(cache_file))
    calls = []

    def fake_fetch(zip_code: str, country: str):
        calls.append((zip_code, country))
        return tipmod.TaxLookupResult(
            zip_code=zip_code,
            country=country,
            tax_type="percent",
            value=Decimal("8.875"),
            source="unit-test",
            fetched_at=datetime.now(timezone.utc),
        )

    first = tipmod.lookup_tax_rate("94105", fetcher=fake_fetch)
    second = tipmod.lookup_tax_rate("94105", fetcher=fake_fetch)
    assert first.value == second.value == Decimal("8.875")
    assert len(calls) == 1
    assert cache_file.is_file()


def test_lookup_tax_rate_expired_cache(monkeypatch, tmp_path):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setenv("TIP_TAX_CACHE_PATH", str(cache_file))
    calls = []

    def fake_fetch(zip_code: str, country: str):
        calls.append(datetime.now(timezone.utc))
        return tipmod.TaxLookupResult(
            zip_code=zip_code,
            country=country,
            tax_type="percent",
            value=Decimal("7.250"),
            source="unit-test",
            fetched_at=datetime.now(timezone.utc),
        )

    tipmod.lookup_tax_rate("30301", fetcher=fake_fetch)
    tipmod.lookup_tax_rate("30301", fetcher=fake_fetch, ttl_hours=0)
    assert len(calls) == 2


def test_lookup_tax_rate_errors_surface():
    def failing_fetch(zip_code: str, country: str):
        raise tipmod.TaxLookupError("boom")

    with pytest.raises(tipmod.TaxLookupError):
        tipmod.lookup_tax_rate("00000", fetcher=failing_fetch)


def test_run_cli_uses_lookup_tax(monkeypatch, capsys):
    from tipcalc import cli

    captured = {}
    original_compute = cli.compute_tip_split

    def record_compute(**kwargs):
        captured.update(kwargs)
        return original_compute(**kwargs)

    monkeypatch.setattr(cli, "compute_tip_split", record_compute)

    def fake_lookup(zip_code: str, country: str):
        return tipmod.TaxLookupResult(
            zip_code=zip_code,
            country=country,
            tax_type="percent",
            value=Decimal("8.000"),
            source="unit-test",
            fetched_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(cli, "lookup_tax_rate", fake_lookup)
    monkeypatch.setattr(cli, "_save_tax_state", lambda *args, **kwargs: None)

    config = cli.AppConfig(
        default_tip_percent=Decimal("18"),
        quick_picks=[Decimal("15"), Decimal("18"), Decimal("20")],
    )
    monkeypatch.setattr(cli, "load_config", lambda path=None: config)

    exit_code = cli.run_cli(
        [
            "--total",
            "108.00",
            "--lookup-tax",
            "94105",
            "--tip",
            "18",
            "--people",
            "2",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert captured["tax_amount"] == Decimal("8.00")
    assert "Using 8" in out


def test_generate_qr_codes_venmo(monkeypatch, tmp_path):
    from tipcalc import qr

    saved_payloads = []

    class FakeQR:
        def __init__(self, payload: str) -> None:
            self.payload = payload

        def save(self, path: str, scale: int) -> None:
            Path(path).write_text("fake")

    class FakeSegno:
        @staticmethod
        def make(payload: str):
            saved_payloads.append(payload)
            return FakeQR(payload)

    monkeypatch.setattr(qr, "_load_segno", lambda: FakeSegno)
    outputs = qr.generate_qr_codes(
        per_person=[Decimal("12.34"), Decimal("0.66")],
        provider="venmo",
        note="Dinner",
        directory=tmp_path,
        scale=3,
    )
    assert len(outputs) == 2
    assert all(p.exists() for p in outputs)
    assert saved_payloads[0].startswith("https://venmo.com/")


def test_generate_qr_codes_bad_provider(monkeypatch):
    from tipcalc import qr

    class DummySegno:
        @staticmethod
        def make(payload: str):
            return None

    monkeypatch.setattr(qr, "_load_segno", lambda: DummySegno)
    with pytest.raises(qr.QRGenerationError):
        qr.generate_qr_codes(per_person=[Decimal("1.00")], provider="unknown", note="Test", directory=Path("dummy"))


def test_run_cli_generates_qr(monkeypatch, tmp_path, capsys):
    from tipcalc import cli

    def fake_generate_qr_codes(**kwargs):
        out_dir = kwargs["directory"]
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / "qr_person_1.png"
        file_path.write_text("fake")
        return [file_path]

    monkeypatch.setattr(cli, "generate_qr_codes", fake_generate_qr_codes)
    monkeypatch.setattr(cli, "_save_tax_state", lambda *args, **kwargs: None)

    config = cli.AppConfig(
        default_tip_percent=Decimal("18"),
        quick_picks=[Decimal("20")],
    )
    monkeypatch.setattr(cli, "load_config", lambda path=None: config)

    exit_code = cli.run_cli(
        [
            "--total",
            "100.00",
            "--tax",
            "0",
            "--tip",
            "18",
            "--people",
            "1",
            "--qr",
            "--qr-dir",
            str(tmp_path / "codes"),
        ]
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "QR code" in out or "Saved" in out


def test_profiles_save_and_load(monkeypatch, tmp_path):
    monkeypatch.setenv("TIP_PROFILES_PATH", str(tmp_path / "profiles.json"))
    profiles.save_profile(
        "dinner",
        {
            "people": 4,
            "round_mode": "nearest",
            "granularity": "0.25",
            "locale": "en_US",
        },
    )
    loaded = profiles.get_profile("dinner")
    assert loaded is not None
    assert loaded["people"] == 4
    assert loaded["round_mode"] == "nearest"
    assert loaded["granularity"] == "0.25"
    assert loaded["locale"] == "en_US"


def test_run_cli_with_profile(monkeypatch, tmp_path):
    from tipcalc import cli

    monkeypatch.setenv("TIP_PROFILES_PATH", str(tmp_path / "profiles.json"))
    profiles.save_profile(
        "brunch",
        {
            "people": 3,
            "round_mode": "up",
            "granularity": "0.25",
            "locale": "en_GB",
        },
    )

    captured = {}

    def fake_compute(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            bill_before_tax=kwargs["total_bill"] - kwargs["tax_amount"],
            tip=Decimal("0"),
            final_total=kwargs["total_bill"],
            per_person=[kwargs["total_bill"]],
        )

    monkeypatch.setattr(cli, "compute_tip_split", fake_compute)
    monkeypatch.setattr(cli, "print_results", lambda **kwargs: "done")
    monkeypatch.setattr(cli, "_save_tax_state", lambda *a, **k: None)

    exit_code = cli.run_cli(
        [
            "--profile",
            "brunch",
            "--total",
            "90.00",
            "--tax",
            "0",
            "--tip",
            "18",
        ]
    )

    assert exit_code == 0
    assert captured["people"] == 3
    assert captured["round_mode"] == "up"
    assert captured["granularity"] == Decimal("0.25")


def test_tip_module_exports_and_version():
    expected_exports = {
        "__version__",
        "TipResult",
        "compute_tip_split",
        "parse_money",
        "parse_percentage",
        "parse_int",
        "to_cents",
        "CENT",
        "HUNDRED",
        "PERCENT_STEP",
        "quantize_amount",
        "fmt_money",
        "fmt_percent",
        "print_results",
        "lookup_tax_rate",
        "TaxLookupError",
        "TaxLookupResult",
        "generate_qr_codes",
        "QRGenerationError",
        "run_cli",
    }
    assert set(tipmod.__all__) == expected_exports

    try:
        expected_version = importlib_metadata.version("tip-calculator")
    except importlib_metadata.PackageNotFoundError:
        expected_version = "0+unknown"
    else:
        expected_version = expected_version or "0+unknown"

    assert isinstance(tipmod.__version__, str)
    assert tipmod.__version__ == expected_version


@pytest.mark.parametrize(
    "raw, expected",
    [
        (Decimal("1.005"), Decimal("1.00")),
        (Decimal("1.015"), Decimal("1.02")),
        (Decimal("-1.005"), Decimal("-1.00")),
        (Decimal("2.675"), Decimal("2.68")),
    ],
)
def test_quantize_amount_half_even(raw: Decimal, expected: Decimal) -> None:
    assert tipmod.quantize_amount(raw) == expected


@pytest.mark.parametrize(
    "raw, rounding, expected",
    [
        (Decimal("1.005"), ROUND_HALF_UP, Decimal("1.01")),
        (Decimal("2.335"), ROUND_HALF_UP, Decimal("2.34")),
    ],
)
def test_quantize_amount_custom_rounding(raw: Decimal, rounding, expected: Decimal) -> None:
    assert tipmod.quantize_amount(raw, rounding=rounding) == expected


if given is not None and st is not None:

    @st.composite
    def _split_scenarios(draw):
        total_cents = draw(st.integers(min_value=100, max_value=200000))
        tax_cents = draw(st.integers(min_value=0, max_value=total_cents - 1))
        tip_bp = draw(st.integers(min_value=0, max_value=10000))
        people = draw(st.integers(min_value=1, max_value=8))
        tip_on_pretax = draw(st.booleans())
        total = Decimal(total_cents) / Decimal("100")
        tax = Decimal(tax_cents) / Decimal("100")
        tip_percent = Decimal(tip_bp) / Decimal("100")
        return total, tax, tip_percent, people, tip_on_pretax

    def _split_sum_invariant_property(case):
        total_bill, tax_amount, tip_percent, people, tip_on_pretax = case
        results = tipmod.compute_tip_split(
            total_bill=total_bill,
            tax_amount=tax_amount,
            tip_percent=tip_percent,
            people=people,
            tip_on_pretax=tip_on_pretax,
        )
        total = sum(results.per_person, Decimal("0"))
        assert total == results.final_total
        assert all(share >= Decimal("0") for share in results.per_person)

    test_split_sum_invariant_property = given(_split_scenarios())(_split_sum_invariant_property)
else:

    @pytest.mark.skip(reason="requires hypothesis")
    def test_split_sum_invariant_property() -> None:
        pytest.skip("requires hypothesis")
