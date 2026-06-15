from horror_daily.config import load_yaml_config
from horror_daily.pipeline.priority import flatten_priority_entries, load_priority_config


def test_load_yaml_config():
    config = load_yaml_config("config/settings.yaml")

    assert config["runtime"]["days_back"] >= 1
    assert config["runtime"]["min_review_count_for_released"] == 200
    assert config["rss_sources"]
    priority_terms = config["steam_priority_search_terms"]
    assert "Fatal Frame" in priority_terms
    assert "零 红蝶" in priority_terms


def test_load_priority_config():
    priority = load_priority_config("config/priority.yaml")
    entries = flatten_priority_entries(priority)

    fatal_frame = next(entry for entry in entries if entry.name == "Fatal Frame")
    assert fatal_frame.tier == "tier_s"
    assert "Project Zero" in fatal_frame.aliases
    assert "Crimson Butterfly" in fatal_frame.aliases
    assert "FATAL FRAME II" in fatal_frame.aliases
