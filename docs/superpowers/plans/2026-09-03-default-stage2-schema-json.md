# 默认 profile 二阶段 schema-driven JSON 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把默认 profile（`photography_default`）的两阶段 stage-2 从固定 Markdown 切换为 schema-driven JSON，降低丢字段导致的 partial 率，并用固定 captions 配对基准验证效果。

**Architecture:** stage-2 默认分支复用现有的 `build_caption_structured_extraction_prompt` + `parse_model_output`（strict/fenced/embedded 三级容错）+ `normalize_caption_fields`，校验改为"JSON 对象中 7 个字段键齐全"（与旧 Markdown 的"7 行齐全"严格度一致）。stage-2 schema 去掉 caption（由 stage-1 钉死），避免重复生成浪费 token。评测脚本自包含编排新旧两条路径，不给 pipeline 加开关。

**Tech Stack:** Python 3.11+、pydantic v2、pytest + pytest-asyncio、本地 mlx-vlm server（http://127.0.0.1:8080）。

**Spec:** `docs/superpowers/specs/2026-09-03-default-stage2-schema-json-design.md`

## Global Constraints

- 不改 stage-1（caption 生成）、不改一阶段 `pipeline.py` 的 Markdown 兜底。
- 不删除 `parse_markdown_fields`、`find_markdown_field_keys`、`build_caption_field_extraction_prompt` 及其在 `memosight/__init__.py` 的导出（单阶段兜底、基准脚本、legacy 测试仍在用）。
- 对外结果契约不变：`observation` = `{caption, scene_labels, people, actions, objects, lighting, mood, search_tags}`；失败 → `status=partial` 且 caption 保留。
- 失败语义不变：解析/校验失败 → `MemoSightFieldExtractionResult(status="failed", fields=empty_caption_fields() 或已归一化字段)`，上层 `analyze` 映射为 `partial`。
- 测试运行命令：`python -m pytest tests/ -x -q`（项目使用 `.venv`，先 `source .venv/bin/activate` 或用 `.venv/bin/python -m pytest`）。
- 评测脚本写到 `results/` 新文件，绝不修改已有结果文件。

---

### Task 1: profiles.py 新增 stage-2 字段 schema（去掉 caption）

**Files:**
- Modify: `memosight/profiles.py`（在 `_PHOTOGRAPHY_DEFAULT_SCHEMA` 定义之后）
- Test: `tests/test_memosight_profiles.py`

**Interfaces:**
- Produces: `memosight.profiles.PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA: dict[str, Any]` — 7 个数组字段（`scene_labels, people, actions, objects, lighting, mood, search_tags`），`required` 为全部 7 个键，无 `caption`。Task 3 的 two_stage.py 和 Task 4 的评测脚本依赖它。

- [ ] **Step 1: 写失败测试**

在 `tests/test_memosight_profiles.py` 末尾追加（先读该文件确认 import 风格）：

```python
def test_default_fields_schema_drops_caption_and_requires_seven_fields():
    from memosight.normalizer import CAPTION_FIELD_KEYS
    from memosight.profiles import (
        PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA,
        PROFILES,
    )

    schema = PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA
    full = PROFILES["photography_default"].output_schema

    assert schema["type"] == "object"
    assert set(schema["properties"]) == set(CAPTION_FIELD_KEYS)
    assert "caption" not in schema["properties"]
    assert sorted(schema["required"]) == sorted(CAPTION_FIELD_KEYS)
    # 字段 spec 与完整 schema 共享同一对象，不允许漂移。
    for key in CAPTION_FIELD_KEYS:
        assert schema["properties"][key] is full["properties"][key]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_memosight_profiles.py::test_default_fields_schema_drops_caption_and_requires_seven_fields -v`
Expected: FAIL，`ImportError: cannot import name 'PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA'`

- [ ] **Step 3: 实现**

在 `memosight/profiles.py` 的 `_PHOTOGRAPHY_DEFAULT_SCHEMA` 定义之后（约 line 124 之后）插入：

```python
# Stage-two extraction schema for the default profile: the seven retrieval
# fields only. ``caption`` is dropped because stage one already produced it
# and the pipeline pins it; asking the model to regenerate it wastes output
# tokens and risks truncation.
PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        key: spec
        for key, spec in _PHOTOGRAPHY_DEFAULT_SCHEMA["properties"].items()
        if key != "caption"
    },
    "required": [
        key for key in _PHOTOGRAPHY_DEFAULT_SCHEMA["required"] if key != "caption"
    ],
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_memosight_profiles.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add memosight/profiles.py tests/test_memosight_profiles.py
git commit -m "feat: add caption-less stage-two fields schema for default profile"
```

---

### Task 2: caption_json_stage 支持 max_tokens=224

**Files:**
- Modify: `memosight/config/default_prompts.json`（zh 和 en 的 `caption_json_stage`）
- Modify: `memosight/prompts.py`（`build_caption_structured_extraction_prompt`）
- Test: `tests/test_memosight_prompts.py`

