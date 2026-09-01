"""Build a side-by-side review page for one-stage JSON vs two-stage v5.

Merges the one-stage results from the preserved one-vs-two-stage benchmark
with the v5 stage-two results from the fixed-caption prompt benchmark (same
20 frames), adapts them into the shape the side-by-side HTML template
expects, and reuses ``make_side_by_side_review.HTML`` with relabeled panels.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_side_by_side_review import HTML

ONE_STAGE_SOURCE = Path("results/compare_one_stage_vs_two_stage_736x416.json")
V5_SOURCE = Path("results/compare_stage2_prompt_v1_vs_v5_736x416.json")
FRAMES_DIR = Path("frames_sample_736x416")
OUTPUT = Path("results/one_stage_vs_v5_review.html")

LABEL_REPLACEMENTS = [
    ("<span>单阶段 <strong", "<span>一段式 <strong"),
    ("<span>两阶段 <strong", "<span>两段式 v5 <strong"),
    ("平均提速", "v5 耗时变化"),
    ("单阶段 JSON", "一段式 JSON（现网）"),
    ("两阶段 Caption → Fields", "两段式 v5（caption 约束）"),
    ("<span>两阶段</span>", "<span>两段式 v5</span>"),
    ("两阶段拆分：Caption", "v5 拆分：字段模型"),
    (
        " · 执行顺序 ${record.execution_order === 'one_stage_first' ? '单阶段优先' : '两阶段优先'}",
        "",
    ),
]


def main() -> None:
    one_stage_source = json.loads(ONE_STAGE_SOURCE.read_text(encoding="utf-8"))
    v5_source = json.loads(V5_SOURCE.read_text(encoding="utf-8"))
    v5_by_frame = {record["frame"]: record for record in v5_source["records"]}

    records = []
    for record in one_stage_source["records"]:
        frame = record["frame"]
        v5_record = v5_by_frame[frame]
        v5 = v5_record["v5"]
        one = record["one_stage"]
        records.append(
            {
                "frame": frame,
                "frame_path": str(FRAMES_DIR / frame),
                "timestamp_s": record["timestamp_s"],
                "execution_order": "one_stage_first",
                "one_stage": {
                    "status": one["status"],
                    "observation": one["observation"],
                    "raw_output": one["raw_output"],
                    "error": one["error"],
                    "issues": one["issues"],
                    "timings_s": {"total": one["timings_s"]["total"]},
                },
                "two_stage": {
                    "status": v5["status"],
                    "observation": {"caption": v5_record["caption"], **v5["fields"]},
                    "caption_raw_output": v5_record["caption"],
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
        )

    payload = {
        "summary": {
            "model_id": v5_source["summary"]["model_id"],
            "one_stage": {"avg_s": one_stage_source["summary"]["one_stage"]["avg_s"]},
            "two_stage": {"avg_s": v5_source["summary"]["v5"]["timing_s"]["avg"]},
            "two_stage_vs_one_stage_pct": (
                v5_source["summary"]["v5"]["timing_s"]["avg"]
                / one_stage_source["summary"]["one_stage"]["avg_s"]
                - 1
            )
            * 100,
        },
        "records": records,
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
