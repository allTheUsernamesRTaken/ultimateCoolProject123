from __future__ import annotations

import argparse
from pathlib import Path

from .core import run_extraction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m extraction")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Extract text for a submission artifact")
    run_parser.add_argument("submission_id")
    run_parser.add_argument("--artifacts-root", default="artifacts")

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run":
        content = run_extraction(args.submission_id, artifacts_root=Path(args.artifacts_root))
        print(content.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
