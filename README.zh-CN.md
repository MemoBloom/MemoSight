<p align="center">
  <img src="https://raw.githubusercontent.com/MemoBloom/MemoSight/main/assets/readme/hero.svg" width="100%" alt="MemoSight — 图片进，结构化 JSON 出。通过本地 mlx-vlm 服务器完成视觉理解，输出经过校验、可直接供算法使用，无需云端 API。">
</p>

<p align="center">
  <a href="README.md">English</a> | 简体中文
</p>

MemoSight 是一个可复用的「图片 → 结构化视觉文本」模块与 CLI。它接受图片
路径或内存中的图片数据，通过可配置的后端完成视觉理解，对结构化输出进行
校验（可选修复），并返回一个稳定的、算法友好的 JSON 对象——字段包括
caption、场景标签、可见人物、动作、物体、光线、氛围和搜索标签等。

它抽取自 MemoBrain 摄影工作流系统，但不依赖 MemoBrain：核心模块只依赖
Python 标准库和 Pydantic。

## 为什么选择 MemoSight

- **是契约，不是聊天回复。** 每个响应都会按照类型化 schema 进行解析、
  归一化和校验——调用方拿到的是稳定的 JSON 对象，而不是原始模型文本。
- **本地优先。** 默认后端与本地
  [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) 服务器通信。无需云端
  API key，数据不离开本机。
- **面向你的领域的 schema。** 五个内置 profile（`photography_default`、
  `wedding_selection`、`portrait_review`、`product_catalog`、
  `event_coverage`）、一个 `custom` profile，以及支持 `required`、
  `enum`、`maxItems` 的有界自定义 JSON schema。
- **你的 prompt，你的 schema。** 所有 prompt 文本都是内置配置而非代码：
  可以通过 `prompt_config` 按请求覆盖任意 prompt，用 `prompt_plan`
  注入 prompt 方案（逐字段指导、do/don't 规则），并在消耗任何一次模型
  调用之前用 `memosight prompt` 预览最终 prompt。
- **小模型可用的两段式方案。** 将视觉理解拆分为「图片→caption」和
  「caption→字段」两次调用——在小型本地 VLM 上约快 1.9 倍且更可靠
  （见基准测试），第二阶段可独立重试。
- **双语 prompt。** 同一份 schema 可生成中文或英文 prompt。
- **纯粹且可插拔。** 无持久化、无数据库、无搜索索引——有纯性守护测试
  在导入时强制约束。实现一个小的异步协议即可替换任意后端。
- **灵活的输入。** 文件路径、原始字节或 base64 数据；临时文件会自动
  物化并清理。

## 默认输出契约

```json
{
  "caption": "string (non-empty)",
  "scene_labels": ["string, max 6"],
  "people": ["string, max 6"],
  "actions": ["string, max 6"],
  "objects": ["string, max 6"],
  "lighting": ["string, max 6"],
  "mood": ["string, max 6"],
  "search_tags": ["string, max 6"]
}
```

人物字段只描述可见的角色/主体——MemoSight 绝不推断真实身份。

## 工作原理

<p align="center">
  <img src="https://raw.githubusercontent.com/MemoBloom/MemoSight/main/assets/readme/pipeline.svg" width="100%" alt="MemoSight 流水线：图片源、prompt 构建、本地 mlx-vlm 后端，然后跨越信任边界进行严格解析、归一化和校验，产出经过验证的 MemoSightResult。">
</p>

后端返回原始模型输出文本；解析、归一化和校验都是流水线的职责——后端
输出永远不被信任。

## 基准测试

测试环境：Apple M5（32 GB），本地 Qwen3.5-2B-MLX-4bit，由
`mlx_vlm.server` 提供服务。8 个短视频（美食、旅行、开箱、vlog——每个
207s 到 1047s），每个视频均匀抽取 20 帧，共 160 帧，预热后交替执行
顺序。

