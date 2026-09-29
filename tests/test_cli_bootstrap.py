import mongomock
import pytest

from roster.cli import main
from roster.store.repositories import SchoolRepo, UserRepo


@pytest.fixture
def patched_db(monkeypatch):
    """Hand the CLI a mongomock database instead of a real connection."""
    database = mongomock.MongoClient()["roster_test"]

    def fake_database(_settings):
        return database

    monkeypatch.setattr("roster.cli._database_for_cli", fake_database)
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    return database


def test_create_school_writes_a_school_and_a_user(patched_db, capsys):
    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
        ]
    )

    assert code == 0
    schools = list(patched_db["schools"].find())
    assert len(schools) == 1
    assert schools[0]["name"] == "Meridian"
    assert schools[0]["cycleDays"] == 6

    user = UserRepo(patched_db).by_email("head@meridian.example")
    assert user is not None
    assert user.school_id == str(schools[0]["_id"])
    # The password is hashed, never stored as given.
    assert user.password_hash != "pw"
    assert "pw" not in user.password_hash


def test_create_school_accepts_grades_and_sections(patched_db):
    main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
            "--grades",
            "4,5",
            "--sections",
            "A,B",
        ]
    )

    school = SchoolRepo(patched_db).get(
        str(patched_db["schools"].find_one()["_id"])
    )
    assert school.grades == (4, 5)
    assert school.sections == ("A", "B")


def test_a_duplicate_email_exits_two_rather_than_tracebacking(
    patched_db, capsys
):
    args = [
        "create-school",
        "--name",
        "Meridian",
        "--email",
        "head@meridian.example",
        "--password",
        "pw",
    ]
    assert main(args) == 0
    assert main(args) == 2
    assert "already" in capsys.readouterr().err.lower()
    assert patched_db["schools"].count_documents({}) == 1


def test_a_missing_session_secret_exits_two(monkeypatch, capsys):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")

    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
        ]
    )

    assert code == 2
    assert "SESSION_SECRET" in capsys.readouterr().err


def test_bad_grades_exits_two_before_connecting(monkeypatch, capsys):
    """Bad grades input exits before connecting to database (Ruling 23)."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    # Track whether _database_for_cli was called
    def should_not_be_called(_settings):
        raise AssertionError("_database_for_cli should not be called for bad grades")

    monkeypatch.setattr("roster.cli._database_for_cli", should_not_be_called)

    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
            "--grades",
            "4,x,6",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "--grades" in err


def test_database_connection_error_exits_two(monkeypatch, capsys):
    """Database connection errors exit 2 with 'database' in message (Ruling 23)."""
    monkeypatch.setenv("MONGODB_URI", "mongodb://unused")
    monkeypatch.setenv("SESSION_SECRET", "test-secret")

    from pymongo.errors import ServerSelectionTimeoutError

    def fake_database_fails(_settings):
        raise ServerSelectionTimeoutError("down")

    monkeypatch.setattr("roster.cli._database_for_cli", fake_database_fails)

    code = main(
        [
            "create-school",
            "--name",
            "Meridian",
            "--email",
            "head@meridian.example",
            "--password",
            "pw",
        ]
    )

    assert code == 2
    err = capsys.readouterr().err
    assert "database" in err.lower()


def test_the_solve_command_still_works_without_the_server_extra():
    """Phase 1's CLI must not have acquired a pymongo import at module level."""
    import ast

    import roster.cli as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    top_level = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }

    forbidden = {
        m for m in top_level if m.split(".")[0] in {"pymongo", "bson"}
    }
    assert forbidden == set(), forbidden
