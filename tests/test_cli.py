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
