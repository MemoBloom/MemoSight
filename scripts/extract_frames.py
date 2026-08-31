"""Extract resized video frames and an evenly spaced comparison subset."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

DEFAULT_VIDEO = Path("video/disney.MP4")
DEFAULT_ALL_FRAMES_DIR = Path("frames_all_720")
DEFAULT_SAMPLE_FRAMES_DIR = Path("frames_sample_720")
DEFAULT_FPS = 2.0
DEFAULT_LONG_EDGE = 720
DEFAULT_SAMPLE_COUNT = 20


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _generated_frames(directory: Path) -> list[Path]:
    return sorted(directory.glob("f[0-9][0-9][0-9][0-9].jpg"))


def _clear_generated_frames(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for frame in _generated_frames(directory):
        frame.unlink()


def _sample_indices(frame_count: int, sample_count: int) -> list[int]:
    """Return zero-based, evenly spaced indices including both endpoints."""
    if frame_count <= 0:
        return []
    if sample_count >= frame_count:
        return list(range(frame_count))
    if sample_count == 1:
        return [0]
    last = frame_count - 1
    return [round(index * last / (sample_count - 1)) for index in range(sample_count)]


def extract_frames(
    video: Path,
    all_frames_dir: Path,
    sample_frames_dir: Path,
    *,
    fps: float,
    long_edge: int,
    sample_count: int,
) -> list[Path]:
    if not video.is_file():
        raise FileNotFoundError(f"Video not found: {video}")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required but was not found on PATH")

    _clear_generated_frames(all_frames_dir)
    _clear_generated_frames(sample_frames_dir)

    # -2 preserves aspect ratio and rounds the short edge to an even number.
    scale = (
        f"scale='if(gte(iw,ih),{long_edge},-2)':"
        f"'if(gte(iw,ih),-2,{long_edge})'"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vf",
            f"fps={fps:g},{scale}",
            "-q:v",
            "2",
            str(all_frames_dir / "f%04d.jpg"),
        ],
        check=True,
    )

    frames = _generated_frames(all_frames_dir)
    if not frames:
        raise RuntimeError(f"ffmpeg produced no frames for {video}")
    selected = [frames[index] for index in _sample_indices(len(frames), sample_count)]
    for frame in selected:
        shutil.copy2(frame, sample_frames_dir / frame.name)
    return selected


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--all-frames-dir", type=Path, default=DEFAULT_ALL_FRAMES_DIR)
    parser.add_argument("--sample-frames-dir", type=Path, default=DEFAULT_SAMPLE_FRAMES_DIR)
    parser.add_argument("--fps", type=_positive_float, default=DEFAULT_FPS)
    parser.add_argument("--long-edge", type=_positive_int, default=DEFAULT_LONG_EDGE)
    parser.add_argument("--sample-count", type=_positive_int, default=DEFAULT_SAMPLE_COUNT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    selected = extract_frames(
        args.video,
        args.all_frames_dir,
        args.sample_frames_dir,
        fps=args.fps,
        long_edge=args.long_edge,
        sample_count=args.sample_count,
    )
    print(
        f"Extracted {len(_generated_frames(args.all_frames_dir))} frames; "
        f"selected {len(selected)} at long edge {args.long_edge}."
    )


if __name__ == "__main__":
    main()
