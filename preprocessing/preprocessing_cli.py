from __future__ import annotations

import argparse
import sys

from preprocessing_workflow import (
    load_json_config,
    preprocessing_config_from_dict,
    run_preprocessing_config,
    run_suite2p_config,
    suite2p_config_from_dict,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run preprocessing workflow stages from JSON config.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preprocess = subparsers.add_parser("preprocess", help="Run raw TIFF preprocessing.")
    preprocess.add_argument("--config", required=True, help="Path to preprocessing JSON config.")

    suite2p = subparsers.add_parser("suite2p", help="Run Suite2P after validating preprocessing outputs.")
    suite2p.add_argument("--config", required=True, help="Path to Suite2P JSON config.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        data = load_json_config(args.config)
        if args.command == "preprocess":
            run_preprocessing_config(preprocessing_config_from_dict(data))
        elif args.command == "suite2p":
            run_suite2p_config(suite2p_config_from_dict(data))
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"[preprocessing_cli] ERROR: {exc}", file=sys.stderr, flush=True)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
