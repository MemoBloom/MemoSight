# MemoSight Brew Release Todo

Goal: turn MemoSight from a Python library/package into a local-first CLI tool that can be installed with Homebrew, while preparing a later Codex skill as the adoption layer.

## 1. Add a CLI Entry Point

- Add `memosight/cli.py`.
- Add a console script in `pyproject.toml`:

```toml
[project.scripts]
memosight = "memosight.cli:main"
```

- The CLI should support at least:

```bash
memosight --help
memosight --version
memosight doctor
memosight analyze /path/to/image.jpg --language zh --profile photography_default
```

- `analyze` should write stable JSON to stdout.
- `doctor` should check:
  - whether the Python package imports correctly;
  - `MEMOSIGHT_MLX_SERVER_URL`;
  - whether local `mlx_vlm.server` is reachable;
  - whether `/health` or `/v1/models` responds normally;
  - current model name or loaded model;
  - clear remediation advice for each failing check.

## 2. Add Local MLX Helper Commands

- Optionally add:

```bash
memosight serve --model /path/to/model --port 8080
memosight setup-mlx
```

- `setup-mlx` must not silently download model weights. Any model download should require explicit user confirmation.
- `brew install memosight` must not download model weights.
- Document the recommended user flow:

```bash
brew install <owner>/memosight/memosight
memosight setup-mlx
memosight doctor
memosight analyze photo.jpg
```

## 3. Complete Packaging Metadata

- Fill out `pyproject.toml` metadata:
  - `license`
  - `authors`
  - `urls`
  - `keywords`
  - `classifiers`
- Ensure source distributions do not include large/generated artifacts:
  - test output directories;
  - `results/`;
  - frame extraction folders;
  - large local images;
  - temporary videos unless intentionally packaged.
- Confirm `README.md` works as both PyPI and Homebrew-facing documentation.
- Confirm a local build succeeds with `python -m build` or the chosen equivalent.

## 4. Add Tests

- Add CLI tests for:
  - `memosight --help`;
  - `memosight --version`;
  - `memosight doctor` when no server is running: should return a clear diagnostic and not crash;
  - `memosight analyze` with a mock backend or test mode: should output valid JSON.
- Keep existing tests passing:

```bash
pytest tests/
```

- If the project adds linting or formatting tools, include their checks in the verification notes.

## 5. Publish a GitHub Release

- Confirm the working tree is clean except for intentional release changes.
- Update the package version, for example `0.1.0`.
- Create and push a tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

- Confirm the GitHub release tarball URL works:

```text
https://github.com/<owner>/memosight/archive/refs/tags/v0.1.0.tar.gz
```

- Compute the tarball SHA-256:

```bash
curl -L https://github.com/<owner>/memosight/archive/refs/tags/v0.1.0.tar.gz | shasum -a 256
```

## 6. Create a Homebrew Tap

- Create a tap repository, recommended name:

```text
homebrew-memosight
```

- Initialize it locally:

```bash
brew tap-new <owner>/homebrew-memosight
```

- Create the formula:

```bash
brew create https://github.com/<owner>/memosight/archive/refs/tags/v0.1.0.tar.gz \
  --tap <owner>/homebrew-memosight \
  --set-name memosight
```

## 7. Write the Formula

Target formula shape:

```ruby
class Memosight < Formula
  include Language::Python::Virtualenv

  desc "Local-first image-to-structured-visual-text CLI"
  homepage "https://github.com/<owner>/memosight"
  url "https://github.com/<owner>/memosight/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "..."
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "memosight", shell_output("#{bin}/memosight --help")
  end
end
```

- Use Homebrew tooling to generate Python dependency resources:

```bash
brew update-python-resources memosight
```

- Confirm `pydantic`, `httpx`, and their recursive dependencies are pinned as `resource` blocks.
- The formula `test do` block must exercise real installed CLI behavior, not only check that a file exists.

## 8. Validate the Formula Locally

Run:

```bash
brew audit --strict --online memosight
brew install --build-from-source --verbose memosight
brew test memosight
memosight --help
memosight doctor
```

- Fix all audit errors.
- Review warnings and fix the actionable ones.
- Confirm installation does not mutate the user's global Python environment.
- Confirm uninstalling does not leave Homebrew-managed service files, model weights, or generated caches behind.

## 9. Update Documentation

Update `README.md` with:

- Homebrew installation;
- PyPI or source installation;
- local MLX server setup;
- `doctor` troubleshooting;
- minimal CLI usage;
- minimal Python API usage;
- privacy statement: images stay local and no cloud API is called by default;
- explicit note that model weights must be prepared or downloaded by the user.

Suggested structure:

```text
Install
Quick Start
Local Model Setup
CLI Usage
Python API
Troubleshooting
```

## 10. Prepare the Later Codex Skill

After package and Homebrew installation are working, create a Codex skill.

The skill should not own installation. It should guide agents to:

- check `memosight --version`;
- run `memosight doctor`;
- use the CLI or Python API depending on the user's image/video workflow;
- use `doctor` output to repair local setup issues;
- ask for confirmation before downloading models, starting services, or modifying environment variables.

## Review Handoff Checklist

When handing the implementation back for review, include:

- change summary;
- modified file list;
- CLI example output;
- `pytest` results;
- Homebrew formula content;
- `brew audit` and `brew test` results;
- known risks, limitations, or incomplete items.
