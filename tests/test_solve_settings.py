import pytest

from roster.solve import _solver


@pytest.mark.parametrize("workers", [None, 1, 3, 4, 8])
def test_the_solver_never_runs_on_fewer_than_four_workers(workers):
    """Measured: one worker finds no timetable in 30s on any school tried;
    two or three find one in 0.3s but cannot prove an infeasible school
    infeasible; four do both. See the note in roster/solve.py."""
    solver = _solver(30.0, seed=None, workers=workers)
    assert solver.parameters.num_search_workers >= 4
    if workers is not None and workers >= 4:
        assert solver.parameters.num_search_workers == workers
