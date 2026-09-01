"""Compare current one-stage JSON with two-stage caption + Markdown fields.

Both variants use the same model, 736x416 inputs, generation configuration,
warm-up policy, and alternating execution order. Results include per-stage
model time and non-model processing time.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient

FRAMES_DIR = Path("frames_sample_736x416")
OUT_PATH = Path("results/compare_one_stage_vs_two_stage_736x416.json")
SUMMARY_PATH = Path("results/compare_one_stage_vs_two_stage_736x416.md")
LANGUAGE = "zh"


class TimedImageBackend:
    def __init__(self, backend) -> None:
        self._backend = backend
        self.name = backend.name
        self.version = backend.version
        self.calls: list[dict] = []

    async def describe(self, image, prompt) -> str:
        started = time.perf_counter()
        try:
            return await self._backend.describe(image, prompt)
        finally:
            self.calls.append(
                {
                    "duration_s": time.perf_counter() - started,
                    **dict(getattr(self._backend._get_client(), "_last_response_meta", {}) or {}),
                }
            )


class TimedTextBackend:
    def __init__(self, backend) -> None:
        self._backend = backend
        self.name = backend.name
        self.version = backend.version
        self.calls: list[dict] = []

    async def complete(self, prompt) -> str:
        started = time.perf_counter()
        try:
            return await self._backend.complete(prompt)
        finally:
            self.calls.append(
                {
                    "duration_s": time.perf_counter() - started,
                    **dict(getattr(self._backend._get_client(), "_last_response_meta", {}) or {}),
                }
            )


def _request(frame: Path) -> MemoSightRequest:
    return MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(frame)),
        asset_id=frame.stem,
        language=LANGUAGE,
    )


async def run_one_stage(pipeline, backend, frame: Path) -> dict:
    call_index = len(backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame))
    total_s = time.perf_counter() - started
    calls = backend.calls[call_index:]
    model_s = sum(call["duration_s"] for call in calls)
    return {
        "status": result.status,
        "observation": result.observation,
        "raw_output": result.raw_output,
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "attempts": result.usage.get("attempts"),
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {
            "model": model_s,
            "non_model": max(0.0, total_s - model_s),
            "total": total_s,
        },
        "model_calls": calls,
    }


async def run_two_stage(pipeline, image_backend, text_backend, frame: Path) -> dict:
    image_index = len(image_backend.calls)
    text_index = len(text_backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame))
    total_s = time.perf_counter() - started
    image_calls = image_backend.calls[image_index:]
    text_calls = text_backend.calls[text_index:]
    caption_model_s = sum(call["duration_s"] for call in image_calls)
    field_model_s = sum(call["duration_s"] for call in text_calls)
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
        "caption_model_calls": image_calls,
        "field_model_calls": text_calls,
    }


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "total_s": sum(values),
        "avg_s": statistics.mean(values),
        "p50_s": statistics.median(values),
        "p95_s": ordered[p95_index],
        "min_s": min(values),
        "max_s": max(values),
    }


def build_summary(records: list[dict]) -> dict:
    one_total = [row["one_stage"]["timings_s"]["total"] for row in records]
    two_total = [row["two_stage"]["timings_s"]["total"] for row in records]
    one_model = sum(row["one_stage"]["timings_s"]["model"] for row in records)
    two_caption = sum(
        row["two_stage"]["timings_s"]["caption_model"] for row in records
    )
    two_fields = sum(
        row["two_stage"]["timings_s"]["field_model"] for row in records
    )
    one_sum = sum(one_total)
    two_sum = sum(two_total)
    clean_records = [
        row
        for row in records
        if row["one_stage"]["status"] == "ok"
        and row["one_stage"]["attempts"] == 1
    ]
    clean_one = [row["one_stage"]["timings_s"]["total"] for row in clean_records]
    clean_two = [row["two_stage"]["timings_s"]["total"] for row in clean_records]
    caption_chars = [len(row["two_stage"]["observation"]["caption"]) for row in records]
    postprocess_total = sum(
        row["two_stage"]["timings_s"]["postprocess"] for row in records
    )
    return {
        "frame_count": len(records),
        "one_stage_ok": sum(row["one_stage"]["status"] == "ok" for row in records),
        "two_stage_ok": sum(row["two_stage"]["status"] == "ok" for row in records),
        "two_stage_partial": sum(
            row["two_stage"]["status"] == "partial" for row in records
        ),
        "one_stage": {
            **_stats(one_total),
            "model_total_s": one_model,
            "model_share_pct": one_model / one_sum * 100,
        },
        "two_stage": {
            **_stats(two_total),
            "caption_model_total_s": two_caption,
            "field_model_total_s": two_fields,
            "model_total_s": two_caption + two_fields,
            "caption_share_pct": two_caption / two_sum * 100,
            "field_share_pct": two_fields / two_sum * 100,
            "model_share_pct": (two_caption + two_fields) / two_sum * 100,
            "postprocess_total_s": postprocess_total,
            "postprocess_share_pct": postprocess_total / two_sum * 100,
            "caption_chars": {
                "min": min(caption_chars),
                "max": max(caption_chars),
                "avg": statistics.mean(caption_chars),
            },
        },
        "two_stage_vs_one_stage_pct": (two_sum / one_sum - 1) * 100,
        "two_stage_faster_frames": sum(
            row["two_stage"]["timings_s"]["total"]
            < row["one_stage"]["timings_s"]["total"]
            for row in records
        ),
        "first_attempt_paired": {
            "frame_count": len(clean_records),
            "one_stage": _stats(clean_one),
            "two_stage": _stats(clean_two),
            "two_stage_vs_one_stage_pct": (
                sum(clean_two) / sum(clean_one) - 1
            )
            * 100,
        },
    }


def render_summary(summary: dict) -> str:
    one = summary["one_stage"]
    two = summary["two_stage"]
    paired = summary["first_attempt_paired"]
    return f"""# One-stage JSON vs two-stage structured output