| 视频 | 一段式 JSON | 两段式 | 加速比 |
| --- | ---: | ---: | ---: |
| 吃播（热狗 + 芝士） | 7.64s | 3.88s | **1.97x** |
| 迪士尼片段 | 7.84s | 3.68s | **2.13x** |
| 17 分钟购物分享 | 7.74s | 3.93s | **1.97x** |
| 古巴旅行纪录片 | 9.70s | 5.64s | **1.72x** |
| 美妆开箱 | 8.84s | 4.51s | **1.96x** |
| 螺蛳粉美食 vlog | 8.70s | 4.67s | **1.86x** |
| 韩国跑腿 vlog | 6.86s | 3.93s | **1.75x** |
| 澳洲旅行 vlog | 6.80s | 3.63s | **1.87x** |
| **全部 160 帧** | **平均 8.01s** | **平均 4.23s** | **1.89x** |

- 两段式的拆分开销很小：caption ≈ 1.74s，字段抽取 ≈ 2.50s。
- 可靠性：一段式 158/160 `ok`；两段式 142/160 `ok` 加 18 个 `partial`
  （第二阶段偶发问题——caption 仍会返回，用 `extract_fields(caption)`
  重试即可，无需再次处理图片）。零硬失败。
- 帧数据集在 `test_data/`（仓库内置每个视频 10 帧；基准测试用了 20
  帧）。原始数据和可交互的逐帧对比评审页在本地生成——
  `scripts/run_test_data_compare.py` 输出
  `results/test_data_compare_one_vs_v5.json`，
  `scripts/make_test_data_review.py` 将其转换为
  `results/test_data_review/index.html`（`results/` 目录已被
  gitignore）。

## 安装

Homebrew（tap）：

```bash
brew install MemoBloom/memosight/memosight
```

PyPI 或源码：

```bash
pip install memosight                 # 从 PyPI 安装
pip install -e .                      # 从源码检出安装，或：uv pip install -e .
pip install -e ".[dev]"               # 附带 pytest，用于运行测试套件
pytest tests/
```

## 快速开始

```bash
memosight setup-mlx        # 安装 mlx-vlm + jinja2（会先询问）；打印模型指引
memosight serve --model /path/to/your-vlm --port 8080   # 启动本地服务器
memosight doctor           # 验证安装与配置
memosight analyze photo.jpg --language zh --profile photography_default
```

`analyze` 将校验后的结果以稳定 JSON 输出到 stdout：

```json
{
  "status": "ok",
  "observation": {
    "caption": "一位身穿黑色运动上衣的女性正在健身房做深蹲……",
    "scene_labels": ["健身房", "室内"],
    "mood": ["专注"],
    "search_tags": ["深蹲", "健身"]
  },
  "schema_name": "photography_default"
}
```

*（已截断——完整结果还包含 `default_observation`、`validation`、
`usage` 等字段，见上方的输出契约。）*

模型权重永远不会被 Homebrew 或 memosight 自动下载——你需要显式准备
（见下文）。

## 在 Codex 中使用（Agent Skill）

安装内置的 Codex agent skill（需要先装好 `memosight` CLI，见上方安装
一节）：

```bash
npx memosight-skill install   # 将 skill 复制到 ~/.codex/skills/memosight
npx memosight-skill doctor    # 验证 node、CLI 和已安装的 skill
npx memosight-skill uninstall # 卸载
```

然后在 Codex 中：`Use $memosight to analyze this image into structured
JSON.` 其他 agent 目标平台见 [`memosight-skill/`](./memosight-skill)。

## 本地模型设置

MemoSight 与本地 [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) 服务器
通信，不在进程内加载模型。

1. 安装 mlx-vlm：`memosight setup-mlx`（或 `pip install mlx-vlm jinja2`——
   mlx-vlm 渲染聊天模板需要 jinja2，但没有把它声明为依赖）。
