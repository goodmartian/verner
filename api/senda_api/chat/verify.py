"""Number check: every number in the answer must occur in the tool results of the dialogue.

Allowed values are the numeric leaves of the tool results and the numbers the person wrote.
A written number matches a value when it equals it after honest rounding to the digits shown
(half a unit of the last written digit); truncation does not pass.
Skipped: years (1900 to 2100), whole numbers 0 to 31 without a data unit next to them
(days, ranks, counts of things), and link targets.
Not caught: numbers written as words, a real number attached to the wrong area or month,
and a wrong conclusion drawn from right numbers. The prompt forbids arithmetic and the tools return ratios.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_THOUSANDS = ", \u00a0\u202f"  # a comma, a space, a no-break space, a narrow no-break space
_NUMBER = re.compile(
    r"(?<![\w.,])"
    r"(?P<num>\d{1,3}(?:[" + _THOUSANDS + r"]\d{3})+(?:\.\d+|,\d{1,2}(?!\d))?|\d+,\d{1,2}(?!\d)|\d+(?:\.\d+)?)"
    r"(?P<suf>\s?(?:%|×|x(?![a-zA-Z])|times\b|percent\b|thousand\b|million\b|k\b|M\b))?"
)
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
_FIRE_ID = re.compile(r"\b\d{8}-[0-9a-f]{6}\b")  # the id of a fire, not a data number
_CLOCK = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?![\d:])")  # 14:45 is a time of day, not a data number
_URL = re.compile(r"https?://\S+")
_UNIT_WORDS = ("detections", "detection", "hotspots", "hot spots", "detecciones", "puntos de calor", "очагов",
               "детекций", "mw", "km", "км", "times")
_EPS = 1e-9
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6}
_PERCENT = {"%", "percent"}
_TIMES = {"×", "x", "times"}


def leaves(node: Any, key: str = "") -> Iterable[tuple[str, float]]:
    """Numeric leaves of a JSON value with the name of the key that holds them."""
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        yield key, float(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from leaves(v, str(k))
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from leaves(v, key)


def _is_ratio(key: str) -> bool:
    return key.endswith("ratio") or key.startswith("ratio_to")


def _parse(match: re.Match) -> tuple[float, float, bool, str]:
    """Value as written (after k, M suffix), the unit of its last digit, whether it is a plain integer, the suffix."""
    raw = match.group("num")
    suffix = (match.group("suf") or "").strip()
    suffix = suffix if suffix in ("%", "×") else suffix.lower()
    grouped = re.search(r"[" + _THOUSANDS + r"]\d{3}(?!\d)", raw) is not None
    if grouped:
        whole, dot, comma = re.fullmatch(r"(.*?\d{3})(?:\.(\d+)|,(\d{1,2}))?", raw).groups()
        frac = dot or comma
        digits = re.sub(r"[" + _THOUSANDS + r"]", "", whole) + (f".{frac}" if frac else "")
    elif re.fullmatch(r"\d+,\d{1,2}", raw):
        digits = raw.replace(",", ".")
    else:
        digits = raw
    value = float(digits)
    if "." in digits:
        unit = 10.0 ** -len(digits.split(".")[1])
    else:
        unit = 1.0
        if grouped:
            tail = re.findall(r"[" + _THOUSANDS + r"](\d{3})", whole)
            for group in reversed(tail):
                if group != "000":
                    break
                unit *= 1000.0
    plain_int = "." not in digits and not grouped and not suffix
    scale = _SCALE.get(suffix, 1.0)
    return value * scale, unit * scale, plain_int, suffix


def _matches(value: float, unit: float, suffix: str, found: list[tuple[str, float]]) -> bool:
    half = unit / 2 + _EPS
    for key, v in found:
        v = abs(v)  # a written number carries no sign here: a gap of -2.94 is read as 2,94 %
        if suffix in _PERCENT:
            if key.endswith("_pct") and abs(v - value) <= half:  # already a percent: humidity_pct, area_change_..._pct
                return True
            if abs(100 * v - value) <= half:
                return True
            if _is_ratio(key) and (abs(100 * (v - 1) - value) <= half or abs(100 * (1 - v) - value) <= half):
                return True
        elif suffix in _TIMES:
            if _is_ratio(key) and abs(v - value) <= half:
                return True
        elif abs(v - value) <= half:
            return True
    return False


def _clean(text: str) -> str:
    return _FIRE_ID.sub(" ", _CLOCK.sub(" ", _URL.sub(" ", _LINK_TARGET.sub("]", text))))


MAX_KEPT = 5000


def kept(results: list[Any]) -> list[list]:
    """The numbers of the tool results of one answer as `[key, value]`, each once: what the chat keeps so that a later
    answer may quote them (the results themselves are not kept)."""
    return [[k, v] for k, v in dict.fromkeys(pair for r in results for pair in leaves(r))][:MAX_KEPT]


def unverified(text: str, results: list[Any], user_texts: list[str], earlier: Iterable[Iterable] = ()) -> list[str]:
    """Numbers of the answer that do not occur in the tool results (of this answer, or `earlier` ones of the chat, as
    `kept` gives them) or in what the person wrote."""
    found = [pair for r in results for pair in leaves(r)] + [(str(k), float(v)) for k, v in earlier]
    for t in user_texts:
        for m in _NUMBER.finditer(_clean(t)):
            value, _, _, _ = _parse(m)
            found.append(("question", value))
    bad = []
    body = _clean(text)
    for m in _NUMBER.finditer(body):
        value, unit, plain_int, suffix = _parse(m)
        if plain_int and 1900 <= value <= 2100:
            continue
        if plain_int and 0 <= value <= 31:
            after = body[m.end():m.end() + 18].lower().lstrip()
            if not after.startswith(_UNIT_WORDS):
                continue
        if not _matches(value, unit, suffix, found):
            bad.append(m.group(0).strip())
    return bad
