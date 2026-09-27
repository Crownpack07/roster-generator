import json

from roster.cli import main
from roster.io import problem_from_dict, problem_to_dict, result_to_dict
from roster.solve import SolveStatus, solve
from roster.verify import verify
from tests.fixtures.meridian import meridian_problem


def test_problem_survives_a_json_round_trip():
    original = meridian_problem()
    data = json.loads(json.dumps(problem_to_dict(original)))
    restored = problem_from_dict(data)
    assert restored.classes() == original.classes()
    assert set(restored.teachers) == set(original.teachers)
    assert restored.demand_for(4) == original.demand_for(4)
    assert len(restored.blocks) == len(original.blocks)


def test_round_tripped_problem_still_solves_and_verifies():
    original = meridian_problem()
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    result = solve(restored, seed=1, workers=1, time_limit_s=30.0)
    assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
    assert verify(restored, result.schedule) == []


def test_blocked_slots_survive_the_round_trip():
    original = meridian_problem(blocked={"Petra": frozenset({10, 11})})
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    assert restored.teachers["Petra"].blocked_slots == frozenset({10, 11})


def test_result_to_dict_is_json_serialisable():
    result = solve(meridian_problem(), seed=1, workers=1, time_limit_s=30.0)
    text = json.dumps(result_to_dict(result))
    payload = json.loads(text)
    assert payload["status"] in ("optimal", "feasible")
    assert 0 < payload["doublesPlaced"] <= payload["doublesCeiling"]
    assert len(payload["placements"]) == 720


def test_result_to_dict_carries_findings_and_conflict_keys():
    result = solve(
        meridian_problem(enabled_optional=("BIB", "SEP", "SPT")),
        seed=1,
        workers=1,
    )
    payload = result_to_dict(result)
    assert payload["status"] == "blocked"
    assert payload["placements"] == []
    assert any(f["code"] == "class_total" for f in payload["findings"])
    assert payload["conflict"] is None


def test_cli_solves_a_file_and_exits_zero(tmp_path, capsys):
    path = tmp_path / "problem.json"
    path.write_text(json.dumps(problem_to_dict(meridian_problem())))
    code = main(["solve", str(path), "--seed", "1", "--workers", "1",
                 "--time-limit", "30"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] in ("optimal", "feasible")


def test_cli_exits_one_when_preflight_blocks(tmp_path, capsys):
    problem = meridian_problem(enabled_optional=("BIB", "SEP", "SPT"))
    path = tmp_path / "problem.json"
    path.write_text(json.dumps(problem_to_dict(problem)))
    code = main(["solve", str(path)])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"


def test_cli_rejects_a_missing_file(tmp_path, capsys):
    code = main(["solve", str(tmp_path / "nope.json")])
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_rejects_a_structurally_invalid_problem_file(tmp_path, capsys):
    """Valid JSON, wrong shape: exit 2 with a message, never a traceback.

    Distinct from both a missing file and unparseable JSON. A hand-edited or
    truncated problem file lands here, and `problem_from_dict` indexes keys
    directly, so without a guard this surfaces as an uncaught KeyError.
    """
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"grades": [4], "sections": ["A"]}))
    code = main(["solve", str(path)])
    assert code == 2
    err = capsys.readouterr().err
    assert "not a valid problem file" in err
    assert "Traceback" not in err


def test_overrides_and_min_doubles_survive_the_round_trip():
    """The highest-risk fields in the whole serialisation layer.

    Both are dicts keyed by a `(grade, subject_code)` TUPLE, and JSON cannot
    express a tuple key at all — they serialise as lists of objects and must be
    reassembled on the way back. Every other test here leaves both dicts empty,
    so without this one the transform is only ever exercised on the empty case.
    Phase 2's API serves this shape, and a key that fails to reassemble would
    silently discard a school's deliberate curriculum overrides.
    """
    original = meridian_problem(
        overrides={(4, "SS"): 5, (7, "HL"): 9},
        min_doubles={(4, "HL"): 4, (5, "MATH"): 3},
    )
    restored = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(original)))
    )
    assert restored.scenario.overrides == {(4, "SS"): 5, (7, "HL"): 9}
    assert restored.scenario.min_doubles == {(4, "HL"): 4, (5, "MATH"): 3}
    # Empty dicts must come back empty, not as something falsy-but-different.
    plain = problem_from_dict(
        json.loads(json.dumps(problem_to_dict(meridian_problem())))
    )
    assert plain.scenario.overrides == {}
    assert plain.scenario.min_doubles == {}


def test_result_to_dict_serialises_a_populated_conflict():
    """The conflict branch, which every other test leaves as None.

    A minimum above the achievable ceiling is proven INFEASIBLE — grade 4 FAL
    has 10 periods, so its doubles ceiling is 4 and a minimum of 6 cannot hold.
    That is what populates the report.
    """
    problem = meridian_problem(min_doubles={(4, "FAL"): 6})
    result = solve(
        problem, run_preflight=False, seed=1, workers=1, time_limit_s=30.0
    )
    assert result.status is SolveStatus.INFEASIBLE
    payload = json.loads(json.dumps(result_to_dict(result)))
    assert payload["status"] == "infeasible"
    assert payload["placements"] == []
    assert payload["conflict"] is not None
    assert payload["conflict"]["ruleGroups"]
    assert payload["conflict"]["sentences"]
    assert payload["conflict"]["remedies"]