2. 自行准备模型权重——本仓库的基准测试和示例均使用
   [`mlx-community/Qwen3.5-2B-MLX-4bit`](https://huggingface.co/mlx-community/Qwen3.5-2B-MLX-4bit)
   验证，是 Apple Silicon 上不错的默认选择：

   ```bash
   huggingface-cli download mlx-community/Qwen3.5-2B-MLX-4bit --local-dir ~/models/Qwen3.5-2B-MLX-4bit
   ```

   其他 [mlx-community](https://huggingface.co/mlx-community) 的 VLM
   也可以使用。

3. 启动服务器：

   ```bash
   memosight serve --model ~/models/Qwen3.5-2B-MLX-4bit --port 8080
   # 等价命令：mlx_vlm.server --model ~/models/Qwen3.5-2B-MLX-4bit --port 8080
   ```

### 配置

后端连接通过环境变量配置：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MEMOSIGHT_MLX_SERVER_URL` | `http://127.0.0.1:8080` | mlx_vlm.server 的基础 URL |
| `MEMOSIGHT_MLX_MODEL_NAME` | *（空）* | 模型 id 提示；为空 = 使用服务器报告的第一个模型 |
| `MEMOSIGHT_MLX_TIMEOUT_S` | `60` | 请求超时时间 |

## CLI 用法

```text
memosight --help
memosight --version
memosight analyze IMAGE [--language zh|en] [--profile NAME] [--schema FILE]
                        [--backend mlx|mock] [--compact]
memosight doctor
memosight serve --model /path/to/model [--port 8080]
memosight setup-mlx [--yes]
memosight prompt --schema FILE [--plan FILE] [--language zh|en]
                 [--caption TEXT] [--json]
```

- `analyze` 将 `MemoSightResult` JSON 打印到 stdout，当结果状态不是
  `ok` 时以非零码退出。`--schema` 指向自定义输出 schema JSON 文件
  （隐含 `custom` profile）。`--backend mock` 运行确定性的离线后端，
  适合做冒烟测试。
- `doctor` 检查包导入、`MEMOSIGHT_MLX_SERVER_URL`、服务器可达性、
  `/health` 和 `/v1/models`，以及已加载的模型——每个失败项都会打印
  具体的修复建议。
- `serve` 包装 `mlx_vlm.server`；`--` 之后的额外参数会原样透传。
- `setup-mlx` 只在你确认后安装 mlx-vlm 和 jinja2 包，绝不下载模型权重。
- `prompt` 在不调用任何模型的情况下渲染自定义输出 schema 的 prompt：
  一段式的「图片→JSON」prompt 和两段式的两个 prompt（「图片→caption」
  和「caption→JSON」）。`--plan` 将 prompt 方案（`task_summary` /
  `field_guidance` / `negative_rules` / `output_rules` /
  `final_prompt`）合并进由 schema 生成的 prompt。默认输出 Markdown，
  加 `--json` 输出机器可读格式。

## Python API

```python
from memosight import (
    MemoSightImageSource,
    MemoSightPipeline,
    MemoSightRequest,
    MlXVlmMemoSightBackend,
)

pipeline = MemoSightPipeline(backend=MlXVlmMemoSightBackend())

result = await pipeline.analyze(
    MemoSightRequest(
        image=MemoSightImageSource(
            kind="path",
            image_path="/absolute/path/to/photo.jpg",
        ),
        language="zh",
        profile="photography_default",
    )
)
```

### Base64 输入

```python
result = await pipeline.analyze(
    MemoSightRequest(
        image=MemoSightImageSource(
            kind="base64",
            data=image_base64,
            mime_type="image/jpeg",
            filename="frame.jpg",
        ),
        language="en",
        profile="photography_default",
    )
)
```

### 两段式结构化输出

任何 profile——默认摄影契约或自定义 schema——都可以拆成两次独立的
模型调用：

```text
image -> short natural-language caption -> fields
      -> parse -> normalize -> validate -> the requested JSON contract
```

第二阶段对默认 profile 渲染为固定 Markdown 字段，对自定义和命名
profile 渲染为 schema 驱动的 JSON。

```python
from memosight import (
    MlXTextMemoSightBackend,
    MlXVlmMemoSightBackend,
    TwoStageMemoSightPipeline,
)
from memosight.mlx_client import MlXVlmClient

client = MlXVlmClient()
pipeline = TwoStageMemoSightPipeline(
    image_backend=MlXVlmMemoSightBackend(client),
    text_backend=MlXTextMemoSightBackend(client),
)
result = await pipeline.analyze(request)
```

两段原始输出可通过 `caption_raw_output` 和 `structured_raw_output`
获取；`usage` 包含独立的 caption、字段生成和后处理耗时。如果第二阶段
失败，结果为 `partial` 并保留 caption——用
`await pipeline.extract_fields(caption)` 只重试该阶段，图片不会被重新
解码或分析。在小型本地模型上，这种拆分比一段式结构化输出更快也更
可靠——见基准测试，以及 `examples/` 中的自定义 schema 案例（深蹲教程：
一段式 3/10 ok，两段式 9/10 ok，耗时减少 48%）。

### 自定义 Schema

```python
result = await pipeline.analyze(
    MemoSightRequest(
        image=MemoSightImageSource(
            kind="path",
            image_path="/absolute/path/to/product.jpg",
        ),
        language="zh",
        profile="custom",
        output_schema={
            "type": "object",
            "properties": {
                "product_type": {"type": "string"},
                "brand_visible": {"type": "boolean"},
                "dominant_colors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 5
                },
                "visible_defects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 6
                }
            },
            "required": ["product_type", "brand_visible"]
        },
    )
)
```

`MemoSightResult.observation` 保存调用方请求的输出；当使用默认
schema（或自定义输出可以安全映射回默认结构）时会填充
`default_observation`。自定义 schema 支持 `string`、`number`、
`integer`、`boolean`、标量数组和简单嵌套对象，支持 `required` /
`enum` / `description` / `maxItems`，并有边界限制（顶层字段 ≤ 24，
深度 ≤ 3，每个数组 ≤ 20 项，enum 选项 ≤ 50，JSON ≤ 20 KB）。

### 自定义 Prompt

Prompt 由三层组装而成，全部可以在不改动库代码的情况下替换：

1. **内置 prompt 配置**（`memosight/config/default_prompts.json`）——
   所有 prompt 文本，中英文齐全。按请求覆盖任意条目；你的 dict 或
   JSON 文件会深度合并到默认值之上：

   ```python
   result = await pipeline.analyze(
       MemoSightRequest(
           image=...,
           prompt_config="my_prompts.json",  # 或 dict
       )
   )
   ```

2. **Prompt 方案（prompt plan）**——渲染进 schema 驱动 prompt 的领域
   指导：`task_summary`、逐字段的 `field_guidance`、`negative_rules`、
   `output_rules` 和 `final_prompt`。方案可以由 LLM 起草
   （`design_prompt_plan`，使用前总会经过净化处理）、离线生成
   （`heuristic_prompt_plan`）或手工编写；也可以用
   `infer_output_schema_from_example` 从一个示例对象反推 schema。

   ```python
   import json
   plan = json.loads(open("examples/squat_prompt_plan.json").read())
   result = await pipeline.analyze(
       MemoSightRequest(
           image=...,
           profile="custom",
           output_schema=json.loads(open("examples/squat_schema.json").read()),
           prompt_plan=plan,
       )
   )
   ```

3. **先预览再运行**——不调用任何模型，渲染指定 schema 的一段式和
   两段式 prompt：

   ```bash
   memosight prompt --schema examples/squat_schema.json \
                    --plan examples/squat_prompt_plan.json
   # 加 --json 输出机器可读格式
   ```

`examples/squat_prompts.md` 展示了一套为健身 schema 生成的完整
prompt。

## 故障排查

先运行 `memosight doctor`——它会报告每个失败的检查项并给出具体的
修复建议：

```text
[FAIL] server reachable: http://127.0.0.1:8080 unreachable (ConnectError)
       -> Start the local server: `memosight serve --model /path/to/model` ...
```

常见原因：

- **服务器未运行** —— 用 `memosight serve --model ...` 启动后重新运行
  `memosight doctor`。
- **URL 或端口不对** —— 将 `MEMOSIGHT_MLX_SERVER_URL` 设置为服务器的
  实际基础 URL。
- **`MEMOSIGHT_MLX_MODEL_NAME` 不匹配** —— doctor 会列出服务器报告的
  模型 id；修正该变量，或取消设置以使用第一个模型。
- **缺少 `mlx-vlm`** —— 运行 `memosight setup-mlx`。
- **缺少 `jinja2`**（服务器渲染聊天模板时报 `pip install jinja2`）——
  mlx-vlm 需要它但没有声明依赖；重新运行 `memosight setup-mlx`
  （v0.2.1+ 会一并安装）或 `pip install jinja2`。

## 隐私

图片由运行在你自己机器上的模型分析。MemoSight 默认不调用任何云端
API，也不向第三方发送任何数据；唯一的网络流量是发往本地
`mlx_vlm.server` 的 HTTP 请求。模型权重由你显式准备或下载——无论是
`brew install memosight` 还是任何 memosight 命令都不会静默下载。

## 视频对比帧

以 2 fps 抽取内置对比视频的帧，长边限制在 720 像素，然后均匀选取
20 帧：

```bash
python scripts/extract_frames.py
```

该命令将所有缩放后的帧写入 `frames_all_720/`，对比子集写入
`frames_sample_720/`。源视频和已有的全分辨率帧不会被修改。需要时可以
用 `--video`、`--fps`、`--long-edge` 或 `--sample-count` 覆盖默认值。

## 内部实现

<details>
<summary><strong>代码布局</strong></summary>

```text
memosight/
  schema.py       # 公开的请求/结果模型（MemoSightRequest、MemoSightResult 等）
  source.py       # 图片源归一化（path / bytes / base64 -> ResolvedImageSource）
  backends.py     # 图片/文本后端协议，以及 MLX 和 mock 适配器
  profiles.py     # 命名 schema profile + 自定义 output_schema 校验
  prompts.py      # 由 profile/schema + prompt 方案组装中英文 prompt
  prompt_config.py    # 内置 prompt 配置加载 + 深度合并覆盖
  prompt_designer.py  # PromptPlan 模型、LLM 起草方案 + 净化、schema 推断
  config/default_prompts.json  # 全部内置 prompt 文本（中/英文），可通过 prompt_config 修改
  parser.py       # 不可信模型输出解析（严格/围栏/内嵌 JSON、遗留 Markdown）
  normalizer.py   # 字段归一化（允许的键、去重、最大条目数）
  validator.py    # 结构化校验问题（默认 + 自定义 schema）
  pipeline.py     # MemoSightPipeline：source -> profile -> prompt -> backend -> parse -> normalize -> validate
  two_stage.py    # 图片 -> caption -> 字段，文本阶段可独立重试
  cli.py          # 命令行接口：analyze / doctor / serve / setup-mlx / prompt
  errors.py       # 类型化的 MemoSight* 错误
  mlx_client.py   # 内置的 mlx_vlm.server httpx 客户端（MlXVlmMemoSightBackend 使用）
  mlx_prompts.py  # 内置客户端默认值使用的内置 prompt
```

</details>

<details>
<summary><strong>后端协议</strong></summary>

后端实现一个小的异步协议：

```python
class MemoSightBackend(Protocol):
    name: str
    version: str

    async def describe(self, image: ResolvedImageSource, prompt: MemoSightPrompt) -> str:
        ...
```

- 实现方以文本形式返回原始模型输出；解析、归一化和校验是流水线的
  职责——永不信任后端输出。
- 实现方负责清理已解析的图片源：完成后调用 `image.cleanup()`
  （放在 `finally` 块中最安全），确保 bytes/base64 输入物化的临时
  文件不会泄漏。调用方拥有的 path 源永不会被改动。
- `MlXVlmMemoSightBackend` 适配内置的 `MlXVlmClient`（惰性导入，因此
  未安装 httpx 时包仍可正常导入），并始终通过客户端的
  `system_prompt`/`user_text` 覆盖项传递 MemoSight 构建的 prompt。
- `MockMemoSightBackend` 是确定性的测试替身，具有固定响应和调用记录。
  它是仅供测试的后端：不要将 mock 结果存入真实数据库。

</details>

<details>
<summary><strong>纯性保证</strong></summary>

MemoSight 是纯模块。它不执行任何持久化、数据库访问或搜索索引逻辑。
核心模块只导入标准库和 Pydantic；`httpx` 仅被内置的 MLX 客户端需要。
纯性守护测试（`tests/test_memosight_schema.py`）在导入时强制约束这一
边界。

</details>

## 许可证

MIT —— 见 [LICENSE](./LICENSE)。
