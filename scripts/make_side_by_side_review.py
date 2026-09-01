"""Build a standalone side-by-side annotation review webpage."""
from __future__ import annotations

import json
from pathlib import Path

SOURCE = Path("results/compare_one_stage_vs_two_stage_736x416.json")
OUTPUT = Path("results/side_by_side_review.html")

HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MemoSight · 标注结果对比</title>
  <style>
    :root {
      color-scheme: light;
      --canvas: #f4f6f8;
      --surface: #ffffff;
      --surface-subtle: #f8fafc;
      --text: #14181f;
      --muted: #687180;
      --border: #dce1e7;
      --border-strong: #c7ced8;
      --blue: #1769ff;
      --blue-soft: #edf4ff;
      --green: #12834c;
      --green-soft: #eaf8f0;
      --red: #d73527;
      --red-soft: #fff0ee;
      --amber: #9b6500;
      --amber-soft: #fff7df;
      --radius: 11px;
      --shadow: 0 1px 2px rgb(15 23 42 / 4%);
      --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif;
      --mono: "SFMono-Regular", Consolas, "Liberation Mono", monospace;
    }

    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      min-width: 320px;
      background: var(--canvas);
      color: var(--text);
      font-family: var(--sans);
      font-size: 14px;
      line-height: 1.55;
    }
    button, input { font: inherit; }
    button { color: inherit; }
    button:focus-visible, input:focus-visible {
      outline: 3px solid rgb(23 105 255 / 24%);
      outline-offset: 2px;
    }

    .app-header {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 64px;
      padding: 10px 22px;
      background: rgb(255 255 255 / 96%);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(14px);
    }
    .brand {
      display: flex;
      align-items: baseline;
      gap: 10px;
      min-width: 0;
    }
    .brand h1 {
      margin: 0;
      font-size: 21px;
      font-weight: 720;
      letter-spacing: -0.02em;
      white-space: nowrap;
    }
    .brand-meta {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .summary-line {
      display: flex;
      align-items: center;
      gap: 18px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .summary-line strong { color: var(--text); font-weight: 650; }
    .summary-line .improvement { color: var(--green); }

    .toolbar {
      position: sticky;
      top: 64px;
      z-index: 19;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 22px;
      background: rgb(248 250 252 / 96%);
      border-bottom: 1px solid var(--border);
      backdrop-filter: blur(12px);
    }
    .toolbar-spacer { flex: 1; }
    .button, .filter-button {
      min-height: 36px;
      padding: 7px 12px;
      background: var(--surface);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      cursor: pointer;
      transition: background 140ms ease, border-color 140ms ease, color 140ms ease;
    }
    .button:hover, .filter-button:hover { background: #f1f5f9; }
    .button:disabled { opacity: 0.42; cursor: not-allowed; }
    .nav-button { display: inline-flex; align-items: center; gap: 7px; }
    .nav-button svg { width: 15px; height: 15px; }
    .counter {
      min-width: 66px;
      text-align: center;
      font-variant-numeric: tabular-nums;
      font-weight: 660;
    }
    .filters {
      display: inline-flex;
      gap: 4px;
      padding: 3px;
      background: #e9edf2;
      border-radius: 9px;
    }
    .filter-button {
      min-height: 30px;
      padding: 4px 11px;
      border: 0;
      background: transparent;
    }
    .filter-button[aria-pressed="true"] {
      color: #fff;
      background: var(--blue);
    }
    .raw-toggle { display: inline-flex; align-items: center; gap: 8px; }
    .raw-toggle input { width: 15px; height: 15px; accent-color: var(--blue); }

    main { padding: 14px 22px 24px; }
    .workspace {
      display: grid;
      grid-template-columns: minmax(420px, 0.92fr) minmax(640px, 1.28fr);
      gap: 14px;
      align-items: start;
    }
    .media-column, .comparison-column { min-width: 0; }
    .media-frame {
      overflow: hidden;
      position: relative;
      aspect-ratio: 736 / 416;
      background: #e7ebf0;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      cursor: zoom-in;
    }
    .media-frame img {
      display: block;
      width: 100%;
      height: 100%;
      object-fit: contain;
      background: #11151a;
    }
    .media-caption {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 9px 2px 0;
      color: var(--muted);
      font-size: 12px;
    }
    .media-caption strong { color: var(--text); font-family: var(--mono); }

    .timing-panel {
      margin-top: 13px;
      padding: 14px 15px 13px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .timing-heading {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 12px;
    }
    .timing-heading h2 { margin: 0; font-size: 14px; }
    .timing-delta { font-size: 13px; font-weight: 680; font-variant-numeric: tabular-nums; }
    .timing-delta.faster { color: var(--green); }
    .timing-delta.slower { color: var(--red); }
    .timing-row {
      display: grid;
      grid-template-columns: 116px 1fr 62px;
      gap: 10px;
      align-items: center;
      margin: 8px 0;
      font-size: 12px;
    }
    .timing-track { height: 10px; overflow: hidden; background: #edf0f3; border-radius: 3px; }
    .timing-fill { height: 100%; min-width: 2px; border-radius: 3px; transition: width 220ms ease; }
    .timing-fill.one { background: #88a8dc; }
    .timing-fill.two { background: #55b77d; }
    .timing-value { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; }
    .stage-split {
      margin-top: 11px;
      padding-top: 10px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
    }

    .results-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .result-panel {
      overflow: hidden;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .result-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      min-height: 51px;
      padding: 11px 14px;
      border-bottom: 1px solid var(--border);
    }
    .result-title { margin: 0; font-size: 15px; letter-spacing: -0.01em; }
    .result-meta { display: flex; align-items: center; gap: 8px; }
    .latency { font-family: var(--mono); font-size: 12px; font-weight: 680; font-variant-numeric: tabular-nums; }
    .status {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
    }
    .status.ok { color: var(--green); background: var(--green-soft); }
    .status.failed { color: var(--red); background: var(--red-soft); }
    .status.partial { color: var(--amber); background: var(--amber-soft); }
    .caption-block {
      min-height: 128px;
      padding: 13px 14px 14px;
      background: var(--surface-subtle);
      border-bottom: 1px solid var(--border);
    }
    .section-label {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .caption-text { margin: 0; line-height: 1.72; }
    .field-list { margin: 0; }
    .field-row {
      display: grid;
      grid-template-columns: 112px minmax(0, 1fr);
      min-height: 54px;
      border-bottom: 1px solid var(--border);
    }
    .field-row:last-child { border-bottom: 0; }
    .field-row.different { background: #fbfcff; }
    .field-name {
      margin: 0;
      padding: 14px 10px 12px 14px;
      border-right: 1px solid var(--border);
      color: #303846;
      font-family: var(--mono);
      font-size: 11px;
      font-weight: 650;
      word-break: break-word;
    }
    .field-values {
      display: flex;
      flex-wrap: wrap;
      align-content: center;
      gap: 5px;
      margin: 0;
      padding: 10px 12px;
    }
    .value {
      display: inline-block;
      max-width: 100%;
      padding: 3px 7px;
      background: #f0f3f7;
      border: 1px solid #e1e6ec;
      border-radius: 5px;
      font-size: 12px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }
    .empty { color: #98a1ad; font-style: normal; }
    .error-box {
      margin: 12px;
      padding: 10px 11px;
      color: #95251c;
      background: var(--red-soft);
      border: 1px solid #ffd1cb;
      border-radius: 7px;
      font-size: 12px;
    }
    .raw-block { display: none; padding: 12px; border-top: 1px solid var(--border); }
    .show-raw .raw-block { display: block; }
    .raw-block pre {
      max-height: 290px;
      margin: 0;
      padding: 11px;
      overflow: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      color: #263140;
      background: #f4f6f8;
      border: 1px solid var(--border);
      border-radius: 7px;
      font: 11px/1.6 var(--mono);
    }
    .raw-secondary { margin-top: 9px !important; }

    .filmstrip-section {
      margin-top: 14px;
      padding: 12px 12px 9px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }
    .filmstrip-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      padding: 0 2px 8px;
    }
    .filmstrip-header h2 { margin: 0; font-size: 13px; }
    .filmstrip-header span { color: var(--muted); font-size: 11px; }
    .filmstrip {
      display: flex;
      gap: 8px;
      overflow-x: auto;
      overscroll-behavior-inline: contain;
      scrollbar-width: thin;
      padding: 2px 2px 6px;
    }
    .thumb {
      flex: 0 0 104px;
      padding: 3px;
      background: transparent;
      border: 2px solid transparent;
      border-radius: 8px;
      cursor: pointer;
      text-align: left;
    }
    .thumb:hover { background: #f2f5f8; }
    .thumb[aria-current="true"] { border-color: var(--blue); background: var(--blue-soft); }
    .thumb img {
      display: block;
      width: 100%;
      aspect-ratio: 736 / 416;
      object-fit: cover;
      background: #e7ebf0;
      border-radius: 4px;
    }
    .thumb-meta {
      display: flex;
      justify-content: space-between;
      gap: 5px;
      padding: 4px 1px 0;
      color: var(--muted);
      font: 10px/1.3 var(--mono);
    }
    .thumb-state { width: 7px; height: 7px; margin-top: 2px; border-radius: 50%; background: var(--green); }
    .thumb-state.failed { background: var(--red); }

    .empty-state {
      display: none;
      padding: 80px 20px;
      text-align: center;
      color: var(--muted);
    }
    .empty-state.visible { display: block; }

    .lightbox {
      position: fixed;
      inset: 0;
      z-index: 50;
      display: none;
      place-items: center;
      padding: 30px;
      background: rgb(9 13 18 / 86%);
    }
    .lightbox.open { display: grid; }
    .lightbox img { max-width: 94vw; max-height: 90vh; object-fit: contain; border-radius: 8px; }
    .lightbox button {
      position: absolute;
      top: 18px;
      right: 20px;
      width: 40px;
      height: 40px;
      color: white;
      background: rgb(255 255 255 / 14%);
      border: 1px solid rgb(255 255 255 / 25%);
      border-radius: 50%;
      cursor: pointer;
      font-size: 20px;
    }

    @media (max-width: 1120px) {
      .workspace { grid-template-columns: 1fr; }
      .media-column { display: grid; grid-template-columns: 1.4fr 0.8fr; gap: 12px; }
      .timing-panel { margin-top: 0; }
      .brand-meta, .summary-line { display: none; }
    }
    @media (max-width: 760px) {
      .app-header { min-height: 54px; padding: 9px 13px; }
      .brand h1 { font-size: 17px; }
      .toolbar { top: 54px; padding: 8px 12px; flex-wrap: wrap; }
      .toolbar-spacer { display: none; }
      .raw-toggle { margin-left: auto; }
      main { padding: 10px 10px 18px; }
      .media-column { display: block; }
      .timing-panel { margin-top: 10px; }
      .results-grid { grid-template-columns: 1fr; }
      .caption-block { min-height: 0; }
      .field-row { grid-template-columns: 104px minmax(0, 1fr); }
      .filmstrip-section { margin-top: 10px; }
      .thumb { flex-basis: 90px; }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      *, *::before, *::after { transition-duration: 0.01ms !important; }
    }
  </style>
</head>
<body>
  <header class="app-header">
    <div class="brand">
      <h1>MemoSight · 标注结果对比</h1>
      <span class="brand-meta" id="modelMeta"></span>
    </div>
    <div class="summary-line" aria-label="整体性能摘要">
      <span>单阶段 <strong id="oneAvg"></strong></span>
      <span>两阶段 <strong id="twoAvg"></strong></span>
      <span>平均提速 <strong class="improvement" id="improvement"></strong></span>
    </div>
  </header>

  <nav class="toolbar" aria-label="帧浏览工具栏">
    <button class="button nav-button" id="prevButton" type="button">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>
      上一帧
    </button>
    <button class="button nav-button" id="nextButton" type="button">
      下一帧
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>
    </button>
    <span class="counter" id="counter" aria-live="polite"></span>
    <div class="filters" aria-label="结果筛选">
      <button class="filter-button" type="button" data-filter="all" aria-pressed="true">全部</button>
      <button class="filter-button" type="button" data-filter="success" aria-pressed="false">成功</button>
      <button class="filter-button" type="button" data-filter="failure" aria-pressed="false">失败</button>
    </div>
    <span class="toolbar-spacer"></span>
    <label class="raw-toggle button"><input id="rawToggle" type="checkbox">显示原始输出</label>
  </nav>

  <main>
    <div id="reviewSurface">
      <div class="workspace">
        <section class="media-column" aria-label="当前图像与耗时">
          <div>
            <div class="media-frame" id="mediaFrame" title="点击查看大图">
              <img id="mainImage" alt="当前比较帧">
            </div>
            <div class="media-caption">
              <strong id="frameName"></strong>
              <span id="timestamp"></span>
            </div>
          </div>
          <section class="timing-panel" aria-labelledby="timingTitle">
            <div class="timing-heading">
              <h2 id="timingTitle">延迟对比</h2>
              <span class="timing-delta" id="timingDelta"></span>
            </div>
            <div class="timing-row">
              <span>单阶段 JSON</span>
              <div class="timing-track"><div class="timing-fill one" id="oneBar"></div></div>
              <span class="timing-value" id="oneTime"></span>
            </div>
            <div class="timing-row">
              <span>两阶段</span>
              <div class="timing-track"><div class="timing-fill two" id="twoBar"></div></div>
              <span class="timing-value" id="twoTime"></span>
            </div>
            <div class="stage-split" id="stageSplit"></div>
          </section>
        </section>

        <section class="comparison-column" aria-label="结构化结果并排对比">
          <div class="results-grid">
            <article class="result-panel" id="onePanel">
              <header class="result-header">
                <h2 class="result-title">单阶段 JSON</h2>
                <div class="result-meta"><span class="latency" id="oneLatency"></span><span class="status" id="oneStatus"></span></div>
              </header>
              <div class="caption-block"><span class="section-label">Caption</span><p class="caption-text" id="oneCaption"></p></div>
              <dl class="field-list" id="oneFields"></dl>
              <div id="oneError"></div>
              <div class="raw-block"><span class="section-label">Raw output</span><pre id="oneRaw"></pre></div>
            </article>

            <article class="result-panel" id="twoPanel">
              <header class="result-header">
                <h2 class="result-title">两阶段 Caption → Fields</h2>
                <div class="result-meta"><span class="latency" id="twoLatency"></span><span class="status" id="twoStatus"></span></div>
              </header>
              <div class="caption-block"><span class="section-label">Caption</span><p class="caption-text" id="twoCaption"></p></div>
              <dl class="field-list" id="twoFields"></dl>
              <div id="twoError"></div>
              <div class="raw-block">
                <span class="section-label">Caption raw output</span><pre id="twoCaptionRaw"></pre>
                <span class="section-label" style="margin-top:10px">Fields raw output</span><pre class="raw-secondary" id="twoFieldsRaw"></pre>
              </div>
            </article>
          </div>
        </section>
      </div>

      <section class="filmstrip-section" aria-labelledby="filmstripTitle">
        <div class="filmstrip-header"><h2 id="filmstripTitle">全部帧</h2><span>点击缩略图切换 · 方向键浏览</span></div>
        <div class="filmstrip" id="filmstrip"></div>
      </section>
    </div>
    <div class="empty-state" id="emptyState">当前筛选条件下没有结果。</div>
  </main>

  <div class="lightbox" id="lightbox" role="dialog" aria-modal="true" aria-label="图像大图预览">
    <button id="closeLightbox" type="button" aria-label="关闭大图">×</button>
    <img id="lightboxImage" alt="当前帧大图">
  </div>

  <script id="dataset" type="application/json">__DATA__</script>
  <script>
    (() => {
      const data = JSON.parse(document.getElementById('dataset').textContent);
      const fields = ['scene_labels', 'people', 'actions', 'objects', 'lighting', 'mood', 'search_tags'];
      const emptyTokens = new Set(['none', 'null', 'unknown', '无', '没有', '无内容']);
      const state = { filter: 'all', visible: [], current: 0 };
      const $ = (id) => document.getElementById(id);

      const imageUrl = (record) => new URL('../' + record.frame_path, window.location.href).href;
      const statusLabel = (status) => ({ ok: '成功', failed: '失败', partial: '部分成功' }[status] || status);
      const formatTime = (seconds) => `${Number(seconds).toFixed(3)} s`;
      const normalizeValues = (value) => {
        if (!Array.isArray(value)) return [];
        return value.filter((item) => !emptyTokens.has(String(item).trim().toLowerCase()));
      };
      const isFailure = (record) => record.one_stage.status !== 'ok' || record.two_stage.status !== 'ok';
      const matches = (record) => state.filter === 'all' || (state.filter === 'failure' ? isFailure(record) : !isFailure(record));

      function setStatus(element, status) {
        element.className = `status ${status}`;
        element.textContent = statusLabel(status);
      }

      function renderFieldList(container, observation, otherObservation) {
        container.replaceChildren();
        fields.forEach((field) => {
          const values = normalizeValues(observation?.[field]);
          const otherValues = normalizeValues(otherObservation?.[field]);
          const row = document.createElement('div');
          row.className = 'field-row' + (JSON.stringify(values) !== JSON.stringify(otherValues) ? ' different' : '');
          const name = document.createElement('dt');
          name.className = 'field-name';
          name.textContent = field;
          const valueList = document.createElement('dd');
          valueList.className = 'field-values';
          if (!values.length) {
            const empty = document.createElement('span');
            empty.className = 'empty';
            empty.textContent = '—';
            valueList.append(empty);
          } else {
            values.forEach((value) => {
              const token = document.createElement('span');
              token.className = 'value';
              token.textContent = value;
              valueList.append(token);
            });
          }
          row.append(name, valueList);
          container.append(row);
        });
      }

      function renderError(container, result) {
        container.replaceChildren();
        if (!result.error && !(result.issues || []).length) return;
        const box = document.createElement('div');
        box.className = 'error-box';
        box.textContent = [result.error, ...(result.issues || [])].filter(Boolean).join(' · ');
        container.append(box);
      }

      function updateTiming(record) {
        const one = record.one_stage.timings_s.total;
        const two = record.two_stage.timings_s.total;
        const max = Math.max(one, two, 0.001);
        $('oneBar').style.width = `${one / max * 100}%`;
        $('twoBar').style.width = `${two / max * 100}%`;
        $('oneTime').textContent = formatTime(one);
        $('twoTime').textContent = formatTime(two);
        const delta = two - one;
        const percentage = delta / one * 100;
        $('timingDelta').className = `timing-delta ${delta <= 0 ? 'faster' : 'slower'}`;
        $('timingDelta').textContent = `${delta <= 0 ? '快' : '慢'} ${Math.abs(delta).toFixed(3)} s (${Math.abs(percentage).toFixed(1)}%)`;
        $('stageSplit').textContent = `两阶段拆分：Caption ${formatTime(record.two_stage.timings_s.caption_model)} · Fields ${formatTime(record.two_stage.timings_s.field_model)} · 后处理 ${(record.two_stage.timings_s.postprocess * 1000).toFixed(3)} ms`;
      }

      function updateFilmstrip(recordIndex) {
        document.querySelectorAll('.thumb').forEach((button) => {
          const selected = Number(button.dataset.index) === recordIndex;
          button.setAttribute('aria-current', String(selected));
          if (selected) button.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
        });
      }

      function renderCurrent() {
        const recordIndex = state.visible[state.current];
        const record = data.records[recordIndex];
        if (!record) return;
        const src = imageUrl(record);
        $('mainImage').src = src;
        $('mainImage').alt = `${record.frame} 比较帧`;
        $('lightboxImage').src = src;
        $('frameName').textContent = record.frame;
        $('timestamp').textContent = `视频时间 ${record.timestamp_s.toFixed(1)} s · 执行顺序 ${record.execution_order === 'one_stage_first' ? '单阶段优先' : '两阶段优先'}`;
        $('counter').textContent = `${state.current + 1} / ${state.visible.length}`;
        $('prevButton').disabled = state.current === 0;
        $('nextButton').disabled = state.current >= state.visible.length - 1;

        $('oneLatency').textContent = formatTime(record.one_stage.timings_s.total);
        $('twoLatency').textContent = formatTime(record.two_stage.timings_s.total);
        setStatus($('oneStatus'), record.one_stage.status);
        setStatus($('twoStatus'), record.two_stage.status);
        $('oneCaption').textContent = record.one_stage.observation?.caption || '—';
        $('twoCaption').textContent = record.two_stage.observation?.caption || '—';
        renderFieldList($('oneFields'), record.one_stage.observation, record.two_stage.observation);
        renderFieldList($('twoFields'), record.two_stage.observation, record.one_stage.observation);
        renderError($('oneError'), record.one_stage);
        renderError($('twoError'), record.two_stage);
        $('oneRaw').textContent = record.one_stage.raw_output || '—';
        $('twoCaptionRaw').textContent = record.two_stage.caption_raw_output || '—';
        $('twoFieldsRaw').textContent = record.two_stage.structured_raw_output || '—';
        updateTiming(record);
        updateFilmstrip(recordIndex);
        history.replaceState(null, '', `#${record.frame.replace('.jpg', '')}`);
      }

      function rebuildVisible(preferredRecordIndex = null) {
        state.visible = data.records.map((_, index) => index).filter((index) => matches(data.records[index]));
        const preferredPosition = preferredRecordIndex === null ? -1 : state.visible.indexOf(preferredRecordIndex);
        state.current = preferredPosition >= 0 ? preferredPosition : 0;
        const empty = !state.visible.length;
        $('reviewSurface').hidden = empty;
        $('emptyState').classList.toggle('visible', empty);
        document.querySelectorAll('.thumb').forEach((button) => {
          button.hidden = !state.visible.includes(Number(button.dataset.index));
        });
        if (!empty) renderCurrent();
      }

      function buildFilmstrip() {
        const strip = $('filmstrip');
        data.records.forEach((record, index) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'thumb';
          button.dataset.index = index;
          button.setAttribute('aria-label', `查看 ${record.frame}`);
          const image = document.createElement('img');
          image.src = imageUrl(record);
          image.alt = '';
          image.loading = index < 8 ? 'eager' : 'lazy';
          const meta = document.createElement('span');
          meta.className = 'thumb-meta';
          const filename = document.createElement('span');
          filename.textContent = record.frame.replace('.jpg', '');
          const indicator = document.createElement('span');
          indicator.className = `thumb-state ${isFailure(record) ? 'failed' : ''}`;
          indicator.title = isFailure(record) ? '包含失败结果' : '两种方案均成功';
          meta.append(filename, indicator);
          button.append(image, meta);
          button.addEventListener('click', () => {
            state.current = state.visible.indexOf(index);
            renderCurrent();
            window.scrollTo({ top: 0, behavior: 'smooth' });
          });
          strip.append(button);
        });
      }

      function navigate(delta) {
        const next = Math.max(0, Math.min(state.visible.length - 1, state.current + delta));
        if (next !== state.current) {
          state.current = next;
          renderCurrent();
        }
      }

      const summary = data.summary;
      $('modelMeta').textContent = summary.model_id.split('/').pop();
      $('oneAvg').textContent = formatTime(summary.one_stage.avg_s);
      $('twoAvg').textContent = formatTime(summary.two_stage.avg_s);
      $('improvement').textContent = `${Math.abs(summary.two_stage_vs_one_stage_pct).toFixed(1)}%`;
      buildFilmstrip();

      const hashFrame = location.hash.slice(1);
      const hashIndex = data.records.findIndex((record) => record.frame.startsWith(hashFrame));
      rebuildVisible(hashIndex >= 0 ? hashIndex : 0);

      $('prevButton').addEventListener('click', () => navigate(-1));
      $('nextButton').addEventListener('click', () => navigate(1));
      $('rawToggle').addEventListener('change', (event) => {
        $('reviewSurface').classList.toggle('show-raw', event.target.checked);
      });
      document.querySelectorAll('.filter-button').forEach((button) => {
        button.addEventListener('click', () => {
          const currentRecordIndex = state.visible[state.current];
          state.filter = button.dataset.filter;
          document.querySelectorAll('.filter-button').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
          rebuildVisible(currentRecordIndex);
        });
      });
      document.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowLeft') navigate(-1);
        if (event.key === 'ArrowRight') navigate(1);
        if (event.key === 'Escape') $('lightbox').classList.remove('open');
      });
      $('mediaFrame').addEventListener('click', () => $('lightbox').classList.add('open'));
      $('closeLightbox').addEventListener('click', () => $('lightbox').classList.remove('open'));
      $('lightbox').addEventListener('click', (event) => {
        if (event.target === $('lightbox')) $('lightbox').classList.remove('open');
      });
    })();
  </script>
</body>
</html>
'''


def main() -> None:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    embedded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    OUTPUT.write_text(HTML.replace("__DATA__", embedded), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
