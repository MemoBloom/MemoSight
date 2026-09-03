"""Build per-video side-by-side review pages plus an index for test_data runs.

Reads results/test_data_compare_one_vs_two_stage.json (produced by
run_test_data_compare.py) and writes one HTML page per video under
results/test_data_review_one_vs_two_stage/, reusing
make_side_by_side_review.HTML with relabeling, plus an index.html that links
to every video page with its summary numbers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_side_by_side_review import HTML

SOURCE = Path("results/test_data_compare_one_vs_two_stage.json")
OUTPUT_DIR = Path("results/test_data_review_one_vs_two_stage")

LABEL_REPLACEMENTS = [
    ("<span>单阶段 <strong", "<span>一段式 <strong"),
    ("<span>两阶段 <strong", "<span>两段式 <strong"),
    ("平均提速", "两段式耗时变化"),
    ("单阶段 JSON", "一段式 JSON"),
    ("两阶段 Caption → Fields", "两段式（caption → 7 行 Markdown 契约）"),
    ("<span>两阶段</span>", "<span>两段式</span>"),
    ("两阶段拆分：Caption", "两段式拆分：Caption"),
]

VIDEO_TITLES = {
    "disney": "Disney 片段",
    "qinsi_aozhou": "亚洲不够装，我来澳洲看看 · 秦思",
    "guba": "打开书本里的世界 · 古巴",
    "luosifen": "柳州菜市场螺蛳粉",
    "huazhixiao": "花知晓开箱妆教",
    "paotui": "韩国跑腿兼职盲盒",
    "gouwufenxiang": "17min 购物分享开箱",
    "chibo_regou": "明朗热狗 + 辣味芝士条吃播",
}

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MemoSight · 一段式 vs 两段式 · 测试数据总览</title>
  <style>
    body {{ margin: 0; padding: 32px 22px; background: #f4f6f8; color: #14181f;
           font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif; }}
    h1 {{ margin: 0 0 4px; font-size: 22px; }}
    .meta {{ color: #687180; font-size: 13px; margin-bottom: 22px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 14px; }}
    .card {{ display: block; text-decoration: none; color: inherit; background: #fff;
             border: 1px solid #dce1e7; border-radius: 11px; padding: 14px;
             transition: border-color 140ms ease, box-shadow 140ms ease; }}
    .card:hover {{ border-color: #1769ff; box-shadow: 0 2px 10px rgb(23 105 255 / 12%); }}
    .card h2 {{ margin: 0 0 8px; font-size: 15px; }}
    .card img {{ width: 100%; aspect-ratio: 16 / 9; object-fit: cover; border-radius: 7px;
                 background: #11151a; display: block; margin-bottom: 10px; }}
    .stats {{ display: flex; gap: 12px; color: #687180; font-size: 12px; flex-wrap: wrap; }}
    .stats strong {{ color: #14181f; font-variant-numeric: tabular-nums; }}
    .faster {{ color: #12834c; }} .slower {{ color: #d73527; }}
  </style>
</head>
<body>
  <h1>MemoSight · 一段式 vs 两段式</h1>
  <p class="meta">模型 {model_id} · 每个视频 10 帧 · 点击卡片进入逐帧对比</p>
  <div class="grid">
{cards}
  </div>
</body>
</html>
"""

CARD_HTML = """    <a class="card" href="{page}">
      <img src="{thumb}" alt="" loading="lazy">
      <h2>{title}</h2>
      <div class="stats">
        <span>一段式 <strong>{one_avg:.3f}s</strong> ({one_ok}/{n})</span>
        <span>两段式 <strong>{two_avg:.3f}s</strong> ({two_ok}/{n})</span>
        <span class="{delta_class}">{delta:+.1f}%</span>
      </div>
    </a>"""


def build_page(video: dict, model_id: str) -> str:
    summary = video["summary"]
    payload = {
        "summary": {
            "model_id": model_id,
            "one_stage": {"avg_s": summary["one_stage"]["avg_s"]},
            "two_stage": {"avg_s": summary["two_stage"]["avg_s"]},
            "two_stage_vs_one_stage_pct": summary["two_stage_vs_one_stage_pct"],
        },
        "records": video["records"],
    }
    html = HTML
    for old, new in LABEL_REPLACEMENTS:
        if old not in html:
            raise RuntimeError(f"label not found in template: {old}")
        html = html.replace(old, new)
    title = VIDEO_TITLES.get(video["video"], video["video"])
    html = html.replace(
        "<h1>MemoSight · 标注结果对比</h1>",
        f'<h1>MemoSight · {title}</h1>',
    )
    path_fix = ("'../' + record.frame_path", "'../../' + record.frame_path")
    if path_fix[0] not in html:
        raise RuntimeError("frame path prefix not found in template")
    html = html.replace(*path_fix)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return html.replace("__DATA__", embedded)


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    model_id = payload["model_id"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cards = []
    for video in payload["videos"]:
        page = f"{video['video']}.html"
        html = build_page(video, model_id)
        (OUTPUT_DIR / page).write_text(html, encoding="utf-8")
        summary = video["summary"]
        delta = summary["two_stage_vs_one_stage_pct"]
        thumb = "../../" + video["records"][0]["frame_path"]
        cards.append(
            CARD_HTML.format(
                page=page,
                thumb=thumb,
                title=VIDEO_TITLES.get(video["video"], video["video"]),
                one_avg=summary["one_stage"]["avg_s"],
                two_avg=summary["two_stage"]["avg_s"],
                one_ok=summary["one_stage_ok"],
                two_ok=summary["two_stage_ok"],
                n=summary["frame_count"],
                delta=delta,
                delta_class="faster" if delta <= 0 else "slower",
            )
        )
        print(f"Wrote {OUTPUT_DIR / page}")

    index = INDEX_HTML.format(
        model_id=model_id.split("/")[-1], cards="\n".join(cards)
    )
    (OUTPUT_DIR / "index.html").write_text(index, encoding="utf-8")
    print(f"Wrote {OUTPUT_DIR / 'index.html'}")


if __name__ == "__main__":
    main()
