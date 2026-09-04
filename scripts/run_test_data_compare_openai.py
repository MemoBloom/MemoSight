"""Run one-stage vs two-stage (current default profile) comparison on test_data/
through the OpenAI-compatible (vLLM/SGLang) backend.

Mirrors scripts/run_test_data_compare.py (mlx variant): for each subdirectory
of test_data/, runs both variants on all frames with alternating execution
order after a shared warm-up, then writes
results/test_data_compare_openai.json.

Thinking models (Qwen3.6, ...) are run with ``enable_thinking: false`` via the
per-request ``chat_template_kwargs`` passthrough; with thinking on, the
reasoning block consumes the max_tokens budget and truncates the structured
output before it can be parsed.

Connection defaults to MEMOSIGHT_OPENAI_BASE_URL / MEMOSIGHT_OPENAI_MODEL,
overridable with --base-url / --model.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    OpenAICompatBackend,
    OpenAICompatTextBackend,
    TwoStageMemoSightPipeline,
)

TEST_DATA_DIR = Path("test_data")
OUT_PATH = Path("results/test_data_compare_openai.json")
LANGUAGE = "zh"
CAPTION_FIELD_KEYS = (
    "scene_labels",
    "people",
    "actions",
    "objects",
    "lighting",
    "mood",
    "search_tags",
)


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
            self.calls.append({"duration_s": time.perf_counter() - started})


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
            self.calls.append({"duration_s": time.perf_counter() - started})


def _request(frame: Path) -> MemoSightRequest:
    return MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(frame)),
        asset_id=frame.stem,
        language=LANGUAGE,
    )


def _video_duration_s(video_dir: Path) -> float | None:
    meta = video_dir / "duration_s.txt"
    if meta.is_file():
        return float(meta.read_text().strip())
    return None


def _filled_fields(observation: dict | None) -> int:
    if not observation:
        return 0
    return sum(1 for key in CAPTION_FIELD_KEYS if observation.get(key))


async def run_one_stage(pipeline, backend, frame: Path) -> dict:
    call_index = len(backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame))
    total_s = time.perf_counter() - started
    model_s = sum(call["duration_s"] for call in backend.calls[call_index:])
    return {
        "status": result.status,
        "observation": result.observation,
        "filled_fields": _filled_fields(result.observation),
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "attempts": result.usage.get("attempts"),
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {
            "model": model_s,
            "non_model": max(0.0, total_s - model_s),
            "total": total_s,
        },
    }


async def run_two_stage(pipeline, image_backend, text_backend, frame: Path) -> dict:
    image_index = len(image_backend.calls)
    text_index = len(text_backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame))
    total_s = time.perf_counter() - started
    caption_model_s = sum(
        call["duration_s"] for call in image_backend.calls[image_index:]
    )
    field_model_s = sum(call["duration_s"] for call in text_backend.calls[text_index:])
    return {
        "status": result.status,
        "observation": result.observation,
        "filled_fields": _filled_fields(result.observation),
        "failed_stage": result.failed_stage,
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {
            "caption_model": caption_model_s,
            "field_model": field_model_s,
            "model_total": caption_model_s + field_model_s,
            "non_model": max(0.0, total_s - caption_model_s - field_model_s),
            "total": total_s,
        },
    }


def _avg(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def build_video_summary(records: list[dict]) -> dict:
    one_ok = sum(row["one_stage"]["status"] == "ok" for row in records)
    two_ok = sum(row["two_stage"]["status"] == "ok" for row in records)
    one_avg = _avg([row["one_stage"]["timings_s"]["total"] for row in records])
    two_avg = _avg([row["two_stage"]["timings_s"]["total"] for row in records])
    caption_avg = _avg(
        [row["two_stage"]["timings_s"]["caption_model"] for row in records]
    )
    field_avg = _avg([row["two_stage"]["timings_s"]["field_model"] for row in records])
    return {
        "frame_count": len(records),
        "one_stage_ok": one_ok,
        "two_stage_ok": two_ok,
        "two_stage_partial": sum(
            row["two_stage"]["status"] == "partial" for row in records
        ),
        "one_stage": {"avg_s": one_avg, "avg_filled_fields": _avg(
            [row["one_stage"]["filled_fields"] for row in records])},
        "two_stage": {
            "avg_s": two_avg,
            "caption_avg_s": caption_avg,
            "field_avg_s": field_avg,
            "avg_filled_fields": _avg(
                [row["two_stage"]["filled_fields"] for row in records]),
        },
        "two_stage_vs_one_stage_pct": (two_avg / one_avg - 1) * 100 if one_avg else 0.0,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    base_url = args.base_url or os.environ.get(
        "MEMOSIGHT_OPENAI_BASE_URL", "http://127.0.0.1:8000/v1"
    )
    chat_kwargs = {"enable_thinking": False}

    video_dirs = sorted(
        path
        for path in TEST_DATA_DIR.iterdir()
        if path.is_dir() and any(path.glob("*.jpg"))
    )
    if not video_dirs:
        raise RuntimeError(f"No video directories found in {TEST_DATA_DIR}")

    one_backend = TimedImageBackend(
        OpenAICompatBackend(base_url, args.model, chat_template_kwargs=chat_kwargs)
    )
    two_image_backend = TimedImageBackend(
        OpenAICompatBackend(base_url, args.model, chat_template_kwargs=chat_kwargs)
    )
    two_text_backend = TimedTextBackend(
        OpenAICompatTextBackend(base_url, args.model, chat_template_kwargs=chat_kwargs)
    )
    one_pipeline = MemoSightPipeline(one_backend, max_repair_attempts=1)
    two_pipeline = TwoStageMemoSightPipeline(two_image_backend, two_text_backend)
    model_id = await one_backend._backend._get_model_id()
    print(f"Base URL: {base_url} | model: {model_id} | kwargs: {chat_kwargs}", flush=True)

    first_frames = sorted(video_dirs[0].glob("*.jpg"))
    print(f"Warming both paths with {first_frames[0]}...", flush=True)
    await run_one_stage(one_pipeline, one_backend, first_frames[0])
    await run_two_stage(two_pipeline, two_image_backend, two_text_backend, first_frames[0])

    videos = []
    for video_dir in video_dirs:
        frames = sorted(video_dir.glob("*.jpg"))
        duration_s = _video_duration_s(video_dir)
        print(f"\n== {video_dir.name}: {len(frames)} frames ==", flush=True)
        records = []
        for index, frame in enumerate(frames, 1):
            frame_idx = int(frame.stem[1:])
            timestamp_s = (
                (frame_idx - 1) / (len(frames) - 1) * duration_s
                if duration_s and len(frames) > 1
                else 0.0
            )
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
                f"  [{index}/{len(frames)}] {frame.name} "
                f"one={one['status']} {one['timings_s']['total']:.2f}s; "
                f"two={two['status']} {two['timings_s']['total']:.2f}s",
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
        videos.append(
            {
                "video": video_dir.name,
                "duration_s": duration_s,
                "summary": build_video_summary(records),
                "records": records,
            }
        )

    payload = {
        "backend": "openai_compat",
        "base_url": base_url,
        "model_id": model_id,
        "chat_template_kwargs": chat_kwargs,
        "videos": videos,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nWrote {OUT_PATH}", flush=True)
    for video in videos:
        summary = video["summary"]
        print(
            f"{video['video']}: one {summary['one_stage_ok']}/{summary['frame_count']} ok "
            f"avg {summary['one_stage']['avg_s']:.2f}s; "
            f"two {summary['two_stage_ok']}/{summary['frame_count']} ok "
            f"avg {summary['two_stage']['avg_s']:.2f}s "
            f"({summary['two_stage_vs_one_stage_pct']:+.1f}%)",
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
