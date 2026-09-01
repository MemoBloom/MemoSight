"""Paired benchmark for stage-one caption prompt v1 versus a candidate.

Both variants use the same 20 images and the same v1 field extractor. Execution
order alternates per frame. Results are written to new files and never modify
the previous one-stage/two-stage or stage-two prompt benchmarks.
"""
from __future__ import annotations

import asyncio
import argparse
import json
import statistics
import time
from pathlib import Path

from memosight import (
    CAPTION_FIELD_KEYS,
    MemoSightImageSource,
    MemoSightRequest,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient

SOURCE_PATH = Path("results/compare_one_stage_vs_two_stage_736x416.json")


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
                    "prompt_version": prompt.schema_name,
                    "max_tokens": prompt.max_tokens,
                    **dict(
                        getattr(
                            self._backend._get_client(),
                            "_last_response_meta",
                            {},
                        )
                        or {}
                    ),
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
                    **dict(
                        getattr(
                            self._backend._get_client(),
                            "_last_response_meta",
                            {},
                        )
                        or {}
                    ),
                }
            )


def _request(frame: Path) -> MemoSightRequest:
    return MemoSightRequest(
        image=MemoSightImageSource(kind="path", image_path=str(frame)),
        asset_id=frame.stem,
        language="zh",
    )


def _field_metrics(observation: dict) -> dict:
    counts = {key: len(observation.get(key, [])) for key in CAPTION_FIELD_KEYS}
    chars = sum(
        len(str(item))
        for key in CAPTION_FIELD_KEYS
        for item in observation.get(key, [])
    )
    return {
        "counts": counts,
        "total_items": sum(counts.values()),
        "total_chars": chars,
    }


async def run_version(
    pipeline,
    image_backend,
    text_backend,
    frame: Path,
) -> dict:
    image_index = len(image_backend.calls)
    text_index = len(text_backend.calls)
    started = time.perf_counter()
    result = await pipeline.analyze(_request(frame))
    total_s = time.perf_counter() - started
    image_calls = image_backend.calls[image_index:]
    text_calls = text_backend.calls[text_index:]
    caption = result.caption_raw_output or ""
    metrics = _field_metrics(result.observation)
    return {
        "status": result.status,
        "caption": caption,
        "fields": {
            key: result.observation.get(key, []) for key in CAPTION_FIELD_KEYS
        },
        "structured_raw_output": result.structured_raw_output,
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "timings_s": {
            "caption": sum(call["duration_s"] for call in image_calls),
            "field": sum(call["duration_s"] for call in text_calls),
            "total": total_s,
        },
        "caption_model_calls": image_calls,
        "field_model_calls": text_calls,
        "metrics": {
            "caption_chars": len(caption),
            "field_items": metrics["total_items"],
            "field_chars": metrics["total_chars"],
            "field_items_per_100_caption_chars": (
                metrics["total_items"] / len(caption) * 100 if caption else 0.0
            ),
            "field_chars_per_caption_char": (
                metrics["total_chars"] / len(caption) if caption else 0.0
            ),
            "field_counts": metrics["counts"],
        },
    }


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "total": sum(values),
        "avg": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": ordered[p95_index],
        "min": min(values),
        "max": max(values),
    }


def _completion_tokens(row: dict, call_key: str) -> int:
    calls = row[call_key]
    return sum(call.get("usage", {}).get("completion_tokens", 0) for call in calls)


