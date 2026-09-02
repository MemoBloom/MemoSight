"""Prompt configuration loading and merging."""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, TypeAlias

PromptConfigInput: TypeAlias = dict[str, Any] | str | Path | None


@lru_cache(maxsize=1)
def default_prompt_config() -> dict[str, Any]:
    """Load bundled default prompt text from package data."""
    with resources.files("memosight.config").joinpath("default_prompts.json").open(
        "r",
        encoding="utf-8",
    ) as handle:
        return json.load(handle)


def load_prompt_config(config: PromptConfigInput = None) -> dict[str, Any]:
    """Return a prompt config, optionally deep-merged over bundled defaults."""
    base = copy.deepcopy(default_prompt_config())
    if config is None:
        return base
    if isinstance(config, dict):
        return _deep_merge(base, config)
    path = Path(config)
    with path.open("r", encoding="utf-8") as handle:
        override = json.load(handle)
    if not isinstance(override, dict):
        raise ValueError("prompt config file must contain a JSON object")
    return _deep_merge(base, override)


def language_prompt_config(config: dict[str, Any], language: str) -> dict[str, Any]:
    """Return the language config, falling back to English when needed."""
    lang = "zh" if language == "zh" else "en"
    value = config.get(lang) or config.get("en")
    if not isinstance(value, dict):
        raise ValueError(f"prompt config is missing language section: {lang}")
    return value


def prompt_config_section(
    lang_config: dict[str, Any],
    section: str,
) -> dict[str, Any]:
    """Return one config section as a dict."""
    value = lang_config.get(section)
    if not isinstance(value, dict):
        raise ValueError(f"prompt config section must be an object: {section}")
    return value


def prompt_config_text(
    container: dict[str, Any],
    key: str,
    *,
    section: str,
) -> str:
    """Read a required string from a config section."""
    value = container.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"prompt config {section}.{key} must be a non-empty string")
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base
