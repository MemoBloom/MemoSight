# 默认 profile 二阶段升级为 schema-driven JSON — 设计

日期：2026-09-03
依据：`test_data/report/liuwenlong-0903`（问题 1：两阶段固定 Markdown 字段抽取偶发丢字段 → partial 9/92）

## 背景与目标

默认 profile（`photography_default`）的两阶段 pipeline 中，stage-2 目前使用固定
Markdown 模板抽取 7 个字段，小模型偶尔漏输出一两个字段（如 `search_tags`），
触发"缺字段"校验失败 → `status=partial`。报告建议改用 schema 驱动 JSON 抽取。

**目标**：默认 profile 的 stage-2 从固定 Markdown 切换为 schema-driven JSON，
降低丢字段导致的 partial 率，并用配对基准验证效果。

**非目标**：

- 不改 stage-1（caption 生成）。
- 不改一阶段 pipeline（`pipeline.py` 的 Markdown 兜底保留）。
- 不删除 legacy Markdown 代码（`parse_markdown_fields`、
  `build_caption_field_extraction_prompt` 仍被单阶段兜底、导出和基准脚本使用）。
- 不改对外结果契约：`observation` / `default_observation` / `MemoSightObservation`
  形状不变。

## 生产代码改动

### 1. `memosight/profiles.py`

新增 stage-2 专用 schema 常量 `_PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA`：
从 `_PHOTOGRAPHY_DEFAULT_SCHEMA` 去掉 `caption`，只含 7 个数组字段，
`required` = 全部 7 个键。

理由：caption 由 stage-1 产出并钉死（pin），要求模型在二阶段重新生成约 100 字
caption 会浪费输出 token 并增加 192~224 token 预算内截断的风险；去掉后输出规模
与现有 Markdown 模板相当，可比性也更好（"模型是否丢字段"这一变量一致）。

### 2. `memosight/two_stage.py`

`_extract_fields_for_profile` 的默认分支改为：

1. 用 `build_caption_structured_extraction_prompt` 构造 prompt，传入一个
   `output_schema=_PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA` 的 profile 视图
   （复用默认 profile 的 instructions）。
2. `parse_model_output` 解析（已有 strict → fenced → embedded 三级容错）。
3. 解析失败 → 与现状一致：`status=failed`（上层 `analyze` 映射为 `partial`，
   caption 仍可用），`fields=empty_caption_fields()`。
4. 解析成功 → `normalize_caption_fields(parsed.data)` 归一化（复用现有的
   去重、去 unknown、字符串转单元素数组、截断 6 项逻辑）。
5. 用 `validator.validate_custom(fields, _PHOTOGRAPHY_DEFAULT_FIELDS_SCHEMA)`
   校验：7 个字段全部 required（与现状"7 行齐全"严格度一致）、数组类型、
   maxItems=6。
6. 成功后 `observation = MemoSightObservation(caption=caption, **fields)`，
   与现状一致。

失败语义、usage 字段（`structured_output_duration_s`、`postprocess_duration_s`、
`parse_strategy`）保持不变；`parse_strategy` 变为 JSON 解析策略
（strict/fenced/embedded）。

### 3. `memosight/config/default_prompts.json` + `memosight/prompts.py`

- `caption_json_stage`（zh/en）增加 `max_tokens: 224`（略高于 Markdown 的 192，
  覆盖 JSON 结构开销，降低截断风险）。
- `build_caption_structured_extraction_prompt` 读取该 `max_tokens` 并填入
  `MemoSightPrompt`（目前该函数不支持 max_tokens）。

现有 `caption_json_stage` 规则已包含"数组用空数组、不要省略字段名"，正对
丢字段故障模式，无需改规则文案。

## 评测

新增 `scripts/compare_stage2_markdown_vs_json.py`（模式参考
`compare_stage2_prompts.py`，自包含编排两条路径，不给 pipeline 加开关）：

- **Caption 源（固定，stage-1 只跑一次并缓存）**：
  - `results/compare_one_stage_vs_two_stage_736x416.json`（20 条）
    + `results/squat_compare_one_vs_two.json`（10 条）中已有的
    `two_stage.caption_raw_output`；
  - `test_data/` 9 个目录 × 10 帧 = 90 张帧，用 stage-1 caption prompt 经
    MLX server 生成 caption，写入 `results/stage2_caption_cache.json` 缓存；
    已缓存则不重跑视觉。
- **配对执行**：对每条固定 caption 分别跑 Markdown 基线（脚本内用
  `build_caption_field_extraction_prompt` + `parse_markdown_fields` +
  缺字段校验复现旧逻辑）和 JSON 候选（直接调用
  `pipeline.extract_fields()`，即切换后的生产路径），逐条交替执行顺序。
- **指标**：success 数（ok vs failed）、耗时统计（avg/p50/p95）、
  completion tokens、每字段条目数；缺字段失败列出缺失字段名。
- **产物**：`results/compare_stage2_markdown_vs_json.json` +
  同名 `.md` 报告。

**判定**：success 数提升（基线预期有缺字段失败）且字段丰富度（每字段条目数）
不明显下降，即为有效提升。

## 测试

- `tests/test_two_stage_pipeline.py`：默认 profile 二阶段用例改为 JSON 输出
  （7 字段 JSON → ok；缺 `search_tags` 的 JSON → failed/partial 且报缺失字段；
  非 JSON 输出 → failed）。
- `tests/test_memosight_prompts.py`：默认 profile 的 stage-2 prompt 断言
  JSON 字段定义包含全部 7 个字段且不含 caption。
- Markdown 解析器的既有测试不动。

## 错误处理与兼容性

- 解析或校验失败 → `partial`（caption 保留、`extract_fields` 可独立重试），
  与现状一致，无硬失败。
- `cli.py`、一阶段 `pipeline.py` 不受影响。
- `build_caption_field_extraction_prompt`、`parse_markdown_fields`、
  `find_markdown_field_keys` 及其导出保留。