def summarize(records: list[dict], model_id: str, candidate: str) -> dict:
    summary = {
        "model_id": model_id,
        "frame_count": len(records),
        "fixed_field_prompt": "v1",
        "source_frames": str(SOURCE_PATH),
    }
    for version in ("v1", candidate):
        rows = [record[version] for record in records]
        caption_chars = [row["metrics"]["caption_chars"] for row in rows]
        field_items = [row["metrics"]["field_items"] for row in rows]
        field_chars = [row["metrics"]["field_chars"] for row in rows]
        caption_tokens = [
            _completion_tokens(row, "caption_model_calls") for row in rows
        ]
        field_counts = {
            key: sum(row["metrics"]["field_counts"][key] for row in rows)
            for key in CAPTION_FIELD_KEYS
        }
        summary[version] = {
            "success": sum(row["status"] == "ok" for row in rows),
            "caption_timing_s": _stats(
                [row["timings_s"]["caption"] for row in rows]
            ),
            "field_timing_s": _stats(
                [row["timings_s"]["field"] for row in rows]
            ),
            "total_timing_s": _stats(
                [row["timings_s"]["total"] for row in rows]
            ),
            "caption_chars_avg": statistics.mean(caption_chars),
            "caption_chars_min": min(caption_chars),
            "caption_chars_max": max(caption_chars),
            "caption_completion_tokens_avg": statistics.mean(caption_tokens),
            "field_items_avg": statistics.mean(field_items),
            "field_chars_avg": statistics.mean(field_chars),
            "field_items_per_100_caption_chars_avg": statistics.mean(
                row["metrics"]["field_items_per_100_caption_chars"]
                for row in rows
            ),
            "field_chars_per_caption_char_avg": statistics.mean(
                row["metrics"]["field_chars_per_caption_char"] for row in rows
            ),
            "field_counts_avg": {
                key: count / len(rows) for key, count in field_counts.items()
            },
        }
    v1 = summary["v1"]
    candidate_summary = summary[candidate]
    summary[f"{candidate}_vs_v1"] = {
        "caption_time_pct": (
            candidate_summary["caption_timing_s"]["total"]
            / v1["caption_timing_s"]["total"]
            - 1
        )
        * 100,
        "total_time_pct": (
            candidate_summary["total_timing_s"]["total"]
            / v1["total_timing_s"]["total"]
            - 1
        )
        * 100,
        "caption_chars_pct": (
            candidate_summary["caption_chars_avg"] / v1["caption_chars_avg"] - 1
        )
        * 100,
        "caption_completion_tokens_pct": (
            candidate_summary["caption_completion_tokens_avg"]
            / v1["caption_completion_tokens_avg"]
            - 1
        )
        * 100,
        "field_items_pct": (
            candidate_summary["field_items_avg"] / v1["field_items_avg"] - 1
        )
        * 100,
        "field_chars_pct": (
            candidate_summary["field_chars_avg"] / v1["field_chars_avg"] - 1
        )
        * 100,
        "longer_caption_frames": sum(
            record[candidate]["metrics"]["caption_chars"]
            > record["v1"]["metrics"]["caption_chars"]
            for record in records
        ),
        "more_field_items_frames": sum(
            record[candidate]["metrics"]["field_items"]
            > record["v1"]["metrics"]["field_items"]
            for record in records
        ),
    }
    return summary


def render_report(summary: dict, candidate: str) -> str:
    v1 = summary["v1"]
    candidate_summary = summary[candidate]
    delta = summary[f"{candidate}_vs_v1"]
    target = {"v2": "80–120 chars", "v3": "90–110 chars"}[candidate]
    token_budget = {"v2": 160, "v3": 128}[candidate]
    lines = [
        f"# Stage-one caption prompt v1 vs {candidate}",
        "",
        f"- Model: {summary['model_id']}",
        f"- Frames: {summary['frame_count']} from `{summary['source_frames']}`",
        "- Field extraction stayed fixed at v1 / 192 max tokens.",
        "- Stage-one execution order alternated per frame.",
        "",
        f"| Metric | v1 (50–80 chars, 96 tokens) | {candidate} ({target}, {token_budget} tokens) | Delta |",
        "|---|---:|---:|---:|",
        f"| Success | {v1['success']}/20 | {candidate_summary['success']}/20 | — |",
        f"| Caption time | {v1['caption_timing_s']['total']:.3f}s | {candidate_summary['caption_timing_s']['total']:.3f}s | {delta['caption_time_pct']:+.2f}% |",
        f"| Total two-stage time | {v1['total_timing_s']['total']:.3f}s | {candidate_summary['total_timing_s']['total']:.3f}s | {delta['total_time_pct']:+.2f}% |",
        f"| Caption chars/frame | {v1['caption_chars_avg']:.2f} | {candidate_summary['caption_chars_avg']:.2f} | {delta['caption_chars_pct']:+.2f}% |",
        f"| Caption completion tokens/frame | {v1['caption_completion_tokens_avg']:.2f} | {candidate_summary['caption_completion_tokens_avg']:.2f} | {delta['caption_completion_tokens_pct']:+.2f}% |",
        f"| Extracted field items/frame | {v1['field_items_avg']:.2f} | {candidate_summary['field_items_avg']:.2f} | {delta['field_items_pct']:+.2f}% |",
        f"| Extracted field chars/frame | {v1['field_chars_avg']:.2f} | {candidate_summary['field_chars_avg']:.2f} | {delta['field_chars_pct']:+.2f}% |",
        f"| Items / 100 caption chars | {v1['field_items_per_100_caption_chars_avg']:.2f} | {candidate_summary['field_items_per_100_caption_chars_avg']:.2f} | — |",
        "",
        f"{candidate} captions were longer on {delta['longer_caption_frames']}/20 frames; "
        f"{candidate} produced more structured field items on {delta['more_field_items_frames']}/20 frames.",
        "",
        "## Average extracted items by field",
        "",
        f"| Field | v1 | {candidate} |",
        "|---|---:|---:|",
    ]
    for key in CAPTION_FIELD_KEYS:
        lines.append(
            f"| {key} | {v1['field_counts_avg'][key]:.2f} | "
            f"{candidate_summary['field_counts_avg'][key]:.2f} |"
        )
    return "\n".join(lines) + "\n"


