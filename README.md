<p align="center">
  <img src="https://raw.githubusercontent.com/MemoBloom/MemoSight/main/assets/readme/hero.svg" width="100%" alt="MemoSight — images in, structured JSON out. Visual understanding through a local mlx-vlm server, validated algorithm-ready output, no cloud API required.">
</p>

<p align="center">
  English | <a href="README.zh-CN.md">简体中文</a>
</p>

MemoSight is a reusable image-to-structured-visual-text module and CLI. It
accepts image paths or in-memory image payloads, runs visual understanding
through a configurable backend, validates (and optionally repairs) the
structured output, and returns a stable, algorithm-friendly JSON object —
fields such as caption, scene labels, visible people, actions, objects,
lighting, mood, and search tags.

It was extracted from the MemoBrain photography workflow system, but has no
dependency on it: the core module imports only the Python standard library
and Pydantic.

## Why MemoSight

- **A contract, not a chat reply.** Every response is parsed, normalized, and
  validated against a typed schema — callers get a stable JSON object, never
  raw model prose.
- **Local-first.** The default backend talks to a local
  [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) server. No cloud API key, no
  data leaving the machine.
- **Schemas for your domain.** Five built-in profiles (`photography_default`,
  `wedding_selection`, `portrait_review`, `product_catalog`,
  `event_coverage`), a `custom` profile, and bounded custom JSON schemas with
  `required`, `enum`, and `maxItems`.
