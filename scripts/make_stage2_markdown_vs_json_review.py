"""Build a standalone review page comparing Markdown (complete-contract)
stage two vs the schema-driven JSON candidate on the fixed benchmark.

Reads ``results/compare_stage2_markdown_vs_json.json`` (produced by
``compare_stage2_markdown_vs_json.py``) and writes a self-contained HTML
page, following the same embedded-``__DATA__`` pattern as the other
``make_*_review.py`` reports in this folder.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SOURCE = Path("results/compare_stage2_markdown_vs_json.json")
OUTPUT = Path("results/stage2_markdown_vs_json_review.html")

TITLE = "MemoSight · stage-2 Markdown(契约) vs JSON"

HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light;
    --canvas:#f4f6f8; --surface:#fff; --surface-subtle:#f8fafc;
    --text:#14181f; --muted:#687180; --border:#dce1e7; --border-strong:#c7ced8;
    --blue:#1769ff; --blue-soft:#edf4ff;
    --green:#12834c; --green-soft:#eaf8f0;
    --red:#d73527; --red-soft:#fff0ee;
    --amber:#9b6500; --amber-soft:#fff7df;
    --radius:11px; --shadow:0 1px 2px rgb(15 23 42 / 4%);
    --sans:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Microsoft YaHei",sans-serif;
    --mono:"SFMono-Regular",Consolas,"Liberation Mono",monospace;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--canvas); color:var(--text);
         font-family:var(--sans); font-size:14px; line-height:1.55; }
  .app-header { position:sticky; top:0; z-index:20; display:flex; align-items:center;
    justify-content:space-between; min-height:64px; padding:10px 22px;
    background:rgb(255 255 255 / 96%); border-bottom:1px solid var(--border); }
  .brand h1 { margin:0; font-size:20px; font-weight:720; letter-spacing:-0.02em; }
  .brand-meta { color:var(--muted); font-size:12px; }
  .toolbar { position:sticky; top:64px; z-index:19; display:flex; align-items:center;
    gap:10px; padding:10px 22px; background:rgb(248 250 252 / 96%);
    border-bottom:1px solid var(--border); }
  .filter-chip { border:1px solid var(--border-strong); background:var(--surface);
    border-radius:999px; padding:6px 12px; cursor:pointer; font-size:13px; }
  .filter-chip.active { background:var(--blue); border-color:var(--blue); color:#fff; }
  main { padding:20px 22px 60px; max-width:1500px; margin:0 auto; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr));
    gap:14px; margin-bottom:18px; }
  .card { background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); padding:14px 16px; box-shadow:var(--shadow); }
  .card .k { color:var(--muted); font-size:12px; }
  .card .v { font-size:22px; font-weight:700; margin-top:2px; letter-spacing:-0.01em; }
  .card .s { font-size:12px; color:var(--muted); margin-top:2px; }
  .good { color:var(--green); } .bad { color:var(--red); } .warn { color:var(--amber); }
  table { border-collapse:collapse; width:100%; background:var(--surface);
    border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--border); font-size:13px; }
  th { background:var(--surface-subtle); font-weight:650; white-space:nowrap; }
  tr:last-child td { border-bottom:none; }
  .bar-wrap { background:#eef1f4; border-radius:4px; height:8px; overflow:hidden; }
  .bar { height:8px; background:var(--blue); }
  section { margin:22px 0 8px; font-size:15px; font-weight:700; }
  .record { background:var(--surface); border:1px solid var(--border);
    border-radius:var(--radius); margin:10px 0; box-shadow:var(--shadow); overflow:hidden; }
  .record-head { display:flex; align-items:center; gap:10px; padding:10px 14px;
    border-bottom:1px solid var(--border); flex-wrap:wrap; }
  .record-head .src { font-family:var(--mono); font-size:12px; color:var(--muted); }
  .badge { font-size:11px; padding:2px 8px; border-radius:999px; font-weight:650; }
  .badge.ok { background:var(--green-soft); color:var(--green); }
  .badge.fail { background:var(--red-soft); color:var(--red); }
  .badge.order { background:var(--blue-soft); color:var(--blue); }
  .caption { padding:8px 14px; background:var(--surface-subtle); font-size:13px;
    color:var(--text); border-bottom:1px solid var(--border); }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:0; }
  .col { padding:12px 14px; min-width:0; }
  .col + .col { border-left:1px solid var(--border); }
  .col h4 { margin:0 0 6px; font-size:13px; display:flex; align-items:center; gap:8px; }
  .meta { font-size:12px; color:var(--muted); display:flex; gap:12px; flex-wrap:wrap; margin-bottom:8px; }
  pre { margin:0; padding:10px; background:#0f172a; color:#dbe6f4; border-radius:8px;
    font-family:var(--mono); font-size:11.5px; line-height:1.5;
    white-space:pre-wrap; word-break:break-word; max-height:340px; overflow:auto; }
  img.thumb { width:100%; max-height:220px; object-fit:cover; border-radius:8px;
    border:1px solid var(--border); display:block; margin-bottom:8px; }
  @media (max-width:900px) { .cols { grid-template-columns:1fr; } .col + .col { border-left:none; border-top:1px solid var(--border); } }
</style>
</head>
<body>
<header class="app-header">
  <div class="brand"><h1>MemoSight · stage-2 对比</h1>
    <span class="brand-meta" id="header-meta">--</span></div>
</header>
<div class="toolbar">
  <span class="brand-meta">筛选：</span>
  <button class="filter-chip active" data-f="all">全部 <b id="c-all"></b></button>
  <button class="filter-chip" data-f="diff">仅不一致 <b id="c-diff"></b></button>
  <button class="filter-chip" data-f="md_fail">仅 Markdown 失败 <b id="c-md"></b></button>
  <button class="filter-chip" data-f="js_fail">仅 JSON 失败 <b id="c-js"></b></button>
</div>
<main>
  <div class="cards" id="cards"></div>
  <section>按字段的平均条目（Markdown vs JSON）</section>
  <div style="overflow-x:auto"><table id="field-table"></table></div>
  <section>逐条记录（配对交替执行）</section>
  <div id="records"></div>
</main>
<script>
const DATA = __DATA__;
const FIELD_KEYS = ["scene_labels","people","actions","objects","lighting","mood","search_tags"];
const FIELD_ZH = {scene_labels:"场景",people:"人物",actions:"动作",objects:"物体",lighting:"光线",mood:"氛围",search_tags:"检索标签"};
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const fmt = n => (typeof n === "number" ? n.toFixed(2) : "—");

function badge(ok, label) { return `<span class="badge ${ok ? "ok" : "fail"}">${label}</span>`; }
function metaCols(side, rec) {
  const d = rec[side];
  const items = d.metrics ? d.metrics.total_items : "—";
  const miss = (d.missing_fields && d.missing_fields.length)
    ? `<span class="badge fail">缺: ${esc(d.missing_fields.join("、"))}</span>` : "";
  return `<div class="meta"><span>${badge(d.status === "ok", d.status === "ok" ? "ok" : "failed")}</span>
    <span>${esc(d.timings_s ? d.timings_s.total.toFixed(2) : "—")}s</span>
    <span>${items} 项</span>${miss}<span class="warn">${esc(d.error || "")}</span></div>`;
}

function renderCards(summary) {
  const md = summary.markdown, js = summary.json, n = summary.caption_count;
  const cards = [
    ["模型", esc(summary.model_id || ""), ""],
    ["固定 caption 数", n, "stage-1 未重跑；逐条交替执行"],
    ["Markdown(契约) ok", `${md.success}/${n}`, "默认 stage-2"],
    ["JSON ok", `${js.success}/${n}`, "候选对比侧"],
    ["Markdown 缺字段失败", md.missing_field_failures ? md.missing_field_failures.length : 0,
        md.missing_field_failures ? "见逐条记录" : ""],
    ["JSON 缺字段失败", js.missing_field_failures ? js.missing_field_failures.length : 0, ""],
    ["Markdown 平均耗时", fmt(md.timing_s.avg) + "s", `p95 ${fmt(md.timing_s.p95)}s`],
    ["JSON 平均耗时", fmt(js.timing_s.avg) + "s", `p95 ${fmt(js.timing_s.p95)}s`],
    ["Markdown 字段项/条", md.field_items_avg.toFixed(2), ""],
    ["JSON 字段项/条", js.field_items_avg.toFixed(2), ""],
  ];
  document.getElementById("cards").innerHTML = cards.map(c =>
    `<div class="card"><div class="k">${c[0]}</div><div class="v">${c[1]}</div><div class="s">${c[2]}</div></div>`).join("");
}

function renderFieldTable(summary) {
  const md = summary.markdown, js = summary.json;
  let rows = `<tr><th>字段</th><th>Markdown avg</th><th>JSON avg</th><th style="width:40%">Markdown/JSON 相对量</th></tr>`;
  for (const k of FIELD_KEYS) {
    const m = md.field_counts_avg[k] || 0, j = js.field_counts_avg[k] || 0;
    const max = Math.max(m, j, 0.001), wj = (j / max * 100).toFixed(0);
    rows += `<tr><td>${FIELD_ZH[k]} <span style="color:var(--muted)">(${k})</span></td>
      <td>${m.toFixed(2)}</td><td>${j.toFixed(2)}</td>
      <td><div class="bar-wrap"><div class="bar" style="width:${wj}%;background:${j >= m ? "var(--green)" : "var(--amber)"}"></div></div></td></tr>`;
  }
  document.getElementById("field-table").innerHTML = rows;
}

function thumb(source) {
  // test_data/* 路径可直接引用本地图片；保留型 caption 来源无本地文件。
  const m = String(source || "").match(/^(test_data\/[^:]+)$/);
  if (!m) return "";
  return `<img class="thumb" src="${esc(m[1])}" loading="lazy" alt="frame" onerror="this.remove()">`;
}

function renderRecord(rec, i) {
  const md = rec.markdown, js = rec.json;
  const cls = [];
  if (md.status !== "ok") cls.push("md_fail");
  if (js.status !== "ok") cls.push("js_fail");
  const order = rec.execution_order === "markdown_first" ? "Markdown 先执行" : "JSON 先执行";
  const srcName = String(rec.source || "").split("/").pop();
  return `<div class="record ${cls.join(" ")}">
    <div class="record-head">
      <span class="src">#${i + 1} · ${esc(srcName)}</span>
      <span class="badge order">${esc(order)}</span>
      ${md.status !== "ok" ? badge(false, "Markdown 失败") : ""}
      ${js.status !== "ok" ? badge(false, "JSON 失败") : ""}
      <span class="src" style="margin-left:auto">${esc(md.timings_s ? md.timings_s.total.toFixed(2) + "s" : "—")} vs ${esc(js.timings_s ? js.timings_s.total.toFixed(2) + "s" : "—")}</span>
    </div>
    ${thumb(rec.source)}
    <div class="caption">${esc(rec.caption)}</div>
    <div class="cols">
      <div class="col">
        <h4><span class="badge ok">Markdown（默认契约模板）</span></h4>
        ${metaCols("markdown", rec)}
        <pre>${esc(md.raw_output ?? "(空)")}</pre>
      </div>
      <div class="col">
        <h4><span class="badge ok">JSON（schema 候选）</span></h4>
        ${metaCols("json", rec)}
        <pre>${esc(js.raw_output ?? "(空)")}</pre>
      </div>
    </div>
  </div>`;
}

function renderAll() {
  const summary = DATA.summary, records = DATA.records || [];
  document.getElementById("header-meta").textContent =
    `${summary.caption_count} 条固定 caption · ${summary.model_id || ""}`;
  renderCards(summary); renderFieldTable(summary);
  document.getElementById("c-all").textContent = records.length;
  document.getElementById("c-diff").textContent = records.filter(r => (r.markdown.status !== "ok") !== (r.json.status !== "ok")).length;
  document.getElementById("c-md").textContent = records.filter(r => r.markdown.status !== "ok").length;
  document.getElementById("c-js").textContent = records.filter(r => r.json.status !== "ok").length;
  const wrap = document.getElementById("records");
  wrap.innerHTML = records.map(renderRecord).join("");
  document.querySelectorAll(".filter-chip").forEach(btn => {
    btn.onclick = () => {
      document.querySelectorAll(".filter-chip").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const f = btn.dataset.f;
      wrap.querySelectorAll(".record").forEach(el => {
        const ok = f === "all" || (f === "diff" && (el.classList.contains("md_fail") !== el.classList.contains("js_fail")))
          || (f === "md_fail" && el.classList.contains("md_fail"))
          || (f === "js_fail" && el.classList.contains("js_fail"));
        el.style.display = ok ? "" : "none";
      });
    };
  });
}
renderAll();
</script>
</body>
</html>
"""


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    html = HTML.replace("__TITLE__", TITLE)
    embedded = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = html.replace("__DATA__", embedded)
    html = html.replace(
        "__GENERATED__",
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
