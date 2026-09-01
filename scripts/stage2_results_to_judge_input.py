"""Convert a stage2 prompt comparison file into judge-eval input format.

Extracts one prompt version's fields per record and wraps them in the
``two_stage.observation`` shape that ``eval_two_stage_judge.py`` expects.

Usage:
    .venv/bin/python scripts/stage2_results_to_judge_input.py \
        --input results/compare_stage2_prompt_v1_vs_v5_736x416.json \
        --version v5 \
        --output results/eval_input_stage2_v5.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames-dir", default="frames_sample_736x416")
    args = parser.parse_args()

    source = json.loads(Path(args.input).read_text())
    records = []
    for record in source["records"]:
        run = record[args.version]
        observation = {"caption": record["caption"], **run["fields"]}
        records.append(
            {
                "frame": record["frame"],
                "frame_path": str(Path(args.frames_dir) / record["frame"]),
                "two_stage": {
                    "status": run["status"],
                    "observation": observation,
                },
            }
        )
    payload = {
        "source": args.input,
        "version": args.version,
        "records": records,
    }
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    print(f"wrote {len(records)} records -> {args.output}")


if __name__ == "__main__":
    main()
