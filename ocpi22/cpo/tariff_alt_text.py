"""Build short, multi-language `tariff_alt_text` strings for display on
payment terminals (e.g. Payter).

The output is a list of `(language, text)` tuples — one per supported
language — derived from the SolidTariff fields. Languages are hardcoded
to EN/FR/NL.

Format follows the convention agreed with the product team:

    energy → time (charging) → flat (starting fee) → parking

Example (EN):

    €0.45/kWh + €6/h charging + €1.00 starting fee + €3/h parking after 15min
"""

from typing import List, Optional, Tuple

SUPPORTED_LANGUAGES: Tuple[str, ...] = ("en", "fr", "nl")


def _fmt_amount(amount: float, currency: str, language: str) -> str:
    """Format an amount with currency symbol/code, language-aware decimal sep.

    EUR → `€` (prefix for EN/NL, suffix for FR by local convention).
    Other currencies → `<ISO> <amount>` prefix for all languages.
    """
    decimal_sep = "." if language == "en" else ","
    formatted = f"{amount:.2f}".replace(".", decimal_sep)

    if currency == "EUR":
        return f"{formatted}€" if language == "fr" else f"€{formatted}"
    return f"{currency} {formatted}"


def _fmt_rate(amount: float, unit: str, currency: str, language: str) -> str:
    """Format a per-unit rate, e.g. `€0.45/kWh` or `0,45€/kWh`."""
    return f"{_fmt_amount(amount, currency, language)}/{unit}"


# Per-language label tables. Keys map to the building blocks below.
_LABELS = {
    "en": {
        "hour_unit": "h",
        "time_suffix": " charging",
        "flat_suffix": " starting fee",
        "parking_suffix": " parking",
        "parking_grace": " parking after {minutes}min",
    },
    "fr": {
        "hour_unit": "h",
        "time_suffix": " recharge",
        "flat_suffix": " frais de démarrage",
        "parking_suffix": " stationnement",
        "parking_grace": " stationnement après {minutes}min",
    },
    "nl": {
        "hour_unit": "u",
        "time_suffix": " opladen",
        "flat_suffix": " startkost",
        "parking_suffix": " parkeren",
        "parking_grace": " parkeren na {minutes}min",
    },
}


def has_price_components(
    per_kwh: Optional[float],
    per_hr: Optional[float],
    flat: Optional[float],
    parking_per_hr: Optional[float],
) -> bool:
    return any(v is not None for v in (per_kwh, per_hr, flat, parking_per_hr))


def _get_alt_text(
    language: str,
    *,
    per_kwh: Optional[float],
    per_hr: Optional[float],
    flat: Optional[float],
    parking_per_hr: Optional[float],
    parking_grace_minutes: Optional[int],
    currency: str,
) -> str:
    labels = _LABELS[language]
    components: List[str] = []

    if per_kwh is not None:
        components.append(_fmt_rate(per_kwh, "kWh", currency, language))

    if per_hr is not None:
        components.append(
            _fmt_rate(per_hr, labels["hour_unit"], currency, language)
            + labels["time_suffix"]
        )

    if flat is not None:
        components.append(_fmt_amount(flat, currency, language) + labels["flat_suffix"])

    if parking_per_hr is not None:
        rate = _fmt_rate(parking_per_hr, labels["hour_unit"], currency, language)
        if parking_grace_minutes and parking_grace_minutes > 0:
            components.append(
                rate + labels["parking_grace"].format(minutes=parking_grace_minutes)
            )
        else:
            components.append(rate + labels["parking_suffix"])

    return " + ".join(components)


def build_tariff_alt_text(
    *,
    per_kwh: Optional[float],
    per_hr: Optional[float],
    flat: Optional[float],
    parking_per_hr: Optional[float],
    parking_grace_minutes: Optional[int],
    currency: str,
) -> List[Tuple[str, str]]:
    """Return a list of `(language, text)` tuples for EN/FR/NL.

    Always returns one entry per supported language. Zero values are treated
    as valid (e.g. free time-based charging) and are included. Raises
    ``ValueError`` if all components are None — callers must ensure at least
    one component is set before calling.
    """
    if not has_price_components(per_kwh, per_hr, flat, parking_per_hr):
        raise ValueError(
            "At least one price component must be set (per_kwh, per_hr, flat, or parking_per_hr)"
        )

    return [
        (
            language,
            _get_alt_text(
                language,
                per_kwh=per_kwh,
                per_hr=per_hr,
                flat=flat,
                parking_per_hr=parking_per_hr,
                parking_grace_minutes=parking_grace_minutes,
                currency=currency,
            ),
        )
        for language in SUPPORTED_LANGUAGES
    ]
