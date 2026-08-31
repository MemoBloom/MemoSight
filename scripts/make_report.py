"""Generate an HTML report comparing bare one-shot vs MemoSight pipeline.

Reads results/compare_results.json, writes results/compare_report.html.
Images are referenced by relative path (frames_sample/...); open the report
from the project root or serve it with: python -m http.server
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

RESULTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/compare_results_720.json")
OUT = RESULTS.with_name(RESULTS.stem.replace("compare_results", "compare_report") + ".html")

FIELDS = ["caption", "scene_labels", "people", "actions",
          "objects", "lighting", "mood", "search_tags"]


def esc(s) -> str:
    return html.escape(str(s))


def render_observation(data: dict) -> str:
    """Render a structured observation as a compact field table."""
    rows = []
    for key in FIELDS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            chips = " ".join(f'<span class="chip">{esc(v)}</span>' for v in value)
            rows.append(f'<tr><td class="k">{esc(key)}</td><td>{chips or "<i>空</i>"}</td></tr>')
        else:
            rows.append(f'<tr><td class="k">{esc(key)}</td><td>{esc(value)}</td></tr>')
    extra = [k for k in data if k not in FIELDS]
    for key in extra:
        rows.append(f'<tr><td class="k">{esc(key)}</td>'
                    f'<td><code>{esc(json.dumps(data[key], ensure_ascii=False))}</code></td></tr>')
    return f'<table class="obs">{"".join(rows)}</table>'


def render_raw(raw: str | None, limit: int = 1200) -> str:
    if not raw:
        return ""
    text = raw if len(raw) <= limit else raw[:limit] + f" …(截断, 共{len(raw)}字符)"
    return f'<details><summary>原始输出 ({len(raw)} 字符)</summary><pre>{esc(text)}</pre></details>'


def render_bare(bare: dict) -> str:
    latency = f'<span class="meta">{bare["latency_s"]}s</span>'
    if bare["ok"]:
        return (f'<div class="verdict ok">✓ 严格 JSON 解析成功 {latency}</div>'
                + render_observation(bare["data"]) + render_raw(bare.get("raw_output")))
    return (f'<div class="verdict fail">✗ 失败（{esc(bare.get("stage", "?"))} 阶段）{latency}</div>'
            f'<div class="errmsg">{esc(bare.get("error", ""))}</div>'
            + render_raw(bare.get("raw_output")))


def render_memosight(memo: dict) -> str:
    latency = f'<span class="meta">{memo["latency_s"]}s</span>'
    meta = (f'<span class="meta">parse_strategy={esc(memo.get("parse_strategy"))} · '
            f'attempts={memo.get("attempts")}</span>')
    if memo["status"] == "ok":
        repaired = ' <span class="tag repair">修复后通过</span>' if (memo.get("attempts") or 1) > 1 else ""
        return (f'<div class="verdict ok">✓ ok {latency} {meta}{repaired}</div>'
                + render_observation(memo["observation"])
                + render_raw(memo.get("raw_output")))
    issues = "".join(f"<li>{esc(m)}</li>" for m in memo.get("issues", []))
    issues_html = f"<ul class='issues'>{issues}</ul>" if issues else ""
    return (f'<div class="verdict fail">✗ failed {latency} {meta}</div>'
            f'<div class="errmsg">{esc(memo.get("error", ""))}</div>{issues_html}'
            + render_raw(memo.get("raw_output")))


def main() -> None:
    records = json.loads(RESULTS.read_text())
    total = len(records)
    bare_ok = sum(1 for r in records if r["bare"]["ok"])
    memo_ok = sum(1 for r in records if r["memosight"]["status"] == "ok")
    repaired = sum(1 for r in records
                   if r["memosight"]["status"] == "ok" and (r["memosight"].get("attempts") or 1) > 1)
    bare_lat = sum(r["bare"]["latency_s"] for r in records) / total
    memo_lat = sum(r["memosight"]["latency_s"] for r in records) / total
    bare_total_s = sum(r["bare"].get("timings_s", {}).get("total", r["bare"]["latency_s"])
                       for r in records)
    bare_model_s = sum(r["bare"].get("timings_s", {}).get("model", r["bare"]["latency_s"])
                       for r in records)
    memo_total_s = sum(r["memosight"].get("timings_s", {}).get("total", r["memosight"]["latency_s"])
                       for r in records)
    memo_model_s = sum(r["memosight"].get("timings_s", {}).get("model", r["memosight"]["latency_s"])
                       for r in records)
    memo_repair_s = sum(
        r["memosight"].get("model_meta", {}).get("duration_s", 0.0)
        for r in records if (r["memosight"].get("attempts") or 1) > 1
    )
    memo_non_model_s = max(0.0, memo_total_s - memo_model_s)
    no_retry = [r for r in records if (r["memosight"].get("attempts") or 1) == 1]
    bare_no_retry_lat = sum(r["bare"]["latency_s"] for r in no_retry) / len(no_retry)
    memo_no_retry_lat = sum(r["memosight"]["latency_s"] for r in no_retry) / len(no_retry)

    cards = []
    for r in records:
        cards.append(f"""
