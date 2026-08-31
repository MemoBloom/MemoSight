"""Compare bare one-shot VLM output vs MemoSight pipeline on sampled frames.

Bare one-shot: same model call, raw output accepted via strict json.loads only
(no fence stripping, no embedded-JSON rescue, no normalization, no repair).

MemoSight: full pipeline (multi-strategy parse, normalize, validate, repair).

Writes results/compare_results.json.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MlXVlmMemoSightBackend,
)
from memosight.profiles import resolve_profile
from memosight.prompts import build_prompt
from memosight.source import resolve_image_source

FRAMES_DIR = Path("frames_sample_736x416")
TAG = FRAMES_DIR.name.removeprefix("frames_sample").lstrip("_")
OUT_PATH = Path(f"results/compare_results_{TAG or '1080'}.json")
LANGUAGE = "zh"


class TimedBackend:
    """Measure backend/model calls without changing pipeline behavior."""

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
            duration_s = time.perf_counter() - started
            client = self._backend._get_client()
            meta = dict(getattr(client, "_last_response_meta", {}) or {})
            self.calls.append({"duration_s": duration_s, **meta})


async def bare_one_shot(backend: TimedBackend, image_path: Path, prompt) -> dict:
    """Single model call; strict json.loads is the only acceptance check."""
    total_started = time.perf_counter()
    source_started = time.perf_counter()
    source = MemoSightImageSource(kind="path", image_path=str(image_path))
    resolved = resolve_image_source(source)
    source_s = time.perf_counter() - source_started
    call_index = len(backend.calls)
    try:
        raw = await backend.describe(resolved, prompt)
    except Exception as exc:
        total_s = time.perf_counter() - total_started
        model_s = sum(call["duration_s"] for call in backend.calls[call_index:])
        return {"ok": False, "stage": "backend", "error": str(exc),
                "latency_s": round(total_s, 4),
                "timings_s": {"source": source_s, "model": model_s,
                              "parse": 0.0, "total": total_s}}
    model_calls = backend.calls[call_index:]
    model_s = sum(call["duration_s"] for call in model_calls)
    parse_started = time.perf_counter()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("top level is not a JSON object")
        parse_s = time.perf_counter() - parse_started
        total_s = time.perf_counter() - total_started
        return {
            "ok": True,
            "data": data,
            "raw_output": raw,
            "latency_s": round(total_s, 4),
            "timings_s": {
                "source": source_s,
                "model": model_s,
                "parse": parse_s,
                "total": total_s,
            },
            "model_meta": model_calls[-1] if model_calls else {},
        }
    except (json.JSONDecodeError, ValueError) as exc:
        parse_s = time.perf_counter() - parse_started
        total_s = time.perf_counter() - total_started
        return {"ok": False, "stage": "parse", "error": str(exc),
                "raw_output": raw, "latency_s": round(total_s, 4),
                "timings_s": {"source": source_s, "model": model_s,
                              "parse": parse_s, "total": total_s},
                "model_meta": model_calls[-1] if model_calls else {}}


async def memosight_pipeline(pipeline, backend: TimedBackend, image_path: Path) -> dict:
    request = MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(image_path)),
        asset_id=image_path.stem,
        language=LANGUAGE,
    )
    call_index = len(backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(request)
    total_s = time.perf_counter() - started
    model_calls = backend.calls[call_index:]
    model_s = sum(call["duration_s"] for call in model_calls)
    return {
        "status": result.status,
        "observation": result.observation,
        "raw_output": result.raw_output,
        "error": result.error,
        "attempts": result.usage.get("attempts"),
        "parse_strategy": result.usage.get("parse_strategy"),
        "issues": [issue.message for issue in result.validation.issues],
        "latency_s": round(total_s, 4),
        "timings_s": {
            "model": model_s,
            "pipeline_non_model": max(0.0, total_s - model_s),
            "total": total_s,
        },
        "model_meta": model_calls[-1] if model_calls else {},
    }


async def main() -> None:
    frames = sorted(FRAMES_DIR.glob("*.jpg"))
    backend = TimedBackend(MlXVlmMemoSightBackend())
    pipeline = MemoSightPipeline(backend=backend, max_repair_attempts=1)
    prompt = build_prompt(resolve_profile(profile="photography_default"),
                          language=LANGUAGE)

    if not frames:
        raise RuntimeError(f"No comparison frames found in {FRAMES_DIR}")
    print(f"Warming up with {frames[0].name}...", flush=True)
    await bare_one_shot(backend, frames[0], prompt)

    records = []
    for i, frame in enumerate(frames, 1):
        frame_idx = int(frame.stem[1:])
        timestamp_s = (frame_idx - 1) / 2.0
        print(f"[{i}/{len(frames)}] {frame.name} (t={timestamp_s:.1f}s)", flush=True)
        if i % 2:
            bare = await bare_one_shot(backend, frame, prompt)
            memo = await memosight_pipeline(pipeline, backend, frame)
            order = "bare_first"
        else:
            memo = await memosight_pipeline(pipeline, backend, frame)
            bare = await bare_one_shot(backend, frame, prompt)
            order = "memosight_first"
        print(f"  bare:      {'ok' if bare['ok'] else 'FAIL'} "
              f"({bare['latency_s']}s)", flush=True)
        print(f"  memosight: {memo['status']} strategy={memo['parse_strategy']} "
              f"attempts={memo['attempts']} ({memo['latency_s']}s)", flush=True)
        records.append({
            "frame": frame.name,
            "frame_path": str(frame),
            "frame_index": frame_idx,
            "timestamp_s": timestamp_s,
            "execution_order": order,
            "bare": bare,
            "memosight": memo,
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2))
    bare_ok = sum(1 for r in records if r["bare"]["ok"])
    memo_ok = sum(1 for r in records if r["memosight"]["status"] == "ok")
    print(f"\nDone. bare ok: {bare_ok}/{len(records)}, "
          f"memosight ok: {memo_ok}/{len(records)}")


if __name__ == "__main__":
    asyncio.run(main())
