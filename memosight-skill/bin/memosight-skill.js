#!/usr/bin/env node
// memosight-skill — installer for the MemoSight agent skill.
//
// Commands:
//   memosight-skill install [--target codex] [--dir PATH]
//   memosight-skill doctor
//   memosight-skill uninstall [--target codex] [--dir PATH]
//
// The installer never touches anything silently: it prints the exact paths
// it writes or deletes, and it never installs the memosight CLI itself.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PKG_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SKILL_SRC = path.join(PKG_ROOT, "skill");
const VERSION = JSON.parse(
  fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"),
).version;

const BREW_HINT = "brew install MemoBloom/memosight/memosight";

// Known install targets: agent name -> skills directory + layout note.
const TARGETS = {
  codex: {
    dir: () => path.join(os.homedir(), ".codex", "skills", "memosight"),
    note: "Codex discovers skills under ~/.codex/skills/<name>/SKILL.md",
  },
};

function usage() {
  console.log(`memosight-skill ${VERSION}

Usage:
  memosight-skill install [--target codex] [--dir PATH]
  memosight-skill doctor [--target codex] [--dir PATH]
  memosight-skill uninstall [--target codex] [--dir PATH]

Options:
  --target NAME   agent environment (default: codex)
  --dir PATH      override the target skills directory
  --help          show this help
  --version       show the package version
`);
}

function parseArgs(argv) {
  const args = { target: "codex", dir: null, command: null };
  const rest = [...argv];
  while (rest.length) {
    const arg = rest.shift();
    if (arg === "--target") args.target = rest.shift();
    else if (arg === "--dir") args.dir = rest.shift();
    else if (arg === "--help" || arg === "-h") args.command = "help";
    else if (arg === "--version" || arg === "-v") args.command = "version";
    else if (!args.command && !arg.startsWith("-")) args.command = arg;
    else {
      console.error(`Unknown argument: ${arg}`);
      args.command = "help";
      args.badArg = true;
    }
  }
  return args;
}

function targetDir(args) {
  if (args.dir) return path.resolve(args.dir);
  const target = TARGETS[args.target];
  if (target) return target.dir();
  return null;
}

function printManualInstall(target) {
  console.log(`Target "${target}" is not supported yet (codex is the first-class target).`);
  console.log("Manual installation: copy the skill directory into your agent's");
  console.log("skills location. The skill files are at:");
  console.log(`  ${SKILL_SRC}`);
  console.log("Known layouts:");
  console.log("  codex:  ~/.codex/skills/memosight/");
  console.log("  claude: ~/.claude/skills/memosight/ (experimental)");
}

function memosightVersion() {
  const result = spawnSync("memosight", ["--version"], { encoding: "utf8" });
  if (result.error || result.status !== 0) return null;
  return (result.stdout || "").trim() || null;
}

function install(args) {
  const dir = targetDir(args);
  if (!dir) {
    printManualInstall(args.target);
    return 1;
  }
  const version = memosightVersion();
  if (!version) {
    console.error("memosight CLI not found on PATH. Install it first:");
    console.error(`  ${BREW_HINT}`);
    return 1;
  }
  if (fs.existsSync(dir)) {
    console.error(`Already installed: ${dir}`);
    console.error("Run `memosight-skill uninstall` first to replace it.");
    return 1;
  }
  fs.mkdirSync(dir, { recursive: true });
  fs.cpSync(SKILL_SRC, dir, { recursive: true });
  console.log(`Installed MemoSight skill for ${args.target}:`);
  console.log(`  ${dir}`);
  console.log(`(memosight CLI detected: ${version})`);
  console.log("");
  console.log("Try it in Codex with:");
  console.log("  Use $memosight to analyze this image into structured JSON.");
  return 0;
}

function doctor(args) {
  let ok = true;
  const check = (name, pass, detail, advice) => {
    console.log(`  [${pass ? "ok " : "FAIL"}] ${name}: ${detail}`);
    if (!pass) {
      ok = false;
      if (advice) console.log(`         -> ${advice}`);
    }
  };

  check("node", true, process.version);
  const npm = spawnSync("npm", ["--version"], { encoding: "utf8" });
  check(
    "npm",
    !npm.error && npm.status === 0,
    (npm.stdout || "").trim() || "not found",
    "npm ships with node; reinstall node if it is missing.",
  );
  const version = memosightVersion();
  check(
    "memosight CLI",
    !!version,
    version || "not found on PATH",
    `Install it: ${BREW_HINT}`,
  );
  const dir = targetDir(args);
  if (!dir) {
    printManualInstall(args.target);
    return 1;
  }
  check(
    "skill directory",
    fs.existsSync(dir),
    dir,
    "Install it: npx memosight-skill install",
  );
  const skillMd = path.join(dir, "SKILL.md");
  check(
    "SKILL.md",
    fs.existsSync(skillMd),
    skillMd,
    "Reinstall: npx memosight-skill install (after uninstall).",
  );
  console.log(ok ? "\nAll checks passed." : "\nSome checks failed; see advice above.");
  return ok ? 0 : 1;
}

function uninstall(args) {
  const dir = targetDir(args);
  if (!dir) {
    printManualInstall(args.target);
    return 1;
  }
  if (!fs.existsSync(dir)) {
    console.log(`Nothing to remove: ${dir} does not exist.`);
    return 0;
  }
  console.log("Removing:");
  console.log(`  ${dir}`);
  fs.rmSync(dir, { recursive: true, force: true });
  console.log("Done. The memosight CLI itself is untouched.");
  return 0;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  switch (args.command) {
    case null:
    case "help":
      usage();
      return args.badArg ? 2 : 0;
    case "version":
      console.log(`memosight-skill ${VERSION}`);
      return 0;
    case "install":
      return install(args);
    case "doctor":
      return doctor(args);
    case "uninstall":
      return uninstall(args);
    default:
      console.error(`Unknown command: ${args.command}\n`);
      usage();
      return 2;
  }
}

process.exit(main());