**Interfaces:**
- Consumes: 现有 `prompt_config_section` / `prompt_config_text`（`memosight/prompt_config.py`）。
- Produces: `build_caption_structured_extraction_prompt` 返回的 `MemoSightPrompt.max_tokens` 从 stage config 读取（默认 224，可被 runtime prompt_config 覆盖）。Task 3 依赖此行为。

- [ ] **Step 1: 写失败测试**

在 `tests/test_memosight_prompts.py` 的 `test_caption_structured_extraction_prompt_is_schema_driven` 之后追加：

```python
def test_caption_structured_extraction_prompt_has_default_max_tokens():
    profile = resolve_profile(output_schema=CUSTOM_SCHEMA)
    prompt = build_caption_structured_extraction_prompt("黑色手表。", profile)

    assert prompt.max_tokens == 224


def test_caption_structured_extraction_prompt_max_tokens_config_override():
    config = {"zh": {"caption_json_stage": {"max_tokens": 96}}}

    prompt = build_caption_structured_extraction_prompt(
        "黑色手表。",
        resolve_profile(output_schema=CUSTOM_SCHEMA),
        prompt_config=config,
    )

    assert prompt.max_tokens == 96
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_memosight_prompts.py::test_caption_structured_extraction_prompt_has_default_max_tokens -v`
Expected: FAIL，`assert None == 224`

- [ ] **Step 3: 实现**

`memosight/config/default_prompts.json`：zh 的 `caption_json_stage`（当前 line 31-34）改为：

```json
    "caption_json_stage": {
      "system": "你是 MemoSight caption 结构化抽取助手。只使用 caption 明确写出的事实，不要猜测、补充或推断图片中未写出的信息。",
      "rules": "抽取要求：\n- 只输出一个 JSON 对象，不要使用 Markdown 代码块，不要输出任何解释。\n- 上面给出的字段名（含嵌套字段）必须全部出现，不要新增字段。\n- 字段名、嵌套结构和类型必须严格匹配上面的 JSON 字段定义。\n- caption 没有明确写出的内容：非枚举字符串用空字符串，数组用空数组，布尔值在 caption 没有明确支持该判断时用 false。\n- 枚举字段只能从给定可选值中挑选；如果枚举值明确包含 \"unknown\"，证据不足时可以使用该值。\n- 多值字段使用数组；遵守每个字段的最大条目数限制。",
      "max_tokens": 224
    }
```

en 的 `caption_json_stage`（当前 line 65-68）同样加 `"max_tokens": 224`：

```json
    "caption_json_stage": {
      "system": "You are the MemoSight caption structured extraction assistant. Use only facts explicitly stated in the caption. Do not guess, add, or infer unstated image details.",
      "rules": "Extraction rules:\n- Output exactly one JSON object. No Markdown fences, no explanations.\n- Every field name above, including nested fields, must appear; do not add fields.\n- Field names, nesting, and types must strictly match the JSON field definitions above.\n- For content not explicitly stated in the caption: use an empty string for non-enum strings, empty arrays for arrays, and false for booleans unless the caption explicitly supports true.\n- For enum fields, choose only from the listed choices; if an enum explicitly includes \"unknown\", use that value when evidence is insufficient.\n- Use arrays for multi-value fields and respect each field's maximum item count.",
      "max_tokens": 224
    }
```

`memosight/prompts.py` 的 `build_caption_structured_extraction_prompt`（当前 line 107-182）：在 `system = prompt_config_text(...)` 之后加一行读取，并改返回值：

```python
    system = prompt_config_text(
        stage_config,
        "system",
        section="caption_json_stage",
    )
    max_tokens = stage_config.get("max_tokens")
```

返回处改为：

```python
    return MemoSightPrompt(
        text="\n".join(lines),
        language=lang,
        system=system,
        schema_name=f"{profile.schema_name}_caption_json",
        max_tokens=max_tokens if isinstance(max_tokens, int) else None,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_memosight_prompts.py -v`
Expected: 全部 PASS（含既有 caption_json_stage 用例）

- [ ] **Step 5: Commit**

```bash
git add memosight/config/default_prompts.json memosight/prompts.py tests/test_memosight_prompts.py
git commit -m "feat: honor max_tokens in caption JSON extraction stage (default 224)"
```

---

### Task 3: two_stage.py 默认分支切换为 schema-driven JSON

**Files:**
- Modify: `memosight/two_stage.py`（module docstring、imports、`_extract_fields_for_profile` 默认分支）
- Test: `tests/test_two_stage_pipeline.py`
- Test: `tests/test_memosight_prompts.py`（追加一个默认 profile 的 JSON stage-2 prompt 测试）

**Interfaces:**
- Consumes: Task 1 的 `PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA`；Task 2 的 max_tokens 行为；现有 `parse_model_output`、`normalize_caption_fields`、`empty_caption_fields`、`build_caption_structured_extraction_prompt`、`validator.validate_payload`。
- Produces: 默认 profile stage-2 的 prompt `schema_name == "photography_default_caption_json"`；`usage["parse_strategy"]` 变为 `strict`/`fenced`/`embedded`/`None`。Task 4 评测脚本的 JSON 侧直接调 `pipeline.extract_fields(caption)` 走这条路径。

