"""Judge two-stage results with a larger VLM (e.g. Qwen3.5-4B-MLX-bf16).

For every record in a compare_two_stage result file, the judge sees the frame
image, the stage-one caption, and the stage-two Markdown fields, then classifies
each field item:

- ``supported``:      explicitly stated in the caption AND consistent with image
- ``added_but_true``: NOT in the caption but actually visible in the image
                      (stage two invented it; happens to be correct)
- ``hallucination``:  NOT in the caption AND not visible / contradicted by image

It also scores the caption itself and gives an overall quality score.

Usage:
    .venv/bin/python scripts/eval_two_stage_judge.py \
        --input results/compare_one_stage_vs_two_stage_736x416.json \
        --output results/eval_two_stage_4bjudge.json \
        --judge-url http://127.0.0.1:8080
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
from pathlib import Path

import httpx

FIELDS = [
    "scene_labels",
    "people",
    "actions",
    "objects",
    "lighting",
    "mood",
    "search_tags",
]

JUDGE_SYSTEM = (
    "你是严格的图像标注质检员。给你一张图片、一段由其他模型写的 caption，"
    "以及从 caption 抽取出的 7 组检索字段。你的任务是逐项核对字段内容。"
    "只输出一个 JSON 对象，不要输出任何解释或 Markdown 代码块。"
)

JUDGE_USER_TEMPLATE = """请逐项核对下面的结构化字段。

判定标准（对每个字段的每一项给出 verdict）：
- "supported"：该项在 caption 中有明确表述，且与图片内容一致。
- "added_but_true"：caption 中没有提到该项，但它确实在图片中可见（属于二阶段擅自补充但碰巧正确）。
- "hallucination"：caption 中没有提到，且图片中也看不到或与图片矛盾（真正的幻觉）。

另外评价：
- caption_issues：caption 中与图片明显矛盾的内容（没有则为空数组）。
- accuracy：1-5 分，字段与图片的一致程度（5=完全一致，幻觉越多分越低）。
- completeness：1-5 分，作为检索标注的完备程度。
- comment：一句话总评（中文）。

caption：
{caption}

结构化字段：
{fields_block}

只输出如下结构的 JSON：
{{
  "item_verdicts": [{{"field": "字段名", "item": "条目原文", "verdict": "supported|added_but_true|hallucination"}}],
  "caption_issues": ["..."],
  "accuracy": 1,
  "completeness": 1,
  "comment": "..."
}}"""


def _fields_block(observation: dict) -> str:
    lines = []
    for key in FIELDS:
        items = observation.get(key) or []
        lines.append(f"{key}: {', '.join(str(i) for i in items) if items else '(空)'}")
    return "\n".join(lines)


def _image_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:image/jpeg;base64,{data}"


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None


async def judge_record(
    client: httpx.AsyncClient,
    judge_url: str,
    model_id: str,
    record: dict,
    frames_dir: Path,
) -> dict:
    frame_path = Path(record["frame_path"])
    if not frame_path.exists():
        frame_path = frames_dir / record["frame"]
    observation = record["two_stage"]["observation"]
    caption = observation.get("caption", "")
    user_text = JUDGE_USER_TEMPLATE.format(
        caption=caption, fields_block=_fields_block(observation)
    )
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(frame_path)},
                    },
                ],
            },
        ],
        "max_tokens": 1024,
        "temperature": 0.0,
    }
    raw = ""
    try:
        resp = await client.post(
            f"{judge_url}/v1/chat/completions", json=payload, timeout=300
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        verdict = _extract_json(raw)
        if verdict is None:
            return {"frame": record["frame"], "ok": False, "error": "unparseable judge output", "raw": raw}
        return {"frame": record["frame"], "ok": True, "judge": verdict}
    except Exception as exc:  # noqa: BLE001 - record and continue batch
        return {"frame": record["frame"], "ok": False, "error": str(exc), "raw": raw}


async def _get_model_id(client: httpx.AsyncClient, judge_url: str) -> str:
    # Use /health loaded_model: /v1/models lists every cached model and the
    # server hot-swaps to whatever model id the request names, so the first
    # list entry is not necessarily the loaded judge model.
    resp = await client.get(f"{judge_url}/health", timeout=30)
    resp.raise_for_status()
    loaded = resp.json().get("loaded_model")
    if not loaded:
        raise RuntimeError(f"judge server at {judge_url} reports no loaded model")
    return loaded


def _summarize(evaluations: list[dict]) -> dict:
    verdict_counts = {"supported": 0, "added_but_true": 0, "hallucination": 0}
    per_field: dict[str, dict[str, int]] = {
        key: {"supported": 0, "added_but_true": 0, "hallucination": 0}
        for key in FIELDS
    }
    accuracy: list[float] = []
    completeness: list[float] = []
    caption_issue_frames: list[str] = []
    judged = 0
    for ev in evaluations:
        if not ev.get("ok"):
            continue
        judged += 1
        judge = ev["judge"]
        for item in judge.get("item_verdicts", []):
            verdict = item.get("verdict")
            field = item.get("field")
            if verdict in verdict_counts:
                verdict_counts[verdict] += 1
                if field in per_field:
                    per_field[field][verdict] += 1
        if isinstance(judge.get("accuracy"), (int, float)):
            accuracy.append(float(judge["accuracy"]))
        if isinstance(judge.get("completeness"), (int, float)):
            completeness.append(float(judge["completeness"]))
        if judge.get("caption_issues"):
            caption_issue_frames.append(ev["frame"])
    total_items = sum(verdict_counts.values())
    return {
        "judged_frames": judged,
        "failed_frames": len(evaluations) - judged,
        "total_items": total_items,
        "verdict_counts": verdict_counts,
        "verdict_rates": {
            k: (v / total_items if total_items else 0.0)
            for k, v in verdict_counts.items()
        },
        "per_field": per_field,
        "avg_accuracy": sum(accuracy) / len(accuracy) if accuracy else None,
        "avg_completeness": (
            sum(completeness) / len(completeness) if completeness else None
        ),
        "caption_issue_frames": caption_issue_frames,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--judge-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--judge-model",
        default=None,
        help="explicit model id; default = server's currently loaded model",
    )
    parser.add_argument("--frames-dir", default="frames_sample_736x416")
    args = parser.parse_args()

    records = json.loads(Path(args.input).read_text())["records"]
    frames_dir = Path(args.frames_dir)
    # trust_env=False: macOS system proxy settings would otherwise route
    # localhost traffic through a proxy that answers 503.
    async with httpx.AsyncClient(trust_env=False) as client:
        model_id = args.judge_model or await _get_model_id(client, args.judge_url)
        print(f"judge model: {model_id}")
        evaluations = []
        for i, record in enumerate(records, 1):
            ev = await judge_record(client, args.judge_url, model_id, record, frames_dir)
            status = "ok" if ev.get("ok") else f"FAIL: {ev.get('error')}"
            print(f"[{i}/{len(records)}] {record['frame']}: {status}")
            evaluations.append(ev)

    summary = _summarize(evaluations)
    out = {
        "judge_url": args.judge_url,
        "input": args.input,
        "summary": summary,
        "evaluations": evaluations,
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
