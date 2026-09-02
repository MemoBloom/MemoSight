"""Run one-stage vs two-stage comparison on the squat_tutorial frames.

Uses the custom squat schema and the already-generated prompt plan from
examples/squat_schema.json + examples/squat_prompt_plan.json (verified to
reproduce examples/squat_prompts.md byte-for-byte). Two-stage stage one uses
the bundled caption prompt; stage two uses the schema-driven caption->JSON
prompt.

Writes results/squat_compare_one_vs_two.json.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_test_data_compare import (  # noqa: E402
    TimedImageBackend,
    TimedTextBackend,
    build_video_summary,
    _avg,
    _video_duration_s,
)

from memosight import (  # noqa: E402
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient  # noqa: E402

FRAMES_DIR = Path("test_data/squat_tutorial")
SCHEMA_PATH = Path("examples/squat_schema.json")
PLAN_PATH = Path("examples/squat_prompt_plan.json")
OUT_PATH = Path("results/squat_compare_one_vs_two.json")
LANGUAGE = "zh"


def _request(frame: Path, schema: dict, plan: dict) -> MemoSightRequest:
    return MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(frame)),
        asset_id=frame.stem,
        language=LANGUAGE,
        profile="custom",
        output_schema=schema,
        prompt_plan=plan,
    )


async def run_one_stage(pipeline, backend, frame, schema, plan) -> dict:
    call_index = len(backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame, schema, plan))
    total_s = time.perf_counter() - started
    calls = backend.calls[call_index:]
    return {
        "status": result.status,
        "observation": result.observation,
        "raw_output": result.raw_output,
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "attempts": result.usage.get("attempts"),
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {
            "model": sum(call["duration_s"] for call in calls),
            "non_model": max(0.0, total_s - sum(call["duration_s"] for call in calls)),
            "total": total_s,
        },
    }


async def run_two_stage(pipeline, image_backend, text_backend, frame, schema, plan) -> dict:
    image_index = len(image_backend.calls)
    text_index = len(text_backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame, schema, plan))
    total_s = time.perf_counter() - started
    caption_model_s = sum(
        call["duration_s"] for call in image_backend.calls[image_index:]
    )
    field_model_s = sum(call["duration_s"] for call in text_backend.calls[text_index:])
    return {
        "status": result.status,
        "observation": result.observation,
        "caption_raw_output": result.caption_raw_output,
        "structured_raw_output": result.structured_raw_output,
        "error": result.error,
        "failed_stage": result.failed_stage,
        "issues": [issue.message for issue in result.validation.issues],
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {
            "caption_model": caption_model_s,
            "field_model": field_model_s,
            "model_total": caption_model_s + field_model_s,
            "postprocess": result.usage.get("postprocess_duration_s", 0.0),
            "non_model": max(0.0, total_s - caption_model_s - field_model_s),
            "total": total_s,
        },
    }


async def main() -> None:
    frames = sorted(FRAMES_DIR.glob("*.jpg"))
    if not frames:
        raise RuntimeError(f"No frames found in {FRAMES_DIR}")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))

    client = MlXVlmClient()
    model_id = await client._get_model_id()
    print(f"Resolved model: {model_id}", flush=True)

    one_backend = TimedImageBackend(MlXVlmMemoSightBackend(client=client))
    two_image_backend = TimedImageBackend(MlXVlmMemoSightBackend(client=client))
    two_text_backend = TimedTextBackend(MlXTextMemoSightBackend(client=client))
    one_pipeline = MemoSightPipeline(one_backend, max_repair_attempts=1)
    two_pipeline = TwoStageMemoSightPipeline(
        two_image_backend,
        two_text_backend,
    )

    print(f"Warming both paths with {frames[0]}...", flush=True)
    await run_one_stage(one_pipeline, one_backend, frames[0], schema, plan)
    await run_two_stage(two_pipeline, two_image_backend, two_text_backend, frames[0], schema, plan)

    duration_s = _video_duration_s(FRAMES_DIR)
    print(f"\n== {FRAMES_DIR.name}: {len(frames)} frames ==", flush=True)
    records = []
    for index, frame in enumerate(frames, 1):
        frame_idx = int(frame.stem[1:])
        timestamp_s = (
            (frame_idx - 1) / (len(frames) - 1) * duration_s
            if duration_s and len(frames) > 1
            else 0.0
        )
        if index % 2:
            one = await run_one_stage(one_pipeline, one_backend, frame, schema, plan)
            two = await run_two_stage(
                two_pipeline, two_image_backend, two_text_backend, frame, schema, plan
            )
            execution_order = "one_stage_first"
        else:
            two = await run_two_stage(
                two_pipeline, two_image_backend, two_text_backend, frame, schema, plan
            )
            one = await run_one_stage(one_pipeline, one_backend, frame, schema, plan)
            execution_order = "two_stage_first"
        print(
            f"  [{index}/{len(frames)}] {frame.name} "
            f"one={one['status']} {one['timings_s']['total']:.3f}s; "
            f"two={two['status']} {two['timings_s']['total']:.3f}s",
            flush=True,
        )
        records.append(
            {
                "frame": frame.name,
                "frame_path": str(frame),
                "frame_index": frame_idx,
                "timestamp_s": timestamp_s,
                "execution_order": execution_order,
                "one_stage": one,
                "two_stage": two,
            }
        )

    summary = build_video_summary(records)
    payload = {
        "model_id": model_id,
        "video": FRAMES_DIR.name,
        "duration_s": duration_s,
        "schema": schema,
        "prompt_plan_source": str(PLAN_PATH),
        "summary": summary,
        "records": records,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT_PATH}", flush=True)
    print(
        f"one {summary['one_stage_ok']}/{summary['frame_count']} ok "
        f"avg {summary['one_stage']['avg_s']:.3f}s; "
        f"two {summary['two_stage_ok']}/{summary['frame_count']} ok "
        f"(+{summary['two_stage_partial']} partial) "
        f"avg {summary['two_stage']['avg_s']:.3f}s "
        f"({summary['two_stage_vs_one_stage_pct']:+.1f}%)",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