- [ ] **Step 1: 改测试（先全红）**

`tests/test_two_stage_pipeline.py`：

1. 文件顶部 docstring 改为 `"""Contract tests for caption -> schema-driven JSON -> normalized observation."""`；`import json` 加到 `from pathlib import Path` 之前。

2. `VALID_MARKDOWN` 常量替换为：

```python
VALID_JSON = json.dumps(
    {
        "scene_labels": ["婚礼", "室内"],
        "people": ["新人", "宾客"],
        "actions": ["站立", "合影"],
        "objects": ["花艺", "舞台", "礼服"],
        "lighting": ["暖光"],
        "mood": ["庄重", "温馨"],
        "search_tags": ["婚礼", "新人", "舞台", "暖光"],
    },
    ensure_ascii=False,
)
```

3. `test_two_stage_success_preserves_default_output_contract`：`MockMemoSightTextBackend(response=VALID_MARKDOWN)` → `response=VALID_JSON`；`result.structured_raw_output == VALID_MARKDOWN` 和 `result.raw_output == VALID_MARKDOWN` → `== VALID_JSON`；`result.usage["parse_strategy"] == "markdown"` → `== "strict"`。其余断言不变。

4. `test_prompts_are_short_and_single_purpose`：字段 prompt 断言改为：

```python
    field_prompt = text_backend.calls[0]
    assert "JSON" not in caption_prompt.text
    assert "scene_labels" not in caption_prompt.text
    assert len(caption_prompt.text) < 120
    assert "只输出" in caption_prompt.text
    assert "只使用 caption 明确写出的事实" in field_prompt.system
    assert all(f'"{key}"' in field_prompt.text for key in CAPTION_FIELD_KEYS)
    assert '"caption"' not in field_prompt.text
    assert len(field_prompt.system) < 80
    assert "室内暖光下的一人站在桌旁" in field_prompt.text
    assert field_prompt.schema_name == "photography_default_caption_json"
    assert field_prompt.max_tokens == 224
```

（`response=VALID_MARKDOWN` → `VALID_JSON`。）

5. `test_missing_markdown_line_is_partial_and_caption_is_preserved` 重命名为 `test_missing_json_field_is_partial_and_caption_is_preserved`，body 改为：

```python
@pytest.mark.asyncio
async def test_missing_json_field_is_partial_and_caption_is_preserved(tmp_path):
    caption = "一人在室内桌旁站立。"
    payload = json.loads(VALID_JSON)
    del payload["lighting"]
    incomplete = json.dumps(payload, ensure_ascii=False)
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response=caption),
        MockMemoSightTextBackend(response=incomplete),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "partial"
    assert result.failed_stage == "field_extraction"
    assert result.observation["caption"] == caption
    assert result.observation["lighting"] == []
    assert any("lighting" in issue.message for issue in result.validation.issues)
```

6. `test_field_stage_can_be_rerun_without_image`：`response=VALID_MARKDOWN` → `VALID_JSON`。

7. `test_none_values_become_empty_arrays` 改名 `test_empty_arrays_pass_validation`：

```python
@pytest.mark.asyncio
async def test_empty_arrays_pass_validation(tmp_path):
    empty_json = json.dumps({key: [] for key in CAPTION_FIELD_KEYS})
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response="空旷室内。"),
        MockMemoSightTextBackend(response=empty_json),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "ok"
    assert all(result.observation[key] == [] for key in CAPTION_FIELD_KEYS)
```

8. `test_chinese_empty_value_becomes_empty_array` 替换为两个新测试：

```python
@pytest.mark.asyncio
async def test_string_field_value_is_coerced_to_single_item_array(tmp_path):
    payload = json.loads(VALID_JSON)
    payload["mood"] = "温馨"
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response="空旷室内。"),
        MockMemoSightTextBackend(response=json.dumps(payload, ensure_ascii=False)),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "ok"
    assert result.observation["mood"] == ["温馨"]


@pytest.mark.asyncio
async def test_legacy_markdown_output_is_partial_under_json_stage(tmp_path):
    caption = "两位新人站在暖光舞台中央。"
    markdown = "**scene_labels:** 婚礼, 室内\n**people:** 新人, 宾客"
    pipeline = TwoStageMemoSightPipeline(
        MockMemoSightBackend(response=caption),
        MockMemoSightTextBackend(response=markdown),
    )

    result = await pipeline.analyze(_request(tmp_path))

    assert result.status == "partial"
    assert result.failed_stage == "field_extraction"
    assert result.observation["caption"] == caption
    assert all(result.observation[key] == [] for key in CAPTION_FIELD_KEYS)
```

9. `test_prompt_config_flows_through_two_stage_pipeline`：`response=VALID_MARKDOWN` → `VALID_JSON`；config 的 `markdown_field_stage` 段改为 `caption_json_stage`：

