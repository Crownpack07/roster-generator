"""Values derived from curriculum plus toggles. Never stored, always computed."""

from __future__ import annotations

import math

from roster.curriculum import Scenario
from roster.domain import DAYS, FILLER_CODE, SLOT_COUNT


def effective_periods(scenario: Scenario, grade: int, subject_code: str) -> int:
    """The CAPS count, or its override, or the optional count when enabled."""
    key = (grade, subject_code)
    if key in scenario.overrides:
        return scenario.overrides[key]
    caps = scenario.caps.periods(grade, subject_code)
    if caps:
        return caps
    if subject_code in scenario.enabled_optional:
        return scenario.optional.periods(grade, subject_code)
    return 0


def required_periods(scenario: Scenario, grade: int) -> dict[str, int]:
    """Every taught subject and its period count. Excludes filler."""
    codes = list(scenario.caps.subject_codes(grade))
    for code in scenario.optional.subject_codes(grade):
        if code in scenario.enabled_optional and code not in codes:
            codes.append(code)
    result: dict[str, int] = {}
    for code in codes:
        periods = effective_periods(scenario, grade, code)
        if periods:
            result[code] = periods
    return result


def filler_periods(scenario: Scenario, grade: int) -> int:
    """Slots left over. Deliberately may be negative so callers can report it."""
    return SLOT_COUNT - sum(required_periods(scenario, grade).values())


def demand(scenario: Scenario, grade: int) -> dict[str, int]:
    """What the solver must place, filler included as an ordinary subject."""
    result = dict(required_periods(scenario, grade))
    filler = filler_periods(scenario, grade)
    if filler > 0:
        result[FILLER_CODE] = filler
    return result


def doubles_ceiling(n: int) -> int:
    """Doubles achievable for a core subject held to 1-2 periods a day."""
    return max(0, n - DAYS)


def singles_count(n: int) -> int:
    return max(0, 2 * DAYS - n)


def max_per_day(n: int) -> int:
    """Spread cap for a non-core subject: ceil(n / 6)."""
    return math.ceil(n / DAYS)


def caps_deviation(scenario: Scenario, grade: int) -> dict[str, int]:
    """Signed difference from CAPS for every CAPS subject in this grade."""
    return {
        code: effective_periods(scenario, grade, code)
        - scenario.caps.periods(grade, code)
        for code in scenario.caps.subject_codes(grade)
    }
