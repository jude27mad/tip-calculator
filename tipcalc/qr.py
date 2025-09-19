from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterable, List
from urllib.parse import quote_plus

from .formats import to_cents


class QRGenerationError(RuntimeError):
    """Raised when QR code generation fails."""


@dataclass
class QRCodeSpec:
    provider: str = "venmo"
    note: str = "tipcalc split"
    directory: Path = Path("qr_codes")
    scale: int = 5


def _load_segno():
    try:
        import segno  # type: ignore
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise QRGenerationError(
            "segno is required for QR generation. Install with `pip install tip-calculator[qr]`."
        ) from exc
    return segno


def _build_payload(provider: str, amount: Decimal, note: str) -> str:
    value = f"{to_cents(amount):.2f}"
    if provider.lower() == "venmo":
        return f"https://venmo.com/?txn=pay&amount={value}&note={quote_plus(note)}"
    if provider.lower() == "generic":
        return f"PAYMENT:{value}:{note}"
    raise QRGenerationError(f"Unsupported QR provider: {provider}")


def generate_qr_codes(
    *,
    per_person: Iterable[Decimal],
    provider: str,
    note: str,
    directory: Path,
    scale: int = 5,
) -> List[Path]:
    segno = _load_segno()
    directory.mkdir(parents=True, exist_ok=True)
    paths: List[Path] = []
    for idx, share in enumerate(per_person, 1):
        payload = _build_payload(provider, share, f"{note} P{idx}")
        qr = segno.make(payload)
        filename = directory / f"qr_person_{idx}.png"
        qr.save(str(filename), scale=scale)
        paths.append(filename)
    return paths
