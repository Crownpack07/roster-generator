import pytest

from roster.store.config import ConfigError, settings_from_env


def test_a_missing_session_secret_refuses_to_produce_settings():
    """No default secret, ever.

    A baked-in default that works in development is a forged-session hole in
    production: anyone who reads the source can mint a valid cookie.
    """
    with pytest.raises(ConfigError, match="SESSION_SECRET"):
        settings_from_env({"MONGODB_URI": "mongodb://localhost:27017"})


def test_a_missing_mongodb_uri_refuses_to_produce_settings():
    with pytest.raises(ConfigError, match="MONGODB_URI"):
        settings_from_env({"SESSION_SECRET": "s"})


def test_defaults_match_the_spec():
    settings = settings_from_env(
        {"MONGODB_URI": "mongodb://localhost:27017", "SESSION_SECRET": "s"}
    )
    assert settings.mongodb_db == "roster"
    assert settings.solve_time_limit_s == 150.0
    assert settings.solve_max_workers == 1
    assert settings.cookie_secure is True


def test_the_environment_overrides_every_default():
    settings = settings_from_env(
        {
            "MONGODB_URI": "mongodb://example:27017",
            "SESSION_SECRET": "s",
            "MONGODB_DB": "other",
            "SOLVE_TIME_LIMIT_S": "12.5",
            "SOLVE_MAX_WORKERS": "3",
            "COOKIE_SECURE": "false",
        }
    )
    assert settings.mongodb_db == "other"
    assert settings.solve_time_limit_s == 12.5
    assert settings.solve_max_workers == 3
    assert settings.cookie_secure is False


def test_a_non_numeric_time_limit_is_a_config_error_not_a_crash():
    with pytest.raises(ConfigError, match="SOLVE_TIME_LIMIT_S"):
        settings_from_env(
            {
                "MONGODB_URI": "mongodb://localhost:27017",
                "SESSION_SECRET": "s",
                "SOLVE_TIME_LIMIT_S": "soon",
            }
        )