async def main(candidate: str) -> None:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    frames = [Path(record["frame_path"]) for record in source["records"]]
    client = MlXVlmClient()
    model_id = await client._get_model_id()
    image_backend = TimedImageBackend(MlXVlmMemoSightBackend(client=client))
    text_backend = TimedTextBackend(MlXTextMemoSightBackend(client=client))
    pipelines = {
        version: TwoStageMemoSightPipeline(
            image_backend=image_backend,
            text_backend=text_backend,
            caption_prompt_version=version,
            field_prompt_version="v1",
        )
        for version in ("v1", candidate)
    }

    print(f"Resolved model: {model_id}", flush=True)
    print(f"Warming v1 and {candidate} full pipelines...", flush=True)
    warm_v1 = await pipelines["v1"].analyze(_request(frames[0]))
    warm_candidate = await pipelines[candidate].analyze(_request(frames[0]))
    if warm_v1.status != "ok" or warm_candidate.status != "ok":
        raise RuntimeError("Stage-one benchmark warmup failed")

    records = []
    for index, frame in enumerate(frames, 1):
        print(f"[{index}/{len(frames)}] {frame.name}", flush=True)
        if index % 2:
            v1 = await run_version(
                pipelines["v1"], image_backend, text_backend, frame
            )
            candidate_result = await run_version(
                pipelines[candidate], image_backend, text_backend, frame
            )
            order = "v1_first"
        else:
            candidate_result = await run_version(
                pipelines[candidate], image_backend, text_backend, frame
            )
            v1 = await run_version(
                pipelines["v1"], image_backend, text_backend, frame
            )
            order = f"{candidate}_first"
        print(
            f"  v1={v1['status']} caption={v1['metrics']['caption_chars']} chars "
            f"fields={v1['metrics']['field_items']} time={v1['timings_s']['total']:.3f}s; "
            f"{candidate}={candidate_result['status']} "
            f"caption={candidate_result['metrics']['caption_chars']} chars "
            f"fields={candidate_result['metrics']['field_items']} "
            f"time={candidate_result['timings_s']['total']:.3f}s",
            flush=True,
        )
        records.append(
            {
                "frame": frame.name,
                "frame_path": str(frame),
                "execution_order": order,
                "v1": v1,
                candidate: candidate_result,
            }
        )

    summary = summarize(records, model_id, candidate)
    payload = {"summary": summary, "records": records}
    output_stem = f"compare_stage1_caption_v1_vs_{candidate}_736x416"
    out_path = Path("results") / f"{output_stem}.json"
    report_path = Path("results") / f"{output_stem}.md"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    report_path.write_text(render_report(summary, candidate))
    print(render_report(summary, candidate), flush=True)
    print(f"JSON: {out_path}", flush=True)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=("v2", "v3"), default="v2")
    args = parser.parse_args()
    asyncio.run(main(args.candidate))
