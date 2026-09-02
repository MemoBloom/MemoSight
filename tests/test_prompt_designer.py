"""Tests for schema-to-prompt planning and sanitization."""
from __future__ import annotations

import pytest

from memosight import (
    MemoSightPromptPlan,
    MockMemoSightTextBackend,
    build_prompt_plan_design_prompt,
    design_prompt_plan,
    heuristic_prompt_plan,
    infer_output_schema_from_example,
    prompt_plan_from_model_output,
    resolve_profile,
)


SQUAT_EXAMPLE = {
    "exercise_type": "squat",
    "visible_body_parts": ["knees", "hips", "back", "feet"],
    "pose_phase": "bottom",
    "alignment_issues": ["knees_caving_in", "rounded_back"],
    "equipment_visible": ["barbell"],
    "safety_risk": True,
    "coaching_summary": "膝盖有内扣，背部略弓，建议降低重量并保持脊柱中立。",
}


SQUAT_SCHEMA = {
    "type": "object",
    "properties": {
        "exercise_type": {
            "type": "string",
            "enum": [
                "squat",
                "deadlift",
                "bench_press",
                "push_up",
                "plank",
                "lunge",
                "other",
            ],
            "description": "图片中可见的健身动作类型。",
        },
        "visible_body_parts": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
            "description": "动作判断中清晰可见的身体部位。",
        },
        "pose_phase": {
            "type": "string",
            "enum": ["setup", "top", "middle", "bottom", "unknown"],
            "description": "当前动作处于哪个阶段。",
        },
        "alignment_issues": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 8,
            "description": "从可见姿态中观察到的动作对齐问题。",
        },
        "equipment_visible": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 6,
            "description": "图片中清晰可见的健身器械。",
        },
        "safety_risk": {
            "type": "boolean",
            "description": "是否存在明显可见的动作安全风险。",
        },
        "coaching_summary": {
            "type": "string",
            "description": "基于可见姿态给出的简短动作建议。",
        },
    },
    "required": [
        "exercise_type",
        "pose_phase",
        "safety_risk",
        "coaching_summary",
    ],
}


def test_infer_output_schema_from_json_example():
    schema = infer_output_schema_from_example(SQUAT_EXAMPLE)

    assert schema["type"] == "object"
    assert schema["required"] == list(SQUAT_EXAMPLE)
    assert schema["properties"]["exercise_type"]["type"] == "string"
    assert schema["properties"]["visible_body_parts"]["type"] == "array"
    assert schema["properties"]["visible_body_parts"]["maxItems"] == 4
    assert schema["properties"]["safety_risk"]["type"] == "boolean"


def test_prompt_plan_request_covers_schema_fields():
    profile = resolve_profile(output_schema=SQUAT_SCHEMA)
    prompt = build_prompt_plan_design_prompt(
        profile,
        domain_hint="健身动作姿态分析，用于深蹲教学视频抽帧。",
        output_example=SQUAT_EXAMPLE,
    )

    assert prompt.schema_name == "custom_prompt_plan_request"
    assert "field_guidance 必须覆盖每个 schema 字段" in prompt.text
    assert "exercise_type" in prompt.text
    assert "alignment_issues" in prompt.text
    assert "不得要求输出 JSON 数组" in prompt.text
    assert "期望输出样例" in prompt.text
    assert "knees_caving_in" in prompt.text
    assert prompt.max_tokens == 900


def test_model_prompt_plan_output_is_sanitized_against_schema():
    profile = resolve_profile(output_schema=SQUAT_SCHEMA)
    raw = """{
      "task_summary": "深蹲动作姿态分析",
      "field_guidance": "exercise_type: 根据可见动作判断。 pose_phase: 判断动作阶段。 safety_risk: 明显危险时为 true。",
      "negative_rules": [
        "不要输出 JSON 数组",
        "不要推断不可见关节角度",
        "颜色必须用十六进制",
        "不要做医学诊断"
      ],
      "output_rules": [
        "输出严格 JSON 对象",
        "task_summary 不超过 60 字",
        "缺失内容用 unknown",
        "数组遵守 maxItems"
      ],
      "final_prompt": "你是 Prompt Designer，请设计 prompt 并限制 final_prompt 不超过 450 字。"
    }"""

    plan = prompt_plan_from_model_output(raw, profile)

    assert isinstance(plan, MemoSightPromptPlan)
    assert set(plan.field_guidance) == set(SQUAT_SCHEMA["properties"])
    assert plan.field_guidance["exercise_type"] == "根据可见动作判断"
    assert plan.field_guidance["alignment_issues"]
    assert "不要输出 JSON 数组" not in plan.negative_rules
    assert all("十六进制" not in rule for rule in plan.negative_rules)
    assert all("unknown" not in rule.lower() for rule in plan.output_rules)
    assert all("task_summary" not in rule for rule in plan.output_rules)
    assert "Prompt Designer" not in plan.final_prompt
    assert "结合字段判断策略" in plan.final_prompt
    assert not plan.task_summary.startswith("设计")
    assert plan.schema_hash


@pytest.mark.asyncio
async def test_design_prompt_plan_uses_backend_and_sanitizes():
    profile = resolve_profile(output_schema=SQUAT_SCHEMA)
    backend = MockMemoSightTextBackend(
        response='{"task_summary": "深蹲分析", "field_guidance": {}, '
        '"negative_rules": [], "output_rules": [], "final_prompt": ""}'
    )

    plan = await design_prompt_plan(
        profile,
        backend,
        domain_hint="深蹲教学视频抽帧",
        output_example=SQUAT_EXAMPLE,
    )

    assert len(backend.calls) == 1
    assert plan.source == "mock_text"
    assert plan.field_guidance["pose_phase"]
    assert plan.final_prompt


def test_heuristic_prompt_plan_is_schema_aligned():
    profile = resolve_profile(output_schema=SQUAT_SCHEMA)
    plan = heuristic_prompt_plan(profile)

    assert set(plan.field_guidance) == set(SQUAT_SCHEMA["properties"])
    assert "squat/deadlift" in plan.field_guidance["exercise_type"]
    assert "最多 8 项" in plan.field_guidance["visible_body_parts"]