- Model: {summary.get('model_id', 'not recorded')}
- Input: {summary['frame_count']} frames, 736x416, alternating order after warm-up
- One-stage success: {summary['one_stage_ok']}/{summary['frame_count']}
- Two-stage success: {summary['two_stage_ok']}/{summary['frame_count']} (partial: {summary['two_stage_partial']})

| Metric | One-stage JSON | Two-stage caption + Markdown |
|---|---:|---:|
| Total | {one['total_s']:.3f}s | {two['total_s']:.3f}s |
| Average | {one['avg_s']:.3f}s | {two['avg_s']:.3f}s |
| P50 | {one['p50_s']:.3f}s | {two['p50_s']:.3f}s |
| P95 | {one['p95_s']:.3f}s | {two['p95_s']:.3f}s |
| Model share | {one['model_share_pct']:.3f}% | {two['model_share_pct']:.3f}% |

Two-stage model split: caption {two['caption_model_total_s']:.3f}s ({two['caption_share_pct']:.3f}% of total), fields {two['field_model_total_s']:.3f}s ({two['field_share_pct']:.3f}% of total).

Two-stage total time relative to one-stage: {summary['two_stage_vs_one_stage_pct']:+.2f}%.

First-attempt paired subset ({paired['frame_count']} frames): one-stage {paired['one_stage']['avg_s']:.3f}s/frame, two-stage {paired['two_stage']['avg_s']:.3f}s/frame ({paired['two_stage_vs_one_stage_pct']:+.2f}%). Two-stage was faster on {summary['two_stage_faster_frames']}/{summary['frame_count']} frames.

Two-stage post-processing: {two['postprocess_total_s']:.6f}s total ({two['postprocess_share_pct']:.5f}%). Caption length: {two['caption_chars']['avg']:.1f} characters average, {two['caption_chars']['min']}–{two['caption_chars']['max']} range.
"""


async def main() -> None:
    frames = sorted(FRAMES_DIR.glob("*.jpg"))
    if not frames:
        raise RuntimeError(f"No comparison frames found in {FRAMES_DIR}")

    client = MlXVlmClient()
    model_id = await client._get_model_id()
    print(f"Resolved model: {model_id}", flush=True)
    one_backend = TimedImageBackend(MlXVlmMemoSightBackend(client=client))
    two_image_backend = TimedImageBackend(MlXVlmMemoSightBackend(client=client))
    two_text_backend = TimedTextBackend(MlXTextMemoSightBackend(client=client))
    one_pipeline = MemoSightPipeline(one_backend, max_repair_attempts=1)
    two_pipeline = TwoStageMemoSightPipeline(two_image_backend, two_text_backend)

    print(f"Warming both paths with {frames[0].name}...", flush=True)
    await run_one_stage(one_pipeline, one_backend, frames[0])
    await run_two_stage(two_pipeline, two_image_backend, two_text_backend, frames[0])

    records = []
    for index, frame in enumerate(frames, 1):
        frame_index = int(frame.stem[1:])
        timestamp_s = (frame_index - 1) / 2.0
        print(f"[{index}/{len(frames)}] {frame.name} (t={timestamp_s:.1f}s)", flush=True)
        if index % 2:
            one = await run_one_stage(one_pipeline, one_backend, frame)
            two = await run_two_stage(
                two_pipeline, two_image_backend, two_text_backend, frame
            )
            execution_order = "one_stage_first"
        else:
            two = await run_two_stage(
                two_pipeline, two_image_backend, two_text_backend, frame
            )
            one = await run_one_stage(one_pipeline, one_backend, frame)
            execution_order = "two_stage_first"
        print(
            f"  one={one['status']} {one['timings_s']['total']:.3f}s; "
            f"two={two['status']} {two['timings_s']['total']:.3f}s "
            f"(caption {two['timings_s']['caption_model']:.3f}s + "
            f"fields {two['timings_s']['field_model']:.3f}s)",
            flush=True,
        )
        records.append(
            {
                "frame": frame.name,
                "frame_path": str(frame),
                "frame_index": frame_index,
                "timestamp_s": timestamp_s,
                "execution_order": execution_order,
                "one_stage": one,
                "two_stage": two,
            }
        )

    summary = build_summary(records)
    summary["model_id"] = model_id
    payload = {"summary": summary, "records": records}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    SUMMARY_PATH.write_text(render_summary(summary))
    print(render_summary(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
