"""Paired benchmark for stage-two prompt v1 versus a candidate on fixed captions.

Stage one is not rerun. Captions are loaded from the preserved 2B benchmark,
and baseline/candidate execution order alternates per caption to reduce order bias.
All outputs are written to new files; the source benchmark is never modified.
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
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient

SOURCE_PATH = Path("results/compare_one_stage_vs_two_stage_736x416.json")


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


def _field_metrics(fields: dict[str, list[str]]) -> dict:
    counts = {key: len(fields.get(key, [])) for key in CAPTION_FIELD_KEYS}
    chars = sum(
        len(str(item))
        for key in CAPTION_FIELD_KEYS
        for item in fields.get(key, [])
    )
    return {
        "counts": counts,
        "total_items": sum(counts.values()),
        "total_chars": chars,
    }


async def run_version(pipeline, client, caption: str, version: str) -> dict:
    started = time.perf_counter()
    result = await pipeline.extract_fields(caption, prompt_version=version)
    total_s = time.perf_counter() - started
    meta = dict(getattr(client, "_last_response_meta", {}) or {})
    return {
        "status": result.status,
        "fields": result.fields,
        "raw_output": result.raw_output,
        "error": result.error,
        "issues": [issue.message for issue in result.validation.issues],
        "timings_s": {
            "model": result.usage.get("structured_output_duration_s", 0.0),
            "postprocess": result.usage.get("postprocess_duration_s", 0.0),
            "total": total_s,
        },
        "model_meta": meta,
        "metrics": _field_metrics(result.fields),
    }


def summarize(records: list[dict], model_id: str, candidate: str) -> dict:
    summary = {
        "model_id": model_id,
        "frame_count": len(records),
        "fixed_caption_source": str(SOURCE_PATH),
    }
    for version in ("v1", candidate):
        rows = [record[version] for record in records]
        counts = {
            key: sum(row["metrics"]["counts"][key] for row in rows)
            for key in CAPTION_FIELD_KEYS
        }
        completion_tokens = [
            row["model_meta"].get("usage", {}).get("completion_tokens", 0)
            for row in rows
        ]
        summary[version] = {
            "success": sum(row["status"] == "ok" for row in rows),
            "timing_s": _stats([row["timings_s"]["total"] for row in rows]),
            "model_timing_s": _stats([row["timings_s"]["model"] for row in rows]),
            "postprocess_total_s": sum(
                row["timings_s"]["postprocess"] for row in rows
            ),
            "field_items_total": sum(row["metrics"]["total_items"] for row in rows),
            "field_items_avg": statistics.mean(
                row["metrics"]["total_items"] for row in rows
            ),
            "field_chars_total": sum(row["metrics"]["total_chars"] for row in rows),
            "field_chars_avg": statistics.mean(
                row["metrics"]["total_chars"] for row in rows
            ),
            "field_counts_total": counts,
            "field_counts_avg": {
                key: value / len(rows) for key, value in counts.items()
            },
            "completion_tokens_avg": statistics.mean(completion_tokens),
            "completion_tokens_total": sum(completion_tokens),
        }
    v1 = summary["v1"]
    candidate_summary = summary[candidate]
    summary[f"{candidate}_vs_v1"] = {
        "time_pct": (
            candidate_summary["timing_s"]["total"]
            / v1["timing_s"]["total"]
            - 1
        )
        * 100,
        "field_items_pct": (
            candidate_summary["field_items_total"] / v1["field_items_total"] - 1
        )
        * 100,
        "field_chars_pct": (
            candidate_summary["field_chars_total"] / v1["field_chars_total"] - 1
        )
        * 100,
        "completion_tokens_pct": (
            (
                candidate_summary["completion_tokens_total"]
                / v1["completion_tokens_total"]
                - 1
            )
            * 100
            if v1["completion_tokens_total"]
            else None
        ),
        "richer_frames": sum(
            record[candidate]["metrics"]["total_items"]
            > record["v1"]["metrics"]["total_items"]
            for record in records
        ),
        "equal_frames": sum(
            record[candidate]["metrics"]["total_items"]
            == record["v1"]["metrics"]["total_items"]
            for record in records
        ),
    }
    return summary


def render_report(summary: dict, candidate: str) -> str:
    v1 = summary["v1"]
    candidate_summary = summary[candidate]
    delta = summary[f"{candidate}_vs_v1"]
    token_budget = {"v2": 256, "v3": 224, "v4": 192, "v5": 192}[candidate]
    tokens_pct = (
        f"{delta['completion_tokens_pct']:+.2f}%"
        if delta["completion_tokens_pct"] is not None
        else "n/a"
    )
    lines = [
        f"# Stage-two prompt v1 vs {candidate}",
        "",
        f"- Model: {summary['model_id']}",
        f"- Fixed captions: {summary['frame_count']} from `{summary['fixed_caption_source']}`",
        f"- Stage one was not rerun; v1/{candidate} execution order alternated.",
        "",
        f"| Metric | v1 (192 tokens) | {candidate} ({token_budget} tokens) | Delta |",
        "|---|---:|---:|---:|",
        f"| Success | {v1['success']}/{summary['frame_count']} | {candidate_summary['success']}/{summary['frame_count']} | — |",
        f"| Total time | {v1['timing_s']['total']:.3f}s | {candidate_summary['timing_s']['total']:.3f}s | {delta['time_pct']:+.2f}% |",
        f"| Average time | {v1['timing_s']['avg']:.3f}s | {candidate_summary['timing_s']['avg']:.3f}s | — |",
        f"| P95 | {v1['timing_s']['p95']:.3f}s | {candidate_summary['timing_s']['p95']:.3f}s | — |",
        f"| Field items/frame | {v1['field_items_avg']:.2f} | {candidate_summary['field_items_avg']:.2f} | {delta['field_items_pct']:+.2f}% |",
        f"| Field chars/frame | {v1['field_chars_avg']:.2f} | {candidate_summary['field_chars_avg']:.2f} | {delta['field_chars_pct']:+.2f}% |",
        f"| Completion tokens/frame | {v1['completion_tokens_avg']:.2f} | {candidate_summary['completion_tokens_avg']:.2f} | {tokens_pct} |",
        "",
        f"{candidate} produced more field items on {delta['richer_frames']}/{summary['frame_count']} frames and tied on {delta['equal_frames']} frames.",
        "",
        "## Average items by field",
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
    captions = [
        (record["frame"], record["two_stage"]["caption_raw_output"])
        for record in source["records"]
    ]
    client = MlXVlmClient()
    model_id = await client._get_model_id()
    text_backend = MlXTextMemoSightBackend(client=client)
    # The image backend is never called: this benchmark invokes extract_fields only.
    pipeline = TwoStageMemoSightPipeline(
        image_backend=MlXVlmMemoSightBackend(client=client),
        text_backend=text_backend,
    )

    print(f"Resolved model: {model_id}", flush=True)
    print(f"Warming v1 and {candidate} text stages...", flush=True)
    warm_v1 = await pipeline.extract_fields(captions[0][1], prompt_version="v1")
    warm_candidate = await pipeline.extract_fields(
        captions[0][1], prompt_version=candidate
    )
    if warm_v1.status != "ok" or warm_candidate.status != "ok":
        raise RuntimeError(
            "Stage-two warmup failed; verify the configured MLX server URL "
            "before running the benchmark"
        )

    records = []
    for index, (frame, caption) in enumerate(captions, 1):
        print(f"[{index}/{len(captions)}] {frame}", flush=True)
        if index % 2:
            v1 = await run_version(pipeline, client, caption, "v1")
            candidate_result = await run_version(pipeline, client, caption, candidate)
            order = "v1_first"
        else:
            candidate_result = await run_version(pipeline, client, caption, candidate)
            v1 = await run_version(pipeline, client, caption, "v1")
            order = f"{candidate}_first"
        print(
            f"  v1={v1['status']} {v1['timings_s']['total']:.3f}s "
            f"items={v1['metrics']['total_items']}; "
            f"{candidate}={candidate_result['status']} "
            f"{candidate_result['timings_s']['total']:.3f}s "
            f"items={candidate_result['metrics']['total_items']}",
            flush=True,
        )
        records.append(
            {
                "frame": frame,
                "caption": caption,
                "execution_order": order,
                "v1": v1,
                candidate: candidate_result,
            }
        )

    summary = summarize(records, model_id, candidate)
    payload = {"summary": summary, "records": records}
    output_stem = f"compare_stage2_prompt_v1_vs_{candidate}_736x416"
    out_path = Path("results") / f"{output_stem}.json"
    report_path = Path("results") / f"{output_stem}.md"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    report_path.write_text(render_report(summary, candidate))
    print(render_report(summary, candidate), flush=True)
    print(f"JSON: {out_path}", flush=True)
    print(f"Report: {report_path}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=("v2", "v3", "v4", "v5"), default="v2")
    args = parser.parse_args()
    asyncio.run(main(args.candidate))