<section class="card">
  <div class="imgbox">
    <img src="../{esc(r["frame_path"])}" loading="lazy" alt="{esc(r["frame"])}">
    <div class="caption-line">{esc(r["frame"])} · t={r["timestamp_s"]:.1f}s</div>
  </div>
  <div class="col">
    <h3>裸一段式 <small>直接采信模型输出，仅严格 json.loads</small></h3>
    {render_bare(r["bare"])}
  </div>
  <div class="col">
    <h3>一段式 + 工程化后处理 <small>MemoSight pipeline：多级解析 / 归一化 / 校验 / 修复重试</small></h3>
    {render_memosight(r["memosight"])}
  </div>
</section>""")

    page = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>MemoSight 对比报告：裸一段式 vs 一段式+工程化后处理</title>
<style>
  :root {{ --ok:#1a7f37; --fail:#cf222e; --bg:#f6f8fa; --border:#d0d7de; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", "Helvetica Neue", sans-serif;
         margin: 0; background: var(--bg); color: #1f2328; }}
  header {{ padding: 24px 32px; background: #fff; border-bottom: 1px solid var(--border);
           position: sticky; top: 0; z-index: 10; }}
  h1 {{ margin: 0 0 8px; font-size: 20px; }}
  .summary {{ display: flex; gap: 24px; flex-wrap: wrap; font-size: 14px; }}
  .summary b {{ font-size: 18px; }}
  main {{ padding: 24px 32px; max-width: 1600px; margin: 0 auto; }}
  .card {{ display: grid; grid-template-columns: 380px 1fr 1fr; gap: 20px;
          background: #fff; border: 1px solid var(--border); border-radius: 8px;
          padding: 16px; margin-bottom: 20px; }}
  .imgbox img {{ width: 100%; border-radius: 6px; display: block; }}
  .caption-line {{ font-size: 12px; color: #656d76; margin-top: 6px; }}
  h3 {{ margin: 0 0 10px; font-size: 15px; }}
  h3 small {{ display: block; font-weight: normal; color: #656d76; font-size: 12px; margin-top: 2px; }}
  .verdict {{ font-weight: 600; margin-bottom: 8px; font-size: 14px; }}
  .verdict.ok {{ color: var(--ok); }} .verdict.fail {{ color: var(--fail); }}
  .meta {{ font-weight: normal; color: #656d76; font-size: 12px; margin-left: 8px; }}
  .tag.repair {{ background: #fff8c5; color: #7d4e00; border-radius: 4px;
                padding: 1px 6px; font-size: 11px; font-weight: 600; }}
  table.obs {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  table.obs td {{ border-top: 1px solid #eaecef; padding: 5px 8px; vertical-align: top; }}
  td.k {{ color: #656d76; white-space: nowrap; width: 110px; font-family: ui-monospace, monospace; font-size: 12px; }}
  .chip {{ display: inline-block; background: #ddf4e4; color: #116329; border-radius: 10px;
          padding: 1px 8px; margin: 1px 2px; font-size: 12px; }}
  .errmsg {{ color: var(--fail); font-size: 13px; margin-bottom: 8px;
            font-family: ui-monospace, monospace; word-break: break-all; }}
  ul.issues {{ font-size: 12px; color: #7d4e00; margin: 4px 0; padding-left: 18px; }}
  details {{ margin-top: 8px; font-size: 12px; }}
  summary {{ cursor: pointer; color: #656d76; }}
  pre {{ background: #f6f8fa; border: 1px solid var(--border); border-radius: 6px;
        padding: 8px; overflow-x: auto; font-size: 11px; max-height: 300px; overflow-y: auto;
        white-space: pre-wrap; word-break: break-all; }}
  @media (max-width: 1100px) {{ .card {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<header>
  <h1>MemoSight 对比：裸一段式 vs 一段式 + 工程化后处理（video/disney.MP4，2fps、736×416，抽样 {total} 帧，zh）</h1>
  <div class="summary">
    <div>裸一段式成功<br><b>{bare_ok}/{total}</b></div>
    <div>MemoSight 成功<br><b>{memo_ok}/{total}</b></div>
    <div>其中修复重试后通过<br><b>{repaired}</b></div>
    <div>平均延迟（裸 / MemoSight）<br><b>{bare_lat:.1f}s / {memo_lat:.1f}s</b></div>
    <div>排除修复帧平均延迟（裸 / MemoSight）<br><b>{bare_no_retry_lat:.2f}s / {memo_no_retry_lat:.2f}s</b></div>
    <div>裸方案模型耗时占比<br><b>{bare_model_s / bare_total_s * 100:.3f}%</b></div>
    <div>MemoSight 初始模型 / 修复模型 / 非模型<br><b>{(memo_model_s - memo_repair_s) / memo_total_s * 100:.3f}% / {memo_repair_s / memo_total_s * 100:.3f}% / {memo_non_model_s / memo_total_s * 100:.3f}%</b></div>
  </div>
</header>
<main>{"".join(cards)}</main>
</body>
</html>"""
    OUT.write_text(page)
    print(f"wrote {OUT} ({len(page)//1024} KB)")


if __name__ == "__main__":
    main()
