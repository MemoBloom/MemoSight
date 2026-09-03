"""Paired benchmark: legacy fixed-Markdown vs schema-driven JSON stage two.

Stage one is not rerun for cached captions. Captions come from preserved
benchmarks plus test_data frames (generated once into a cache file).
Baseline/candidate execution order alternates per caption to reduce order
bias. All outputs go to new files; source benchmark files are never modified.
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
    MemoSightImageSource,
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient
from memosight.normalizer import empty_caption_fields, normalize_caption_fields
from memosight.parser import find_markdown_field_keys, parse_markdown_fields
from memosight.prompts import (
    build_caption_field_extraction_prompt,
    build_caption_prompt,
)
from memosight.source import resolve_image_source

CAPTION_SOURCES = [
    Path("results/compare_one_stage_vs_two_stage_736x416.json"),
    Path("results/squat_compare_one_vs_two.json"),
]
CACHE_PATH = Path("results/stage2_caption_cache.json")
TEST_DATA = Path("test_data")
OUT_JSON = Path("results/compare_stage2_markdown_vs_json.json")
OUT_MD = Path("results/compare_stage2_markdown_vs_json.md")


def load_preserved_captions() -> list[dict]:
    captions = []
    for path in CAPTION_SOURCES:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        records = data["records"] if isinstance(data, dict) else data
        for record in records:
            caption = (record.get("two_stage") or {}).get("caption_raw_output")
            if caption:
                captions.append(
                    {"source": f"{path.name}:{record.get('frame', '?')}", "caption": caption}
                )
    return captions


async def load_test_data_captions(image_backend) -> list[dict]:
    cache = (
        json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if CACHE_PATH.exists()
        else {}
    )
    frames = sorted(
        path for path in TEST_DATA.glob("*/*.jpg") if path.parent.name != "report"
    )
    prompt = build_caption_prompt(language="zh")
    captions = []
    dirty = False
    for index, frame in enumerate(frames, 1):
        key = str(frame)
        if key not in cache:
            print(f"caption [{index}/{len(frames)}] {key}", flush=True)
            resolved = resolve_image_source(MemoSightImageSource(image_path=key))
            cache[key] = await image_backend.describe(resolved, prompt)
            dirty = True
        captions.append({"source": key, "caption": cache[key]})
    if dirty:
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return captions


def _stats(values: list[float]) -> dict:
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "avg": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": ordered[p95_index],
        "min": min(values),
        "max": max(values),
    }


def _field_metrics(fields: dict) -> dict:
    counts = {key: len(fields.get(key, [])) for key in CAPTION_FIELD_KEYS}
    return {"counts": counts, "total_items": sum(counts.values())}


async def run_markdown(text_backend, client, caption: str) -> dict:
    """Replicate the pre-JSON pipeline branch as the baseline."""
    prompt = build_caption_field_extraction_prompt(caption)
    started = time.perf_counter()
    raw = await text_backend.complete(prompt)
    total_s = time.perf_counter() - started
    meta = dict(getattr(client, "_last_response_meta", {}) or {})
    parsed = parse_markdown_fields(raw)
    present = find_markdown_field_keys(raw)
    missing = [key for key in CAPTION_FIELD_KEYS if key not in present]
    fields = (
        normalize_caption_fields(parsed) if parsed is not None else empty_caption_fields()
    )
    return {
        "status": "ok" if parsed is not None and not missing else "failed",
        "missing_fields": missing,
        "fields": fields,
        "raw_output": raw,
        "timings_s": {"total": total_s},
        "completion_tokens": meta.get("usage", {}).get("completion_tokens", 0),
        "metrics": _field_metrics(fields),
    }


async def run_json(pipeline, client, caption: str) -> dict:
    started = time.perf_counter()
    result = await pipeline.extract_fields(caption)
    total_s = time.perf_counter() - started
    meta = dict(getattr(client, "_last_response_meta", {}) or {})
    return {
        "status": result.status,
        "missing_fields": [
            issue.message.removeprefix("Missing required JSON fields: ").split(", ")
            for issue in result.validation.issues
            if issue.message.startswith("Missing required JSON fields")
        ],
        "fields": result.fields,
        "raw_output": result.raw_output,
        "error": result.error,
        "parse_strategy": result.usage.get("parse_strategy"),
        "timings_s": {"total": total_s},
        "completion_tokens": meta.get("usage", {}).get("completion_tokens", 0),
        "metrics": _field_metrics(result.fields),
    }


def _side_summary(rows: list[dict]) -> dict:
    counts = {
        key: sum(row["metrics"]["counts"][key] for row in rows)
        for key in CAPTION_FIELD_KEYS
    }
    return {
        "success": sum(row["status"] == "ok" for row in rows),
        "timing_s": _stats([row["timings_s"]["total"] for row in rows]),
        "completion_tokens_avg": statistics.mean(
            row["completion_tokens"] for row in rows
        ),
        "field_items_avg": statistics.mean(
            row["metrics"]["total_items"] for row in rows
        ),
        "field_counts_avg": {
            key: value / len(rows) for key, value in counts.items()
        },
        "missing_field_failures": [
            {"missing": row["missing_fields"], "raw": (row["raw_output"] or "")[:200]}
            for row in rows
            if row["status"] != "ok" and row["missing_fields"]
        ],
        "other_failures": sum(
            row["status"] != "ok" and not row["missing_fields"] for row in rows
        ),
    }


def render_report(summary: dict) -> str:
    md, js = summary["markdown"], summary["json"]
    n = summary["caption_count"]
    lines = [
        "# Stage-two: fixed Markdown vs schema-driven JSON (default profile)",
        "",
        f"- Model: {summary['model_id']}",
        f"- Fixed captions: {n}（stage-1 未重跑；执行顺序逐条交替）",
        "",
        "| Metric | Markdown baseline | JSON candidate |",
        "|---|---:|---:|",
        f"| Success | {md['success']}/{n} | {js['success']}/{n} |",
        f"| Missing-field failures | {len(md['missing_field_failures'])} | {len(js['missing_field_failures'])} |",
        f"| Other failures (parse) | {md['other_failures']} | {js['other_failures']} |",
        f"| Avg time | {md['timing_s']['avg']:.3f}s | {js['timing_s']['avg']:.3f}s |",
        f"| P95 time | {md['timing_s']['p95']:.3f}s | {js['timing_s']['p95']:.3f}s |",
        f"| Completion tokens/caption | {md['completion_tokens_avg']:.1f} | {js['completion_tokens_avg']:.1f} |",
        f"| Field items/caption | {md['field_items_avg']:.2f} | {js['field_items_avg']:.2f} |",
        "",
        "## Average items by field",
        "",
        "| Field | Markdown | JSON |",
        "|---|---:|---:|",
    ]
    for key in CAPTION_FIELD_KEYS:
        lines.append(
            f"| {key} | {md['field_counts_avg'][key]:.2f} | "
            f"{js['field_counts_avg'][key]:.2f} |"
        )
    for side, label in (("markdown", "Markdown"), ("json", "JSON")):
        failures = summary[side]["missing_field_failures"]
        if failures:
            lines += ["", f"## {label} missing-field failures", ""]
            for failure in failures:
                lines.append(f"- missing={failure['missing']} raw=`{failure['raw']}`")
    return "\n".join(lines) + "\n"


async def main(limit: int) -> None:
    client = MlXVlmClient()
    model_id = await client._get_model_id()
    image_backend = MlXVlmMemoSightBackend(client=client)
    text_backend = MlXTextMemoSightBackend(client=client)
    pipeline = TwoStageMemoSightPipeline(
        image_backend=image_backend,
        text_backend=text_backend,
    )

    captions = load_preserved_captions()
    captions.extend(await load_test_data_captions(image_backend))
    if limit > 0:
        captions = captions[:limit]
    print(f"Resolved model: {model_id}; captions: {len(captions)}", flush=True)

    print("Warming markdown and json stage-two paths...", flush=True)
    warm_md = await run_markdown(text_backend, client, captions[0]["caption"])
    warm_js = await run_json(pipeline, client, captions[0]["caption"])
    if warm_js["status"] != "ok" or warm_md["status"] != "ok":
        raise RuntimeError(
            "Stage-two warmup failed; verify the configured MLX server URL "
            "before running the benchmark"
        )

    records = []
    for index, item in enumerate(captions, 1):
        print(f"[{index}/{len(captions)}] {item['source']}", flush=True)
        if index % 2:
            md = await run_markdown(text_backend, client, item["caption"])
            js = await run_json(pipeline, client, item["caption"])
            order = "markdown_first"
        else:
            js = await run_json(pipeline, client, item["caption"])
            md = await run_markdown(text_backend, client, item["caption"])
            order = "json_first"
        print(
            f"  markdown={md['status']} {md['timings_s']['total']:.3f}s "
            f"items={md['metrics']['total_items']}; "
            f"json={js['status']} {js['timings_s']['total']:.3f}s "
            f"items={js['metrics']['total_items']}",
            flush=True,
        )
        records.append(
            {
                "source": item["source"],
                "caption": item["caption"],
                "execution_order": order,
                "markdown": md,
                "json": js,
            }
        )

    summary = {
        "model_id": model_id,
        "caption_count": len(records),
        "markdown": _side_summary([record["markdown"] for record in records]),
        "json": _side_summary([record["json"] for record in records]),
    }
    OUT_JSON.write_text(
        json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    OUT_MD.write_text(render_report(summary), encoding="utf-8")
    print(render_report(summary), flush=True)
    print(f"JSON: {OUT_JSON}", flush=True)
    print(f"Report: {OUT_MD}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 means all captions")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
