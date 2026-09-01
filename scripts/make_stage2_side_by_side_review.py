"""Build a side-by-side review page for stage-two prompt v1 vs v5.

Adapts the paired benchmark records (fixed captions, v1/v5 fields) into the
shape the side-by-side HTML template expects, relabels the one-stage/two-stage
framing as v1/v5, and reuses ``make_side_by_side_review.HTML`` unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_side_by_side_review import HTML

SOURCE = Path("results/compare_stage2_prompt_v1_vs_v5_736x416.json")
TIMESTAMPS = Path("results/compare_one_stage_vs_two_stage_736x416.json")
FRAMES_DIR = Path("frames_sample_736x416")
OUTPUT = Path("results/stage2_v1_vs_v5_review.html")

LABEL_REPLACEMENTS = [
    ("<span>单阶段 <strong", "<span>v1 <strong"),
    ("<span>两阶段 <strong", "<span>v5 <strong"),
    ("平均提速", "v5 耗时变化"),
    ("单阶段 JSON", "v1（线上默认）"),
    ("两阶段 Caption → Fields", "v5（caption 约束）"),
    ("<span>两阶段</span>", "<span>v5</span>"),
    ("两阶段拆分：Caption", "v5 拆分：字段模型"),
    ("单阶段优先", "v1 优先"),
    ("两阶段优先", "v5 优先"),
]


def _adapt_record(record: dict, timestamps: dict[str, float]) -> dict:
    caption = record["caption"]
    v1 = record["v1"]
    v5 = record["v5"]
    return {
        "frame": record["frame"],
        "frame_path": str(FRAMES_DIR / record["frame"]),
        "timestamp_s": timestamps.get(record["frame"], 0.0),
        "execution_order": (
            "one_stage_first" if record["execution_order"] == "v1_first" else "two_stage_first"
        ),
        "one_stage": {
            "status": v1["status"],
            "observation": {"caption": caption, **v1["fields"]},
            "raw_output": v1["raw_output"],
            "error": v1["error"],
            "issues": v1["issues"],
            "timings_s": {"total": v1["timings_s"]["total"]},
        },
        "two_stage": {
            "status": v5["status"],
            "observation": {"caption": caption, **v5["fields"]},
            "caption_raw_output": caption,
            "structured_raw_output": v5["raw_output"],
            "error": v5["error"],
            "issues": v5["issues"],
            "timings_s": {
                "total": v5["timings_s"]["total"],
                "caption_model": 0.0,
                "field_model": v5["timings_s"]["model"],
                "postprocess": v5["timings_s"]["postprocess"],
            },
        },
    }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    timestamps = {
        record["frame"]: record["timestamp_s"]
        for record in json.loads(TIMESTAMPS.read_text(encoding="utf-8"))["records"]
    }
    summary = source["summary"]
    payload = {
        "summary": {
            "model_id": summary["model_id"],
            "one_stage": {"avg_s": summary["v1"]["timing_s"]["avg"]},
            "two_stage": {"avg_s": summary["v5"]["timing_s"]["avg"]},
            "two_stage_vs_one_stage_pct": summary["v5_vs_v1"]["time_pct"],
        },
        "records": [_adapt_record(record, timestamps) for record in source["records"]],
    }
    html = HTML
    for old, new in LABEL_REPLACEMENTS:
        if old not in html:
            raise RuntimeError(f"label not found in template: {old}")
        html = html.replace(old, new)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    OUTPUT.write_text(html.replace("__DATA__", embedded), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
