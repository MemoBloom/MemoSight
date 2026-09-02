"""Build a side-by-side review page for the squat one-stage vs two-stage run.

Reads results/squat_compare_one_vs_two.json (produced by
run_squat_compare.py) and writes results/squat_review/index.html.
Unlike the test_data review (fixed 7-field photography contract), this page
renders whatever fields the custom schema declares.
"""
from __future__ import annotations

import json
from pathlib import Path

SOURCE = Path("results/squat_compare_one_vs_two.json")
OUTPUT_DIR = Path("results/squat_review")

HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MemoSight · Squat 自定义 Schema · 一段式 vs 两段式</title>
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body { margin: 0; padding: 28px 22px 60px; background: #f4f6f8; color: #14181f;
           font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", sans-serif; }
    h1 { margin: 0 0 4px; font-size: 21px; }
    .meta { color: #687180; font-size: 13px; margin-bottom: 18px; }
    .summary { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 22px; }
    .stat { background: #fff; border: 1px solid #dce1e7; border-radius: 10px;
            padding: 10px 14px; font-size: 13px; color: #687180; }
    .stat strong { display: block; color: #14181f; font-size: 18px;
                   font-variant-numeric: tabular-nums; margin-top: 2px; }
    .stat .sub { font-size: 11px; color: #98a1ad; margin-top: 2px; }
    .frames { display: flex; flex-direction: column; gap: 18px; }
    .frame { background: #fff; border: 1px solid #dce1e7; border-radius: 12px; padding: 14px; }
    .frame-head { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
    .frame-head h2 { margin: 0; font-size: 15px; }
    .frame-head .ts { color: #98a1ad; font-size: 12px; }
    .badge { font-size: 11px; padding: 2px 8px; border-radius: 99px; font-weight: 600; }
    .ok { background: #e3f5ea; color: #12834c; }
    .partial { background: #fdf0e0; color: #b26a00; }
    .failed { background: #fde7e4; color: #d73527; }
    .cols { display: grid; grid-template-columns: minmax(220px, 300px) 1fr 1fr; gap: 14px; }
    @media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
    .cols img { width: 100%; border-radius: 8px; background: #11151a; display: block; }
    .col h3 { margin: 0 0 8px; font-size: 13px; color: #687180; font-weight: 600; }
    .col h3 .t { color: #14181f; font-variant-numeric: tabular-nums; }
    .caption { font-size: 12px; color: #414a56; background: #f4f6f8; border-radius: 8px;
               padding: 8px 10px; margin-bottom: 10px; line-height: 1.6; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    td { border-top: 1px solid #eef1f4; padding: 6px 8px; vertical-align: top; line-height: 1.55; }
    td.k { color: #687180; white-space: nowrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
           font-size: 11px; padding-top: 8px; }
    tr.diff td { background: #fff8e6; }
    .chips { display: flex; flex-wrap: wrap; gap: 4px; }
    .chip { background: #eef1f4; border-radius: 6px; padding: 1px 7px; }
    .bool-yes { color: #d73527; font-weight: 700; }
    .bool-no { color: #12834c; font-weight: 700; }
    .enum { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }
    .err { color: #d73527; font-size: 11px; margin-top: 6px; }
    .empty { color: #b6bec9; }
  </style>
</head>
<body>
  <h1>MemoSight · Squat 自定义 Schema · 一段式 vs 两段式</h1>
  <p class="meta" id="meta"></p>
  <div class="summary" id="summary"></div>
  <div class="frames" id="frames"></div>

<script>
const DATA = __DATA__;

const FIELD_LABELS = Object.fromEntries(
  Object.entries(DATA.schema.properties).map(([k, v]) => [k, v.description || k])
);
const FIELD_ORDER = Object.keys(DATA.schema.properties);

document.getElementById('meta').textContent =
  `模型 ${DATA.model_id.split('/').pop()} · ${DATA.records.length} 帧 · ` +
  `两段式 caption → JSON · 交替执行顺序（已预热）`;

function fmt(v) { return v == null ? '—' : v; }
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function renderValue(field, spec, value) {
  if (value == null || (Array.isArray(value) && value.length === 0) || value === '')
    return '<span class="empty">—</span>';
  if (spec.type === 'boolean')
    return value ? '<span class="bool-yes">true · 有风险</span>' : '<span class="bool-no">false · 无风险</span>';
  if (Array.isArray(value))
    return '<div class="chips">' + value.map(v => `<span class="chip">${esc(v)}</span>`).join('') + '</div>';
  if (spec.enum) return `<span class="enum">${esc(value)}</span>`;
  return esc(value);
}

function renderFields(result) {
  const rows = FIELD_ORDER.map(field => {
    const spec = DATA.schema.properties[field];
    const value = result.observation ? result.observation[field] : null;
    return `<tr data-field="${field}"><td class="k">${field}</td><td>${renderValue(field, spec, value)}</td></tr>`;
  }).join('');
  return `<table>${rows}</table>`;
}

function statusBadge(status) {
  const label = {ok: 'ok', partial: 'partial', failed: 'failed'}[status] || status;
  return `<span class="badge ${status}">${label}</span>`;
}

function renderFrame(rec) {
  const one = rec.one_stage, two = rec.two_stage;
  const oneT = one.timings_s.total, twoT = two.timings_s.total;
  const diffCells = FIELD_ORDER.map(f => {
    const a = JSON.stringify(one.observation?.[f] ?? null);
    const b = JSON.stringify(two.observation?.[f] ?? null);
    return a !== b ? f : null;
  }).filter(Boolean);
  const caption = two.caption_raw_output
    ? `<div class="caption"><strong>两段式 caption：</strong>${esc(two.caption_raw_output)}</div>` : '';
  const oneErr = one.error ? `<div class="err">${esc(one.error)}</div>` : '';
  const twoErr = two.error ? `<div class="err">${esc(two.error)}${two.failed_stage ? '（' + two.failed_stage + '）' : ''}</div>` : '';
  const html = `
    <div class="frame">
      <div class="frame-head">
        <h2>${rec.frame}</h2><span class="ts">t≈${rec.timestamp_s.toFixed(1)}s</span>
        ${statusBadge(one.status)} <span class="ts">一段式 ${oneT.toFixed(2)}s</span>
        ${statusBadge(two.status)} <span class="ts">两段式 ${twoT.toFixed(2)}s（caption ${two.timings_s.caption_model.toFixed(2)}s + fields ${two.timings_s.field_model.toFixed(2)}s）</span>
      </div>
      <div class="cols">
        <div><img src="../../${rec.frame_path}" loading="lazy" alt="${rec.frame}"></div>
        <div class="col"><h3>一段式 JSON <span class="t">${oneT.toFixed(2)}s</span></h3>${renderFields(one)}${oneErr}</div>
        <div class="col"><h3>两段式（caption → JSON）<span class="t">${twoT.toFixed(2)}s</span></h3>${caption}${renderFields(two)}${twoErr}</div>
      </div>
    </div>`;
  return {html, diffCells};
}

const container = document.getElementById('frames');
let diffFieldCount = {};
DATA.records.forEach(rec => {
  const {html, diffCells} = renderFrame(rec);
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html;
  const el = wrapper.firstElementChild;
  // 标记两段结果不一致的字段行
  el.querySelectorAll('.cols .col').forEach(col => {
    col.querySelectorAll('tr').forEach(tr => {
      if (diffCells.includes(tr.dataset.field)) tr.classList.add('diff');
    });
  });
  diffCells.forEach(f => diffFieldCount[f] = (diffFieldCount[f] || 0) + 1);
  container.appendChild(el);
});

const s = DATA.summary;
const n = s.frame_count;
document.getElementById('summary').innerHTML = `
  <div class="stat">一段式<strong>${s.one_stage.avg_s.toFixed(2)}s</strong><span class="sub">${s.one_stage_ok}/${n} ok</span></div>
  <div class="stat">两段式<strong>${s.two_stage.avg_s.toFixed(2)}s</strong><span class="sub">${s.two_stage_ok}/${n} ok · ${s.two_stage_partial} partial</span></div>
  <div class="stat">耗时变化<strong>${s.two_stage_vs_one_stage_pct >= 0 ? '+' : ''}${s.two_stage_vs_one_stage_pct.toFixed(1)}%</strong><span class="sub">两段式相对一段式</span></div>
  <div class="stat">字段分歧<strong>${Object.entries(diffFieldCount).map(([f, c]) => `${f} ${c}/${n}`).join(' · ') || '无'}</strong><span class="sub">两方案结果不一致的字段</span></div>`;
</script>
</body>
</html>
"""


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    out = OUTPUT_DIR / "index.html"
    out.write_text(HTML.replace("__DATA__", embedded), encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
