---
name: memosight
description: Use the memosight CLI or Python API to turn local images and video frames into validated structured JSON (caption, scene labels, people, actions, objects, lighting, mood, search tags) via a local mlx-vlm server. Use when the user needs image understanding, tagging, captioning, or frame analysis in a local-first workflow. This skill does not install memosight or download models.
---

# MemoSight Agent Guide

MemoSight is a local-first image-to-structured-JSON tool. All analysis runs
against a local `mlx_vlm.server`; no cloud API is called. This skill does not
own installation — if memosight is missing or broken, follow the repair flow
below instead of installing things yourself.

## 1. Detect and verify

```bash
memosight --version
memosight doctor
```

- If `memosight` is not on PATH, tell the user to install it
  (`brew install MemoBloom/memosight/memosight`) and stop — do not install
  it yourself.
- `memosight doctor` checks package imports, the server URL, server
  reachability, `/health`, `/v1/models`, and the loaded model. Each failing
  check prints remediation advice — follow that advice to guide the user
  through repairs.

## 2. Ask before side effects

Always ask for explicit user confirmation before:

- downloading model weights or any large artifact;
- starting or stopping services (`memosight serve ...`);
- installing or upgrading packages (`memosight setup-mlx`, `pip install ...`);
- setting or changing environment variables
  (`MEMOSIGHT_MLX_SERVER_URL`, `MEMOSIGHT_MLX_MODEL_NAME`,
  `MEMOSIGHT_MLX_TIMEOUT_S`).

## 3. Choose the interface

- **Single image, ad-hoc question, shell pipeline** — use the CLI:

  ```bash
  memosight analyze /path/to/photo.jpg --language zh --profile photography_default
  ```

  `analyze` writes stable JSON to stdout and exits non-zero when the result
  status is not `ok`, so it composes with `jq` and shell conditionals.

- **Batch workflows, custom schemas, video-frame pipelines, or integration
  into Python code** — use the Python API (`MemoSightPipeline`,
  `TwoStageMemoSightPipeline`); see the repository README for examples.

- **Custom output schemas** — preview the exact prompts before spending model
  calls:

  ```bash
  memosight prompt --schema schema.json --plan plan.json
  ```

## 4. Files and outputs

- Use project-relative paths for images and outputs; when producing analysis
  files, write them under a clear output directory (for example
  `./memosight-output/`) and tell the user where they landed.

## 5. Interpret results

- `status: "ok"` — `observation` (and `default_observation`) are validated
  and safe to store.
- `status: "partial"` (two-stage only) — the caption succeeded but field
  extraction failed; retry with `extract_fields(caption)` instead of
  re-analyzing the image.
- `status: "failed"` — read `error` and `validation.issues`; do not treat
  `observation` as usable. For persistent validation failures, run
  `memosight doctor` and suspect an overloaded or wrong model before
  suspecting the image.

## 6. Boundaries

- Never download model weights silently; models are user-prepared.
- Never point memosight at a remote/cloud endpoint without the user asking.
- People fields describe visible roles only; do not use memosight output to
  identify real people.
