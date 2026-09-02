"""Tests for prompt configuration loading and override behavior."""
from __future__ import annotations

import json
from pathlib import Path

from memosight.prompt_config import default_prompt_config, load_prompt_config


def test_default_prompt_config_loads_bundled_templates():
    config = default_prompt_config()

    assert "zh" in config
    assert "caption_stage" in config["zh"]
    assert config["zh"]["caption_stage"]["max_tokens"] == 128


def test_load_prompt_config_deep_merges_dict_override():
    config = load_prompt_config(
        {
            "zh": {
                "caption_stage": {
                    "text": "覆盖后的 caption prompt",
                }
            }
        }
    )

    assert config["zh"]["caption_stage"]["text"] == "覆盖后的 caption prompt"
    assert config["zh"]["caption_stage"]["max_tokens"] == 128
    assert config["en"]["one_stage"]["system"]


def test_load_prompt_config_deep_merges_file_override(tmp_path: Path):
    path = tmp_path / "prompt_config.json"
    path.write_text(
        json.dumps(
            {
                "en": {
                    "one_stage": {
                        "rules": "Custom English output rules.",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_prompt_config(path)

    assert config["en"]["one_stage"]["rules"] == "Custom English output rules."
    assert config["en"]["one_stage"]["system"].startswith("You are the MemoSight")
