# memosight-skill

Agent skill installer for [MemoSight](https://github.com/MemoBloom/memosight).

## Prerequisites

MemoSight itself must be installed separately (the skill does not install it):

```bash
brew install MemoBloom/memosight/memosight
```

## Install

```bash
npx memosight-skill install
```

This installs the skill to `~/.codex/skills/memosight/`.

## Verify

```bash
npx memosight-skill doctor
```

Checks Node/npm, the memosight CLI, and the skill installation.

## Uninstall

```bash
npx memosight-skill uninstall
```

Removes only the skill directory.

## Codex usage

```text
Use $memosight to analyze this image into structured JSON.
```

## Options

```bash
npx memosight-skill install --target codex   # default
npx memosight-skill install --dir /path/to/dir
```

Other targets (claude, cursor, windsurf) are planned; for now `--target` with an unknown value prints manual installation instructions.

## License

MIT
