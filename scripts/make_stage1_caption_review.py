"""Generate the v1/v3 caption review by reusing the existing review page."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from make_side_by_side_review import HTML

SOURCE = Path("results/compare_stage1_caption_v1_vs_v3_736x416.json")
TIMESTAMP_SOURCE = Path("results/compare_one_stage_vs_two_stage_736x416.json")
OUTPUTS = {
    "stage1-v1-v3": Path("results/stage1_caption_v1_vs_v3_review.html"),
    "one-stage-v3": Path("results/one_stage_vs_two_stage_v3_review.html"),
}
FIELD_KEYS = (
    "scene_labels",
    "people",
    "actions",
    "objects",
    "lighting",
    "mood",
    "search_tags",
)


def _observation(result: dict) -> dict:
    return {"caption": result["caption"], **result["fields"]}


def _v1_result(result: dict) -> dict:
    return {
        "status": result["status"],
        "observation": _observation(result),
        "raw_output": result["structured_raw_output"],
        "error": result["error"],
        "issues": result["issues"],
        "timings_s": {
            "total": result["timings_s"]["total"],
        },
    }


def _v3_result(result: dict) -> dict:
    return {
        "status": result["status"],
        "observation": _observation(result),
        "caption_raw_output": result["caption"],
        "structured_raw_output": result["structured_raw_output"],
        "error": result["error"],
        "issues": result["issues"],
        "timings_s": {
            "caption_model": result["timings_s"]["caption"],
            "field_model": result["timings_s"]["field"],
            "postprocess": 0.0,
            "total": result["timings_s"]["total"],
        },
    }


def _adapt_stage1_payload(source: dict, timestamp_source: dict) -> dict:
    timestamps = {
        row["frame"]: row.get("timestamp_s", 0.0)
        for row in timestamp_source["records"]
    }
    summary = source["summary"]
    records = []
    for row in source["records"]:
        records.append(
            {
                "frame": row["frame"],
                "frame_path": row["frame_path"],
                "timestamp_s": timestamps.get(row["frame"], 0.0),
                "execution_order": (
                    "one_stage_first"
                    if row["execution_order"] == "v1_first"
                    else "two_stage_first"
                ),
                "one_stage": _v1_result(row["v1"]),
                "two_stage": _v3_result(row["v3"]),
            }
        )
    return {
        "summary": {
            "model_id": summary["model_id"],
            "one_stage": {"avg_s": summary["v1"]["total_timing_s"]["avg"]},
            "two_stage": {"avg_s": summary["v3"]["total_timing_s"]["avg"]},
            # The reused header's third value is repurposed as field-item gain.
            "two_stage_vs_one_stage_pct": summary["v3_vs_v1"]["field_items_pct"],
        },
        "records": records,
    }


def _field_item_count(observation: dict | None) -> int:
    observation = observation or {}
    return sum(len(observation.get(key, [])) for key in FIELD_KEYS)


def _adapt_one_stage_v3_payload(stage1_source: dict, original_source: dict) -> dict:
    v3_by_frame = {row["frame"]: row["v3"] for row in stage1_source["records"]}
    records = []
    one_stage_items = []
    for row in original_source["records"]:
        v3 = v3_by_frame[row["frame"]]
        one_stage_items.append(_field_item_count(row["one_stage"].get("observation")))
        records.append(
            {
                "frame": row["frame"],
                "frame_path": row["frame_path"],
                "timestamp_s": row.get("timestamp_s", 0.0),
                "execution_order": "independent_benchmarks",
                "one_stage": row["one_stage"],
                "two_stage": _v3_result(v3),
            }
        )
    v3_summary = stage1_source["summary"]["v3"]
    one_stage_avg_items = sum(one_stage_items) / len(one_stage_items)
    field_change_pct = (
        v3_summary["field_items_avg"] / one_stage_avg_items - 1
    ) * 100
    return {
        "summary": {
            "model_id": stage1_source["summary"]["model_id"],
            "one_stage": {
                "avg_s": original_source["summary"]["one_stage"]["avg_s"]
            },
            "two_stage": {"avg_s": v3_summary["total_timing_s"]["avg"]},
            "two_stage_vs_one_stage_pct": field_change_pct,
        },
        "records": records,
    }


def _relabel(template: str, mode: str) -> str:
    if mode == "stage1-v1-v3":
        replacements = {
            "MemoSight · 标注结果对比": "MemoSight · Caption Prompt v1 / v3 对比",
            "单阶段 <strong": "Prompt v1 <strong",
            "两阶段 <strong": "Prompt v3 <strong",
            "平均提速": "字段增益",
            "单阶段 JSON": "Prompt v1 · 50–80 字",
            "<span>两阶段</span>": "<span>Prompt v3</span>",
            "两阶段 Caption → Fields": "Prompt v3 · 高密度单段",
            "两阶段拆分：": "v3 拆分：",
            "单阶段优先": "v1 优先",
            "两阶段优先": "v3 优先",
            "两种方案均成功": "v1 / v3 均成功",
        }
    else:
        replacements = {
            "MemoSight · 标注结果对比": "MemoSight · 一段式 JSON / 两阶段 v3 对比",
            "单阶段 <strong": "一段式 <strong",
            "两阶段 <strong": "两阶段 v3 <strong",
            "平均提速": "v3 字段变化",
            "单阶段 JSON": "一段式 JSON",
            "<span>两阶段</span>": "<span>两阶段 v3</span>",
            "两阶段 Caption → Fields": "两阶段 · Caption v3 → Fields",
            "两阶段拆分：": "v3 两阶段拆分：",
            "两种方案均成功": "一段式 / v3 均成功",
            "${Math.abs(summary.two_stage_vs_one_stage_pct).toFixed(1)}%": "${summary.two_stage_vs_one_stage_pct.toFixed(1)}%",
            ".summary-line .improvement { color: var(--green); }": ".summary-line .improvement { color: var(--amber); }",
            "$('timestamp').textContent = `视频时间 ${record.timestamp_s.toFixed(1)} s · 执行顺序 ${record.execution_order === 'one_stage_first' ? '单阶段优先' : '两阶段优先'}`;": "$('timestamp').textContent = `视频时间 ${record.timestamp_s.toFixed(1)} s · 结果来自独立基准`;",
        }
    for old, new in replacements.items():
        template = template.replace(old, new)
    return template


def main(mode: str) -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    timestamp_source = json.loads(TIMESTAMP_SOURCE.read_text(encoding="utf-8"))
    if mode == "stage1-v1-v3":
        payload = _adapt_stage1_payload(source, timestamp_source)
    else:
        payload = _adapt_one_stage_v3_payload(source, timestamp_source)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    output = OUTPUTS[mode]
    output.write_text(
        _relabel(HTML, mode).replace("__DATA__", embedded), encoding="utf-8"
    )
    print(f"Wrote {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--comparison",
        choices=tuple(OUTPUTS),
        default="stage1-v1-v3",
    )
    args = parser.parse_args()
    main(args.comparison)