- **Your prompts, your schema.** All prompt text ships as bundled config, not
  code: override any prompt per request with `prompt_config`, inject a
  prompt plan (per-field guidance, do/don't rules) with `prompt_plan`, and
  preview the exact prompts with `memosight prompt` before spending a single
  model call.
- **Two-stage option for small models.** Split visual understanding into
  image→caption and caption→fields calls — ~1.7x faster and more reliable on
  small local VLMs (see Benchmarks), with an independently retryable second
  stage.
- **Bilingual prompts.** Prompt construction in Chinese or English from the
  same schema.
- **Pure and pluggable.** No persistence, no database, no search index — a
  purity guard test enforces it at import time. Swap in any backend by
  implementing a small async protocol.
- **Flexible input.** File paths, raw bytes, or base64 payloads; temp files
  are materialized and cleaned up automatically.

## Default Output Contract

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

People fields describe visible roles/subjects only — MemoSight never infers
real identities.

## How It Works

<p align="center">
  <img src="https://raw.githubusercontent.com/MemoBloom/MemoSight/main/assets/readme/pipeline.svg" width="100%" alt="MemoSight pipeline: image source, prompt building, local mlx-vlm backend, then across a trust boundary strict parsing, normalization, and validation, producing a validated MemoSightResult.">
</p>

Backends return raw model output as text; parsing, normalization, and
validation are pipeline responsibilities — backend output is never trusted.

## Benchmarks

Measured on an Apple M5 (32 GB) with a local Qwen3.5-2B-MLX-4bit served by
`mlx_vlm.server`: 9 short videos (food, travel, unboxing, vlog, tutorial),
10 evenly spaced frames per video, 90 frames total, alternating execution
order after warm-up.

| Video | One-stage JSON | Two-stage | Speedup |
| --- | ---: | ---: | ---: |
| Mukbang (hot dog + cheese) | 3.87s | 2.30s | **1.68x** |
| Disney clip | 3.89s | 1.99s | **1.95x** |
| 17-min shopping haul | 6.01s | 3.38s | **1.78x** |
| Cuba travel documentary | 6.30s | 3.87s | **1.63x** |
| Makeup unboxing | 6.22s | 3.83s | **1.62x** |
| Luosifen food vlog | 6.36s | 3.59s | **1.77x** |
| Korea errand-runner vlog | 6.48s | 4.03s | **1.61x** |
| Australia travel vlog | 5.09s | 3.05s | **1.67x** |
| Squat tutorial | 5.26s | 3.36s | **1.56x** |
| **All 90 frames** | **5.50s avg** | **3.27s avg** | **1.68x** |

- The two-stage split is cheap: caption ≈ 1.55s, field extraction ≈ 1.72s.
- Reliability: one-stage 90/90 `ok`; two-stage 90/90 `ok` — zero `partial`,
  zero hard failures. The complete-output Markdown contract for the default
  profile (exactly seven field lines, output must finish on `search_tags`)
  removed the early-stop failures of the legacy template. Even if stage two
  hiccups, the caption is still returned and `extract_fields(caption)`
  retries without touching the image again.
- Frame sets live in `test_data/` (the same 10 frames per video the
  benchmark ran on). Raw numbers and an interactive per-frame side-by-side
  review page are generated locally — `scripts/run_test_data_compare.py`
  writes `results/test_data_compare_one_vs_two_stage.json` and
  `scripts/make_test_data_review.py` turns it into
  `results/test_data_review_one_vs_two_stage/index.html` (the `results/`
  directory is gitignored).

## Install

Homebrew (tap):

```bash
brew install MemoBloom/memosight/memosight
```

PyPI or source:

```bash
pip install memosight                 # from PyPI
pip install -e .                      # from a source checkout, or: uv pip install -e .
pip install -e ".[dev]"               # with pytest for the test suite
pytest tests/
```

## Quick Start

```bash
memosight setup-mlx        # install mlx-vlm + jinja2 (asks first); prints model guidance
memosight serve --model /path/to/your-vlm --port 8080   # start the local server
memosight doctor           # verify the setup
memosight analyze photo.jpg --language zh --profile photography_default
```

`analyze` writes the validated result as stable JSON to stdout:

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

*(truncated — the full result also carries `default_observation`,
`validation`, `usage`, and more; see the output contract above.)*

Model weights are never downloaded by Homebrew or by memosight itself — you
prepare them explicitly (see below).

## Use from Codex (Agent Skill)

Install the bundled Codex agent skill (requires the `memosight` CLI, see
Install above):

```bash
npx memosight-skill install   # copies the skill into ~/.codex/skills/memosight
npx memosight-skill doctor    # verify node, the CLI, and the installed skill
npx memosight-skill uninstall # remove it again
```

Then in Codex: `Use $memosight to analyze this image into structured JSON.`
See [`memosight-skill/`](./memosight-skill) for other agent targets.

## Local Model Setup

MemoSight talks to a local [mlx-vlm](https://github.com/Blaizzy/mlx-vlm)
server; it does not load models in-process.

1. Install mlx-vlm: `memosight setup-mlx` (or `pip install mlx-vlm jinja2` —
   jinja2 is required by mlx-vlm for chat template rendering but is not
   declared as its dependency).
2. Prepare model weights yourself — the benchmarks and examples in this repo
   were validated with
   [`mlx-community/Qwen3.5-2B-MLX-4bit`](https://huggingface.co/mlx-community/Qwen3.5-2B-MLX-4bit),
   a good default for Apple Silicon:

   ```bash
   huggingface-cli download mlx-community/Qwen3.5-2B-MLX-4bit --local-dir ~/models/Qwen3.5-2B-MLX-4bit
   ```

   Other [mlx-community](https://huggingface.co/mlx-community) VLMs work too.

3. Start the server:

   ```bash
   memosight serve --model ~/models/Qwen3.5-2B-MLX-4bit --port 8080
   # equivalent: mlx_vlm.server --model ~/models/Qwen3.5-2B-MLX-4bit --port 8080
   ```

### Configuration

Backend connection is configured via environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEMOSIGHT_MLX_SERVER_URL` | `http://127.0.0.1:8080` | mlx_vlm.server base URL |
| `MEMOSIGHT_MLX_MODEL_NAME` | *(empty)* | model id hint; empty = first model the server reports |
| `MEMOSIGHT_MLX_TIMEOUT_S` | `60` | request timeout |
| `MEMOSIGHT_OPENAI_BASE_URL` | `http://127.0.0.1:8000/v1` | OpenAI-compatible server base URL (`--backend openai`) |
| `MEMOSIGHT_OPENAI_MODEL` | *（empty）* | model name; empty = first entry of `/v1/models` |
| `MEMOSIGHT_OPENAI_API_KEY` | *（empty）* | optional Bearer token for OpenAI-compatible servers |

### OpenAI-Compatible Servers (vLLM, SGLang, ...)

`--backend openai` targets any server exposing an OpenAI-compatible
`/v1/chat/completions` endpoint with vision content — for example
[vLLM](https://github.com/vllm-project/vllm) or SGLang on NVIDIA GPUs. Local
image files are sent as base64 data URIs; the same output contract, parsing,
validation, and repair flow apply as with the mlx-vlm backend — only the
transport changes.

```bash
# start the server (Linux / NVIDIA)
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8000

# CLI
memosight analyze photo.jpg --backend openai \
  --base-url http://localhost:8000/v1 \
  --model Qwen/Qwen2.5-VL-7B-Instruct
```

```python
from memosight import MemoSightPipeline, OpenAICompatBackend

pipeline = MemoSightPipeline(
    backend=OpenAICompatBackend(
        "http://localhost:8000/v1", "Qwen/Qwen2.5-VL-7B-Instruct"
    )
)
```

`--base-url` / `--model` fall back to `$MEMOSIGHT_OPENAI_BASE_URL` and
`$MEMOSIGHT_OPENAI_MODEL`; when no model name is configured, the model id is
resolved once from `/v1/models`. Set `$MEMOSIGHT_OPENAI_API_KEY` for Bearer
auth (not needed for a local vLLM server).

## CLI Usage

```text
memosight --help
memosight --version
memosight analyze IMAGE [--language zh|en] [--profile NAME] [--schema FILE]
                        [--backend mlx|mock|openai] [--base-url URL]
                        [--model NAME] [--compact]
memosight doctor
memosight serve --model /path/to/model [--port 8080]
memosight setup-mlx [--yes]
memosight prompt --schema FILE [--plan FILE] [--language zh|en]
                 [--caption TEXT] [--json]
```

- `analyze` prints the `MemoSightResult` JSON to stdout and exits non-zero
  when the result status is not `ok`. `--schema` points to a custom output
  schema JSON file (implies the `custom` profile). `--backend mock` runs a
  deterministic offline backend, useful for smoke tests. `--backend openai`
sends requests to any OpenAI-compatible server (vLLM, SGLang, ...) — see
[OpenAI-Compatible Servers](#openai-compatible-servers-vllm-sglang-).
- `doctor` checks the package imports, `MEMOSIGHT_MLX_SERVER_URL`, server
  reachability, `/health` and `/v1/models`, and the loaded model — each
  failing check prints concrete remediation advice.
- `serve` wraps `mlx_vlm.server`; extra arguments after `--` are passed
  through.
- `setup-mlx` installs the mlx-vlm and jinja2 packages only after your
  confirmation and never downloads model weights.
- `prompt` renders the prompts for a custom output schema without calling any
  model: the one-stage image→JSON prompt and both two-stage prompts
  (image→caption and caption→JSON). `--plan` merges a prompt plan
  (`task_summary` / `field_guidance` / `negative_rules` / `output_rules` /
  `final_prompt`) into the schema-derived prompts. Output is Markdown by
  default, or machine-readable with `--json`.

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

### Base64 Input

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

### Two-stage Structured Output

Any profile — the default photography contract or a custom schema — can run
as two independent model calls:

```text
image -> short natural-language caption -> fields
      -> parse -> normalize -> validate -> the requested JSON contract
```

Stage two renders a fixed-Markdown field prompt for the default profile
(the template enforces a complete seven-line output contract — each field
name appears exactly once and the output must finish on the `search_tags`
line, which removed the early-stop failures of the legacy template), and
schema-driven JSON for custom and named profiles.

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

The two raw outputs are available as `caption_raw_output` and
`structured_raw_output`; `usage` contains separate caption, field-generation,
and post-processing timings. If stage two fails, the result is `partial` and
preserves the caption — retry only that stage with
`await pipeline.extract_fields(caption)`; the image is not decoded or
analyzed again. On small local models the split is both faster and more
reliable than one-stage structured output — see Benchmarks, and the custom
schema case study in `examples/` (squat tutorial: one-stage 3/10 ok vs
two-stage 9/10 ok, 48% less time).

### Custom Schema

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

`MemoSightResult.observation` holds the caller-requested output;
`default_observation` is populated when the default schema is used (or when a
custom output can be safely mapped back). Custom schemas support `string`,
`number`, `integer`, `boolean`, arrays of scalars, and simple nested objects,
with `required` / `enum` / `description` / `maxItems`, and are bounded
(≤ 24 top-level fields, depth ≤ 3, ≤ 20 items per array, ≤ 50 enum choices,
≤ 20 KB JSON).

### Customizing Prompts

Prompts are assembled from three layers, all replaceable without touching
library code:

1. **Bundled prompt config** (`memosight/config/default_prompts.json`) —
   every piece of prompt text, zh and en. Override any entry per request;
   your dict or JSON file is deep-merged over the defaults:

   ```python
   result = await pipeline.analyze(
       MemoSightRequest(
           image=...,
           prompt_config="my_prompts.json",  # or a dict
       )
   )
   ```

2. **Prompt plan** — domain guidance rendered into schema-driven prompts:
   `task_summary`, per-field `field_guidance`, `negative_rules`,
   `output_rules`, and a `final_prompt`. Plans can be drafted by an LLM
   (`design_prompt_plan`, always sanitized before use), generated offline
   (`heuristic_prompt_plan`), or written by hand; a schema can also be
   drafted from one example object with `infer_output_schema_from_example`.

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

3. **Preview before you run** — render the exact one-stage and two-stage
   prompts for a schema without calling any model:

   ```bash
   memosight prompt --schema examples/squat_schema.json \
                    --plan examples/squat_prompt_plan.json
   # add --json for machine-readable output
   ```

`examples/squat_prompts.md` shows a full generated prompt set for a fitness
schema.

## Troubleshooting

Run `memosight doctor` first — it reports each failing check with concrete
remediation advice:

```text
[FAIL] server reachable: http://127.0.0.1:8080 unreachable (ConnectError)
       -> Start the local server: `memosight serve --model /path/to/model` ...
```

Common causes:

- **Server not running** — start it with `memosight serve --model ...` and
  re-run `memosight doctor`.
- **Wrong URL or port** — set `MEMOSIGHT_MLX_SERVER_URL` to the server's
  actual base URL.
- **`MEMOSIGHT_MLX_MODEL_NAME` mismatch** — doctor lists the model ids the
  server reports; fix the variable or unset it to use the first model.
- **`mlx-vlm` missing** — `memosight setup-mlx`.
- **`jinja2` missing** (server fails with `pip install jinja2` when rendering
  chat templates) — mlx-vlm needs it but does not declare it; re-run
  `memosight setup-mlx` (v0.2.1+ installs both) or `pip install jinja2`.

## Privacy

Images are analyzed by a model running on your own machine. MemoSight calls
no cloud API by default and sends nothing to third parties; the only network
traffic is HTTP to your local `mlx_vlm.server`. Model weights are prepared or
downloaded by you, explicitly — neither `brew install memosight` nor any
memosight command downloads them silently.

## Video Comparison Frames

Prepare the bundled comparison video at 2 fps with its long edge capped at
720 pixels, then select 20 evenly spaced frames:

```bash
python scripts/extract_frames.py
```

The command writes all resized frames to `frames_all_720/` and the comparison
subset to `frames_sample_720/`. Source video and existing full-resolution
frames are not modified. Override the defaults with `--video`, `--fps`,
`--long-edge`, or `--sample-count` when needed.

## Under the Hood

<details>
<summary><strong>Layout</strong></summary>

```text
memosight/
  schema.py       # Public request/result models (MemoSightRequest, MemoSightResult, ...)
  source.py       # Image source normalization (path / bytes / base64 -> ResolvedImageSource)
  backends.py     # Image/text backend protocols plus MLX and mock adapters
  openai_backend.py # OpenAI-compatible adapters (vLLM, SGLang, ...)
  profiles.py     # Named schema profiles + custom output_schema validation
  prompts.py      # zh/en prompt assembly from profile/schema + prompt plan
  prompt_config.py    # Bundled prompt config loading + deep-merge overrides
  prompt_designer.py  # PromptPlan models, LLM-drafted plans + sanitization, schema inference
  config/default_prompts.json  # All bundled prompt text (zh/en), editable via prompt_config
  parser.py       # Untrusted model output parsing (strict/fenced/embedded JSON, legacy Markdown)
  normalizer.py   # Field normalization (allowed keys, dedupe, max items)
  validator.py    # Structured validation issues (default + custom schemas)
  pipeline.py     # MemoSightPipeline: source -> profile -> prompt -> backend -> parse -> normalize -> validate
  two_stage.py    # Image -> caption -> fields with an independently retryable text stage
  cli.py          # Command-line interface: analyze / doctor / serve / setup-mlx / prompt
  errors.py       # Typed MemoSight* errors
  mlx_client.py   # Vendored httpx client for mlx_vlm.server (used by MlXVlmMemoSightBackend)
  mlx_prompts.py  # Built-in prompts used by the vendored client defaults
```

</details>

<details>
<summary><strong>Backend protocol</strong></summary>

Backends implement a small async protocol:

```python
class MemoSightBackend(Protocol):
    name: str
    version: str

    async def describe(self, image: ResolvedImageSource, prompt: MemoSightPrompt) -> str:
        ...
```

- Implementations return the raw model output as text; parsing, normalization,
  and validation are pipeline responsibilities — never trust backend output.
- Implementations own cleanup of the resolved image source: call
  `image.cleanup()` when done (a `finally` block is safest) so temp files
  materialized for bytes/base64 inputs never leak. Caller-owned path sources
  are never touched.
- `MlXVlmMemoSightBackend` adapts the vendored `MlXVlmClient`
  (lazy-imported, so the package stays importable without httpx installed)
  and always delivers the MemoSight-built prompt via the client's
  `system_prompt`/`user_text` overrides.
- `MockMemoSightBackend` is a deterministic test double with a fixed response
  and recorded calls. It is a test-only backend: do not store mock results
  in real databases.

</details>

<details>
<summary><strong>Purity guarantees</strong></summary>

MemoSight is a pure module. It performs no persistence, no database access,
and no search-index logic. Core modules import only the standard library and
Pydantic; `httpx` is needed solely by the vendored MLX client. A purity guard
test (`tests/test_memosight_schema.py`) enforces the boundary at import time.

</details>

## License

MIT — see [LICENSE](./LICENSE).
