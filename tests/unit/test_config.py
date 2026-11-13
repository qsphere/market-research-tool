from pathlib import Path

import pytest

from leadgen.config import ConfigError, Settings


def test_defaults():
    s = Settings()
    assert s.host == "127.0.0.1"
    assert s.db_path == Path("leadgen.db")
    assert s.enabled_sources == ("osm",)
    assert s.user_agent == "market-research-tool/0.1"


def test_contact_in_user_agent():
    assert "me@example.com" in Settings(contact="me@example.com").user_agent


def test_env_overrides():
    s = Settings.from_env(
        {
            "LEADGEN_PORT": "9000",
            "LEADGEN_DB_PATH": "x.db",
            "LEADGEN_ENABLED_SOURCES": "osm,fake",
            "LEADGEN_CACHE_HOURS": "2.5",
        }
    )
    assert s.port == 9000 and s.db_path == Path("x.db")
    assert s.enabled_sources == ("osm", "fake") and s.cache_hours == 2.5


@pytest.mark.parametrize(
    "env",
    [
        {"LEADGEN_PORT": "abc"},
        {"LEADGEN_PORT": "70000"},
        {"LEADGEN_CACHE_HOURS": "-1"},
        {"LEADGEN_NOMINATIM_MIN_INTERVAL": "0.2"},
        {"LEADGEN_POSSIBLE_NAME_THRESHOLD": "1.5"},
        {"LEADGEN_DEFAULT_REGION": "USA"},
    ],
)
def test_invalid_values_rejected(env):
    with pytest.raises(ConfigError):
        Settings.from_env(env)
