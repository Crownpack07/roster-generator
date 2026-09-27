"""Render a solved roster as readable grids.

The CLI emits JSON — 720 placements, machine-shaped. This turns that into the
two views a school actually reads: a grid per class for the classroom wall, and
a grid per teacher for each staff member.

    python -m roster.cli solve examples/meridian.json --time-limit 150 > roster.json
    python examples/show_roster.py examples/meridian.json roster.json
    python examples/show_roster.py examples/meridian.json roster.json --teachers

Deliberately not part of the `roster` package: Phase 4 owns real PDF and Excel
exports, and this is a convenience for seeing a timetable today. Monochrome, in
keeping with the design decision that printed grids carry no colour — the school
colours them by hand.
"""

from __future__ import annotations

import argparse
import json
import sys

DAYS = 6
PERIODS = 10


def load(problem_path: str, result_path: str) -> tuple[dict, dict]:
    with open(problem_path, encoding="utf-8") as fh:
        problem = json.load(fh)
    with open(result_path, encoding="utf-8") as fh:
        result = json.load(fh)
    return problem, result


def teacher_of(problem: dict) -> dict[tuple[int, str, str], str]:
    """(grade, section, subject) -> teacher id, from the problem's blocks."""
    owner: dict[tuple[int, str, str], str] = {}
    for block in problem["blocks"]:
        for section in block["sections"]:
            owner[(block["grade"], section, block["subject"])] = block["teacherId"]
    return owner


def grid(cells: dict[int, str]) -> list[str]:
    """One timetable as text: periods down, days across."""
    width = max((len(v) for v in cells.values()), default=8)
    width = max(width, 8)
    out = ["      " + "".join(f"{'Day ' + str(d + 1):<{width + 2}}" for d in range(DAYS))]
    for period in range(PERIODS):
        row = f"  p{period + 1:<3}"
        for day in range(DAYS):
            row += f"{cells.get(day * PERIODS + period, '·'):<{width + 2}}"
        out.append(row.rstrip())
    return out


def show_classes(problem: dict, result: dict) -> None:
    owner = teacher_of(problem)
    by_class: dict[tuple[int, str], dict[int, str]] = {}
    for p in result["placements"]:
        key = (p["grade"], p["section"])
        teacher = owner.get((p["grade"], p["section"], p["subject"]), "?")
        by_class.setdefault(key, {})[p["slot"]] = f"{p['subject']}/{teacher[:6]}"

    for (grade, section) in sorted(by_class):
        print(f"\n{'=' * 78}\n  GRADE {grade}{section}\n{'=' * 78}")
        for line in grid(by_class[(grade, section)]):
            print(line)


def show_teachers(problem: dict, result: dict) -> None:
    owner = teacher_of(problem)
    by_teacher: dict[str, dict[int, str]] = {}
    for p in result["placements"]:
        teacher = owner.get((p["grade"], p["section"], p["subject"]))
        if teacher is None:
            continue
        label = f"{p['grade']}{p['section']} {p['subject']}"
        by_teacher.setdefault(teacher, {})[p["slot"]] = label

    for teacher in sorted(by_teacher):
        taught = len(by_teacher[teacher])
        free = DAYS * PERIODS - taught
        print(f"\n{'=' * 78}\n  {teacher} — {taught} periods taught, {free} free\n{'=' * 78}")
        for line in grid(by_teacher[teacher]):
            print(line)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a solved roster as text grids.")
    ap.add_argument("problem", help="the problem JSON given to the solver")
    ap.add_argument("result", help="the JSON the solver printed")
    ap.add_argument(
        "--teachers",
        action="store_true",
        help="show one grid per teacher instead of one per class",
    )
    args = ap.parse_args(argv)

    problem, result = load(args.problem, args.result)

    status = result["status"]
    print(f"status            {status}")
    print(f"doubles placed    {result['doublesPlaced']} of {result['doublesCeiling']}")
    print(f"solve time        {result['wallSeconds']}s")
    for finding in result["findings"]:
        print(f"  [{finding['severity']}] {finding['code']}: {finding['message']}")

    if not result["placements"]:
        print("\nNo timetable to show.")
        if result.get("conflict"):
            print("\nWhy not:")
            for sentence in result["conflict"]["sentences"]:
                print(f"  - {sentence}")
            print("\nSmallest ways out:")
            for remedy in result["conflict"]["remedies"]:
                print(f"  - {remedy}")
        return 1

    if args.teachers:
        show_teachers(problem, result)
    else:
        show_classes(problem, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
