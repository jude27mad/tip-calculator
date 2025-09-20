from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, Dict, Optional
from urllib import error, parse, request

from .formats import quantize_amount

CACHE_FILENAME = "tax_cache.json"
CACHE_TTL_HOURS = 24
USER_AGENT = "tipcalc/0.1 (+https://github.com/jude27mad/tip-calculator)"


class TaxLookupError(RuntimeError):
    """Raised when a tax lookup fails."""


@dataclass
class TaxLookupResult:
    zip_code: str
    country: str
    tax_type: str
    value: Decimal
    source: str
    fetched_at: datetime

    def cache_payload(self) -> Dict[str, str]:
        return {
            "zip": self.zip_code,
            "country": self.country,
            "tax_type": self.tax_type,
            "tax_value": str(self.value),
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat(),
        }


FetchFunc = Callable[[str, str], TaxLookupResult]


def _cache_path() -> Path:
    override = os.environ.get("TIP_TAX_CACHE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.cwd() / CACHE_FILENAME


def _load_cache() -> Dict[str, Dict[str, str]]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def _save_cache(data: Dict[str, Dict[str, str]]) -> None:
    path = _cache_path()
    try:
        path.write_text(json.dumps(data, indent=2, sort_keys=True))
    except Exception:
        # Cache failures are non-fatal.
        pass


def _cache_key(zip_code: str, country: str) -> str:
    return f"{country.upper()}:{zip_code.upper()}"


def _parse_cached(entry: Dict[str, str]) -> Optional[TaxLookupResult]:
    try:
        value = Decimal(entry["tax_value"])
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        return TaxLookupResult(
            zip_code=entry["zip"],
            country=entry["country"],
            tax_type=entry["tax_type"],
            value=value,
            source=entry.get("source", "cache"),
            fetched_at=fetched_at,
        )
    except (KeyError, InvalidOperation, ValueError):
        return None


def _remote_fetch(zip_code: str, country: str) -> TaxLookupResult:
    base_url = os.environ.get("TIP_TAX_API_BASE", "https://api.api-ninjas.com/v1/salestax")
    params = {"zip": zip_code, "country": country}
    url = f"{base_url}?{parse.urlencode(params)}"
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    api_key = os.environ.get("TIP_TAX_API_KEY")
    if api_key:
        req.add_header("X-Api-Key", api_key)
    elif "api.api-ninjas.com" in base_url:
        raise TaxLookupError("TIP_TAX_API_KEY environment variable is required for the default tax API.")

    try:
        with request.urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore") or exc.reason
        raise TaxLookupError(f"Tax lookup failed: {detail}") from exc
    except Exception as exc:  # pragma: no cover - transient network issues
        raise TaxLookupError(f"Tax lookup failed: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TaxLookupError("Tax API returned invalid JSON") from exc

    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        raise TaxLookupError("Unexpected tax API response format")

    raw_rate = (
        payload.get("total_rate")
        or payload.get("totalRate")
        or payload.get("combined_rate")
        or payload.get("combinedRate")
        or payload.get("rate")
        or payload.get("total")
    )
    if raw_rate is None:
        raise TaxLookupError("Tax API response missing total rate")

    rate = Decimal(str(raw_rate))
    if rate <= Decimal("1"):
        rate *= Decimal("100")

    source = payload.get("summary") or payload.get("jurisdictions") or payload.get("details") or "remote"
    if not isinstance(source, str):
        try:
            source = json.dumps(source, sort_keys=True)
        except Exception:
            source = "remote"

    return TaxLookupResult(
        zip_code=zip_code,
        country=country,
        tax_type="percent",
        value=quantize_amount(rate, step=Decimal("0.001")),
        source=source,
        fetched_at=datetime.now(timezone.utc),
    )


def lookup_tax_rate(
    zip_code: str,
    *,
    country: str = "US",
    fetcher: Optional[FetchFunc] = None,
    ttl_hours: int = CACHE_TTL_HOURS,
    use_cache: bool = True,
) -> TaxLookupResult:
    cleaned_zip = zip_code.strip().replace(" ", "")
    if not cleaned_zip:
        raise TaxLookupError("ZIP/postal code is required")

    key = _cache_key(cleaned_zip, country)
    cache: Dict[str, Dict[str, str]] = _load_cache() if use_cache else {}

    if use_cache and key in cache:
        cached = _parse_cached(cache[key])
        if cached and datetime.now(timezone.utc) - cached.fetched_at <= timedelta(hours=ttl_hours):
            return cached

    fetch_impl = fetcher or _remote_fetch
    result = fetch_impl(cleaned_zip, country.upper())

    if use_cache:
        cache[key] = result.cache_payload()
        _save_cache(cache)

    return result