```python
            "caption_json_stage": {
                "system": "运行时自定义字段系统提示。",
                "rules": "运行时自定义字段规则。",
                "max_tokens": 48,
            },
```

断言改为：

```python
    assert field_prompt.system == "运行时自定义字段系统提示。"
    assert field_prompt.text.endswith("运行时自定义字段规则。")
    assert field_prompt.max_tokens == 48
```

`tests/test_memosight_prompts.py` 追加：

```python
def test_default_fields_schema_prompt_lists_seven_fields_without_caption():
    from memosight.profiles import PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA

    profile = get_profile("photography_default").model_copy(
        update={"output_schema": PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA}
    )
    prompt = build_caption_structured_extraction_prompt("室内暖光下的人。", profile)

    assert prompt.schema_name == "photography_default_caption_json"
    assert prompt.max_tokens == 224
    for field in CAPTION_FIELD_KEYS:
        assert f'"{field}"' in prompt.text
    assert '"caption"' not in prompt.text
```

（文件顶部 import 加 `from memosight.normalizer import CAPTION_FIELD_KEYS`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_two_stage_pipeline.py tests/test_memosight_prompts.py -x -q`
Expected: FAIL（mock 返回的是 JSON，但旧代码按 Markdown 解析 → missing fields / not recognized）

- [ ] **Step 3: 实现 two_stage.py 改动**

a) module docstring（当前 line 1-8）改为：

```python
"""Two-stage structured output: image -> caption -> structured fields.

The stage boundary is intentional: visual inference only writes a concise
caption, while a text-only call extracts fields. All profiles use
schema-driven JSON prompts for stage two (the default profile uses a
caption-less fields schema); the legacy fixed-Markdown parser remains for
the one-stage fallback and external callers. Stage two is public and
independently retryable, so a malformed text response does not require
repeating visual inference.
"""
```

b) imports：删除 `find_markdown_field_keys`、`parse_markdown_fields`、`build_caption_field_extraction_prompt`；`from .profiles import DEFAULT_PROFILE_NAME, MemoSightProfile, resolve_profile` 改为：

```python
from .profiles import (
    DEFAULT_PROFILE_NAME,
    PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA,
    MemoSightProfile,
    resolve_profile,
)
```

`from .prompts import (...)` 只保留 `build_caption_prompt, build_caption_structured_extraction_prompt`。

c) `_extract_fields_for_profile` 默认分支（当前 line 289-368，即 `prompt = build_caption_field_extraction_prompt(...)` 到函数末尾）整体替换为：

```python
        fields_profile = profile.model_copy(
            update={"output_schema": PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA}
        )
        prompt = build_caption_structured_extraction_prompt(
            caption,
            fields_profile,
            language=language,
            output_instructions=output_instructions,
            prompt_config=prompt_config,
        )
        model_started = time.perf_counter()
        try:
            raw_output = await self._text_backend.complete(prompt)
        except Exception as exc:
            logger.exception("Two-stage field extraction backend failed")
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=empty,
                validation=MemoSightValidationResult(),
                usage={
                    "structured_output_duration_s": time.perf_counter()
                    - model_started,
                    "postprocess_duration_s": 0.0,
                },
                error=f"Field extraction backend failed: {exc}",
            )
        structured_duration_s = time.perf_counter() - model_started

        post_started = time.perf_counter()
        parsed = parse_model_output(raw_output)
        issues: list[MemoSightValidationIssue] = []
        if parsed.data is None:
            parse_issue = parsed.error
            issues.append(
                MemoSightValidationIssue(
                    source=f"{_ISSUE_SOURCE}.fields",
                    message=(
                        parse_issue.message
                        if parse_issue
                        else "Field output is not recognized JSON"
                    ),
                    line=parse_issue.line if parse_issue else None,
                    column=parse_issue.column if parse_issue else None,
                )
            )
            fields = empty
        else:
            # Presence check happens on the raw JSON object: normalization
            # back-fills absent keys with empty lists, which would mask the
            # dropped-field failure mode this stage is meant to catch.
            missing = [key for key in CAPTION_FIELD_KEYS if key not in parsed.data]
            if missing:
                issues.append(
                    MemoSightValidationIssue(
                        source=f"{_ISSUE_SOURCE}.fields",
                        message=f"Missing required JSON fields: {', '.join(missing)}",
                    )
                )
            fields = normalize_caption_fields(parsed.data)
        if not issues:
            issues.extend(
                self._validator.validate_payload(
                    {"caption": caption, **fields},
                    source=f"{_ISSUE_SOURCE}.fields",
                )
            )
        postprocess_duration_s = time.perf_counter() - post_started
        usage = {
            "structured_output_duration_s": structured_duration_s,
            "postprocess_duration_s": postprocess_duration_s,
            "parse_strategy": parsed.strategy,
        }
        validation = MemoSightValidationResult(
            checked=1,
            valid=0 if issues else 1,
            issues=issues,
        )
        if issues:
            return MemoSightFieldExtractionResult(
                status="failed",
                fields=fields,
                raw_output=raw_output,
                validation=validation,
                usage=usage,
                error=f"Field output failed validation ({len(issues)} issue(s))",
            )
        return MemoSightFieldExtractionResult(
            status="ok",
            fields=fields,
            raw_output=raw_output,
            validation=validation,
            usage=usage,
        )
