<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="MemoSight — images in, structured JSON out. Visual understanding through a local mlx-vlm server, validated algorithm-ready output, no cloud API required.">
</p>

MemoSight is a reusable image-to-structured-visual-text module. It accepts
image paths or in-memory image payloads, runs visual understanding through a
configurable backend, validates (and optionally repairs) the structured
output, and returns a stable, algorithm-friendly JSON object — fields such as
caption, scene labels, visible people, actions, objects, lighting, mood, and
search tags.

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
- **Schemas for your domain.** Six built-in profiles (`photography_default`,
  `wedding_selection`, `portrait_review`, `product_catalog`,
  `event_coverage`) plus bounded custom JSON schemas with `required`, `enum`,
  and `maxItems`.
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
  <img src="./assets/readme/pipeline.svg" width="100%" alt="MemoSight pipeline: image source, prompt building, local mlx-vlm backend, then across a trust boundary strict parsing, normalization, and validation, producing a validated MemoSightResult.">
</p>

Backends return raw model output as text; parsing, normalization, and
validation are pipeline responsibilities — backend output is never trusted.

## Quick Start

Install the package:

```bash
pip install -e .            # or: uv pip install -e .
pip install -e ".[dev]"     # with pytest for the test suite
pytest tests/
```

Start a local [mlx-vlm](https://github.com/Blaizzy/mlx-vlm) server:

```bash
pip install mlx-vlm
mlx_vlm.server --model /path/to/your-vlm --port 8080
```

Analyze an image:

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

### Configuration

Backend connection is configured via environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `MEMOSIGHT_MLX_SERVER_URL` | `http://127.0.0.1:8080` | mlx_vlm.server base URL |
| `MEMOSIGHT_MLX_MODEL_NAME` | *(empty)* | model id hint; empty = first model the server reports |
| `MEMOSIGHT_MLX_TIMEOUT_S` | `60` | request timeout |

## More Examples

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
  backends.py     # MemoSightBackend protocol, MlXVlmMemoSightBackend, MockMemoSightBackend
  profiles.py     # Named schema profiles + custom output_schema validation
  prompts.py      # zh/en prompt construction from profile or custom schema
  parser.py       # Untrusted model output parsing (strict/fenced/embedded JSON, legacy Markdown)
  normalizer.py   # Field normalization (allowed keys, dedupe, max items)
  validator.py    # Structured validation issues (default + custom schemas)
  pipeline.py     # MemoSightPipeline: source -> profile -> prompt -> backend -> parse -> normalize -> validate
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

TBD — add a license before publishing.