```

注意：`prompt_plan` 参数保持不传入默认分支（与旧 Markdown 分支行为一致，YAGNI）。

- [ ] **Step 4: 跑全部测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS。若有其它测试引用旧 Markdown 行为（如 `test_memosight_backends.py`、`test_memosight_cli.py`），只更新与默认 stage-2 输出格式相关的断言，不改测试意图。

- [ ] **Step 5: Commit**

```bash
git add memosight/two_stage.py tests/test_two_stage_pipeline.py tests/test_memosight_prompts.py
git commit -m "feat: switch default profile stage-two to schema-driven JSON"
```

---

### Task 4: 配对基准脚本 compare_stage2_markdown_vs_json.py

**Files:**
- Create: `scripts/compare_stage2_markdown_vs_json.py`

**Interfaces:**
- Consumes: Task 3 之后的 `TwoStageMemoSightPipeline.extract_fields(caption)`（JSON 候选）；`build_caption_field_extraction_prompt` + `parse_markdown_fields` + `find_markdown_field_keys` + `normalize_caption_fields`（Markdown 基线，脚本内复现旧 pipeline 逻辑）；`MlXVlmMemoSightBackend.describe` + `build_caption_prompt`（caption 缓存生成）。
- Produces: `results/compare_stage2_markdown_vs_json.json` 和 `.md`；`results/stage2_caption_cache.json`（caption 缓存，重复运行不重跑视觉）。

- [ ] **Step 1: 写脚本**

完整内容：

```python
"""Paired benchmark: legacy fixed-Markdown vs schema-driven JSON stage two.

Stage one is not rerun for cached captions. Captions come from preserved
benchmarks plus test_data frames (generated once into a cache file).
Baseline/candidate execution order alternates per caption to reduce order
bias. All outputs go to new files; source benchmark files are never modified.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from memosight import (
    CAPTION_FIELD_KEYS,
    MemoSightImageSource,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient
from memosight.normalizer import empty_caption_fields, normalize_caption_fields
from memosight.parser import find_markdown_field_keys, parse_markdown_fields
from memosight.prompts import (
    build_caption_field_extraction_prompt,
    build_caption_prompt,
)
from memosight.source import resolve_image_source

CAPTION_SOURCES = [
    Path("results/compare_one_stage_vs_two_stage_736x416.json"),
    Path("results/squat_compare_one_vs_two.json"),
]
CACHE_PATH = Path("results/stage2_caption_cache.json")
TEST_DATA = Path("test_data")
OUT_JSON = Path("results/compare_stage2_markdown_vs_json.json")
OUT_MD = Path("results/compare_stage2_markdown_vs_json.md")


def load_preserved_captions() -> list[dict]:
    captions = []
    for path in CAPTION_SOURCES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data["records"] if isinstance(data, dict) else data
        for record in records:
            caption = (record.get("two_stage") or {}).get("caption_raw_output")
            if caption:
                captions.append(
                    {"source": f"{path.name}:{record.get('frame', '?')}", "caption": caption}
                )
    return captions


async def load_test_data_captions(image_backend) -> list[dict]:
    cache = (
        json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if CACHE_PATH.exists()
        else {}
    )
    frames = sorted(
        path for path in TEST_DATA.glob("*/*.jpg") if path.parent.name != "report"
    )
    prompt = build_caption_prompt(language="zh")
    captions = []
    dirty = False
    for index, frame in enumerate(frames, 1):
        key = str(frame)
        if key not in cache:
            print(f"caption [{index}/{len(frames)}] {key}", flush=True)
            resolved = resolve_image_source(MemoSightImageSource(image_path=key))
            cache[key] = await image_backend.describe(resolved, prompt)
            dirty = True
        captions.append({"source": key, "caption": cache[key]})
    if dirty:
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return captions


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "avg": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": ordered[p95_index],
        "min": min(values),
        "max": max(values),
    }


def _field_metrics(fields: dict) -> dict:
    counts = {key: len(fields.get(key, [])) for key in CAPTION_FIELD_KEYS}
    return {"counts": counts, "total_items": sum(counts.values())}


async def run_markdown(text_backend, client, caption: str) -> dict:
    """Replicate the pre-JSON pipeline branch as the baseline."""
    prompt = build_caption_field_extraction_prompt(caption)
    started = time.perf_counter()
    raw = await text_backend.complete(prompt)
    total_s = time.perf_counter() - started
    meta = dict(getattr(client, "_last_response_meta", {}) or {})
    parsed = parse_markdown_fields(raw)
    present = find_markdown_field_keys(raw)
    missing = [key for key in CAPTION_FIELD_KEYS if key not in present]
    fields = (
        normalize_caption_fields(parsed) if parsed is not None else empty_caption_fields()
    )
    return {
        "status": "ok" if parsed is not None and not missing else "failed",
        "missing_fields": missing,
        "fields": fields,
        "raw_output": raw,
        "timings_s": {"total": total_s},
        "completion_tokens": meta.get("usage", {}).get("completion_tokens", 0),
        "metrics": _field_metrics(fields),
    }


async def run_json(pipeline, client, caption: str) -> dict:
    started = time.perf_counter()
    result = await pipeline.extract_fields(caption)
    total_s = time.perf_counter() - started
    meta = dict(getattr(client, "_last_response_meta", {}) or {})
    return {
        "status": result.status,
        "missing_fields": [
            issue.message.removeprefix("Missing required JSON fields: ").split(", ")
            for issue in result.validation.issues
            if issue.message.startswith("Missing required JSON fields")
        ],
        "fields": result.fields,
        "raw_output": result.raw_output,
        "error": result.error,
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {"total": total_s},
        "completion_tokens": meta.get("usage", {}).get("completion_tokens", 0),
        "metrics": _field_metrics(result.fields),
    }


def _side_summary(rows: list[dict]) -> dict:
    counts = {
        key: sum(row["metrics"]["counts"][key] for row in rows)
        for key in CAPTION_FIELD_KEYS
    }
    return {
        "success": sum(row["status"] == "ok" for row in rows),
        "timing_s": _stats([row["timings_s"]["total"] for row in rows]),
        "completion_tokens_avg": statistics.mean(
            row["completion_tokens"] for row in rows
        ),
        "field_items_avg": statistics.mean(
            row["metrics"]["total_items"] for row in rows
        ),
        "field_counts_avg": {
            key: value / len(rows) for key, value in counts.items()
        },
        "missing_field_failures": [
            {"missing": row["missing_fields"], "raw": (row["raw_output"] or "")[:200]}
            for row in rows
            if row["status"] != "ok" and row["missing_fields"]
        ],
        "other_failures": sum(
            row["status"] != "ok" and not row["missing_fields"] for row in rows
        ),
    }


def render_report(summary: dict) -> str:
    md, js = summary["markdown"], summary["json"]
    n = summary["caption_count"]
    lines = [
        "# Stage-two: fixed Markdown vs schema-driven JSON (default profile)",
        "",
        f"- Model: {summary['model_id']}",
        f"- Fixed captions: {n}（stage-1 未重跑；执行顺序逐条交替）",
        "",
        "| Metric | Markdown baseline | JSON candidate |",
        "|---|---:|---:|",
        f"| Success | {md['success']}/{n} | {js['success']}/{n} |",
        f"| Missing-field failures | {len(md['missing_field_failures'])} | {len(js['missing_field_failures'])} |",
        f"| Other failures (parse) | {md['other_failures']} | {js['other_failures']} |",
        f"| Avg time | {md['timing_s']['avg']:.3f}s | {js['timing_s']['avg']:.3f}s |",
        f"| P95 time | {md['timing_s']['p95']:.3f}s | {js['timing_s']['p95']:.3f}s |",
        f"| Completion tokens/caption | {md['completion_tokens_avg']:.1f} | {js['completion_tokens_avg']:.1f} |",
        f"| Field items/caption | {md['field_items_avg']:.2f} | {js['field_items_avg']:.2f} |",
        "",
        "## Average items by field",
        "",
        "| Field | Markdown | JSON |",
        "|---|---:|---:|",
    ]
    for key in CAPTION_FIELD_KEYS:
        lines.append(
            f"| {key} | {md['field_counts_avg'][key]:.2f} | "
            f"{js['field_counts_avg'][key]:.2f} |"
        )
    for side, label in (("markdown", "Markdown"), ("json", "JSON")):
        failures = summary[side]["missing_field_failures"]
        if failures:
            lines += ["", f"## {label} missing-field failures", ""]
            for failure in failures:
                lines.append(f"- missing={failure['missing']} raw=`{failure['raw']}`")
    return "\n".join(lines) + "\n"


async def main(limit: int) -> None:
    client = MlXVlmClient()
    model_id = await client._get_model_id()
    image_backend = MlXVlmMemoSightBackend(client=client)
    text_backend = MlXTextMemoSightBackend(client=client)
    pipeline = TwoStageMemoSightPipeline(
        image_backend=image_backend,
        text_backend=text_backend,
    )

    captions = load_preserved_captions()
    captions.extend(await load_test_data_captions(image_backend))
    if limit > 0:
        captions = captions[:limit]
    print(f"Resolved model: {model_id}; captions: {len(captions)}", flush=True)

    print("Warming markdown and json stage-two paths...", flush=True)
    warm_md = await run_markdown(text_backend, client, captions[0]["caption"])
    warm_js = await run_json(pipeline, client, captions[0]["caption"])
    if warm_js["status"] != "ok" or warm_md["status"] != "ok":
        raise RuntimeError(
            "Stage-two warmup failed; verify the configured MLX server URL "
            "before running the benchmark"
        )

    records = []
    for index, item in enumerate(captions, 1):
        print(f"[{index}/{len(captions)}] {item['source']}", flush=True)
        if index % 2:
            md = await run_markdown(text_backend, client, item["caption"])
            js = await run_json(pipeline, client, item["caption"])
            order = "markdown_first"
        else:
            js = await run_json(pipeline, client, item["caption"])
            md = await run_markdown(text_backend, client, item["caption"])
            order = "json_first"
        print(
            f"  markdown={md['status']} {md['timings_s']['total']:.3f}s "
            f"items={md['metrics']['total_items']}; "
            f"json={js['status']} {js['timings_s']['total']:.3f}s "
            f"items={js['metrics']['total_items']}",
            flush=True,
        )
        records.append(
            {
                "source": item["source"],
                "caption": item["caption"],
                "execution_order": order,
                "markdown": md,
                "json": js,
            }
        )

    summary = {
        "model_id": model_id,
        "caption_count": len(records),
        "markdown": _side_summary([record["markdown"] for record in records]),
        "json": _side_summary([record["json"] for record in records]),
    }
    OUT_JSON.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_MD.write_text(render_report(summary), encoding="utf-8")
    print(render_report(summary), flush=True)
    print(f"JSON: {OUT_JSON}", flush=True)
    print(f"Report: {OUT_MD}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 means all captions")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
```

注意：`run_json` 里 `missing_fields` 收集的是嵌套 list（每 issue 一个 list），`_side_summary` 里 truthiness 判断不受影响；如觉得丑可扁平化，但不影响指标。

- [ ] **Step 2: 冒烟运行（--limit 2）**

Run: `.venv/bin/python scripts/compare_stage2_markdown_vs_json.py --limit 2`
Expected: 两条 caption 各跑 markdown+json，exit 0，写出 `results/compare_stage2_markdown_vs_json.{json,md}` 和 `results/stage2_caption_cache.json`。若 warmup 失败说明 MLX server 不在线，先确认 `curl http://127.0.0.1:8080/v1/models`。

- [ ] **Step 3: Commit**

```bash
git add scripts/compare_stage2_markdown_vs_json.py
git commit -m "test: paired benchmark for markdown vs JSON stage-two extraction"
```

（`results/` 产物不入库——先确认 `.gitignore` 是否覆盖 `results/`；若未覆盖，产物也先不 add。）

---

### Task 5: 全量基准运行与效果判定

**Files:**
- Produces: `results/compare_stage2_markdown_vs_json.json`、`.md`、`results/stage2_caption_cache.json`

- [ ] **Step 1: 全量运行（约 120 条 caption × 2 侧，加 90 帧 caption 生成，预计 8–15 分钟）**

Run（后台）: `.venv/bin/python scripts/compare_stage2_markdown_vs_json.py`
Expected: exit 0；报告写出。

- [ ] **Step 2: 判定**

读 `results/compare_stage2_markdown_vs_json.md`：

- JSON 侧 success 数 > Markdown 侧（基线预期有缺字段失败）→ 有效提升；
- JSON 侧 field items/caption 下降超过 10% → 记录为质量回退，需在总结中如实说明；
- 把结论（success 对比、耗时、tokens、字段丰富度、失败样本）汇总给用户。

- [ ] **Step 3: Commit 报告（如 `.gitignore` 未忽略 results/）**

```bash
git add results/compare_stage2_markdown_vs_json.md
git commit -m "docs: markdown vs JSON stage-two benchmark report"
```

---

### Task 6: 文档同步与最终回归

**Files:**
- Modify: `README.md:288-289`、`README.zh-CN.md:275-277`
- Modify: `memosight/two_stage.py` docstring 已在 Task 3 完成

- [ ] **Step 1: 更新 README**

`README.md` line 288-289：

```markdown
Stage two renders schema-driven JSON for all profiles; the default profile
uses a caption-less fields schema (caption is pinned from stage one).
```

`README.zh-CN.md` line 275-277：

```markdown
第二阶段对所有 profile 都渲染 schema 驱动的 JSON；默认 profile 使用
不含 caption 的字段 schema（caption 由第一阶段钉死）。
```

- [ ] **Step 2: 全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add README.md README.zh-CN.md
git commit -m "docs: describe schema-driven JSON stage two for all profiles"
```

---

## Self-Review 记录

- Spec 覆盖：spec 的 4 块（profiles schema、two_stage 切换、max_tokens、评测脚本）+ README 同步 → Task 1–6 全覆盖。
- 占位符：无 TBD/TODO；所有代码步骤含完整代码。
- 类型一致：`PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA`（Task 1 产出 → Task 3/测试消费）；`prompt.max_tokens == 224`（Task 2 产出 → Task 3 测试断言消费）；`extract_fields` 返回 `MemoSightFieldExtractionResult`（Task 4 消费其 `.status/.fields/.raw_output/.validation.issues/.usage`）。
- 已知取舍：Task 4 的 `missing_fields` 为嵌套 list，仅用于报告展示，不影响判定指标。

---

## 迭代记录（2026-09-03，首轮基准后）

首轮基准（120 条固定 caption，配对交替）：Markdown 99/120 ok，JSON 68/120 ok。
JSON 失败 52 条中 50 条为 max_tokens=224 截断（模型模仿 prompt 中的
pretty-print 示例输出带缩进 JSON，约 454 字符处被截断），缺字段失败仅 2 条
（vs Markdown 21 条）。结论：schema-driven JSON 确实消灭了丢字段故障模式，
但 token 预算不足引入更严重的截断故障。

**Task 4b（插入，用户批准）**：紧凑 JSON 迭代

1. `memosight/config/default_prompts.json`：zh/en `caption_json_stage`
   `max_tokens` 224 → 384；rules 各加一条：
   - zh：`- 输出单行紧凑 JSON，不要缩进、换行或多余空白。`
   - en：`- Output compact single-line JSON: no indentation, line breaks, or extra whitespace.`
2. `memosight/prompts.py`：`build_caption_structured_extraction_prompt` 的示例
   改为紧凑单行渲染（新增 `_render_example_object_compact` /
   `_compact_placeholder_for` 辅助函数；`_render_example_object` 保持供
   一段式 `build_prompt` 使用，不动）。
3. 测试：`max_tokens == 224` 断言全部改 384（`tests/test_memosight_prompts.py`、
   `tests/test_two_stage_pipeline.py`）；新增紧凑示例断言（CUSTOM_SCHEMA 的
   示例必须是单行 `{"product_type": "...", "brand_visible": true, "mood": "warm", "dominant_colors": []}`，
   且 zh prompt 含"紧凑"）。
4. 重跑 `.venv/bin/python scripts/compare_stage2_markdown_vs_json.py`
   （caption 缓存已就绪，stage-1 不重跑），按 Task 5 的判定标准重新评估。

**Task 5 判定（第二轮，2026-09-03）**：效果提升确认。

第二轮基准（120 条固定 caption，配对交替，stage-1 未重跑；模型
`/Users/kanzhiwu/Workspace/memobrain/models/Qwen3.5-2B-MLX-4bit`）：

| Metric | Markdown baseline | JSON candidate |
|---|---:|---:|
| Success | 99/120 | **120/120** |
| Missing-field failures | 21 | 0 |
| Other failures (parse) | 0 | 0 |
| Avg time | 2.235s | 5.403s |
| P95 time | 3.141s | 7.592s |
| Field items/caption | 16.18 | 24.39 |

- success 对比：JSON 120/120 > Markdown 99/120 → 有效提升；
  首轮的 50 条 max_tokens 截断故障全部消失（紧凑单行输出 + 384 预算生效）。
- 字段丰富度：JSON field items/caption 24.39 vs 基线 16.18（+51%），非下降，
  无质量回退（people 略降 1.99→1.35，其余字段均升，search_tags 2.82→5.77）。
- 代价：JSON 耗时约为 Markdown 的 2.4 倍（avg 5.40s vs 2.24s），输出更丰富、
  且为 7 字段齐全的合法 JSON，属可接受取舍。
- completion tokens 两侧均为 0.0（后端未回填 usage），该项无法对比。

结论：默认 profile stage-2 切换 schema-driven JSON（caption-less、紧凑单行、
max_tokens=384）在 2B 模型上确认提升，特征分支可合入 main。
最终回归：`.venv/bin/python -m pytest tests/ -q` → 161 passed。

**A1 迭代（2026-09-03，用户决定速度优先，默认回退 Markdown）**：

JSON stage-2 的完整性优势确认（120/120 vs Markdown 99/120），但其文本调用
约 3.3s（Markdown 约 1.3–1.9s），两段式 JSON 合计 ≈ 一段式，快路径优势消失。
逐项验证结论：

1. 加预算无效：Markdown @192 与 @512 输出字节级一致（120/120 相同），
   缺字段是模型在松散文本格式下提前停笔/重复行，不是 token 截断。
2. 收尾契约有效：新 Markdown 模板要求“恰好 7 行、每字段名恰好一次、以
   `**search_tags:**` 行结尾、禁止提前停止”（另 max_tokens 192→256），
   全量 120 条 fixed caption 上 ok=120/120（旧模板 99/120），文本 avg ~1.8s、
   输出 ~159 字符（JSON 路径 ~3.3s / 460 字符）。
3. 决定：默认 profile 两段式 stage-2 回退为 Markdown（收尾契约模板）；
   自定义/命名 profile 维持 schema 驱动 JSON。

**A1 全量配对基准（2026-09-03，120 条 fixed caption，2B-4bit）**：
Markdown(契约 v2) 与 JSON 均 120/120 ok、0 缺字段；文本 avg 2.096s vs 5.522s
（p95 3.309s vs 7.484s）；输出约 7.9 vs 24.4 项（md 以逗号计项、空格分隔短语
未计入）。结论：默认 stage-2 用 Markdown 契约模板后，完整性与 JSON 持平、
耗时约为 JSON 的 38%。HTML 对比页由 scripts/make_stage2_markdown_vs_json_review.py
生成到 results/（不入库）。
