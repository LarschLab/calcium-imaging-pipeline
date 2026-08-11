"""Backward-compatible command name for standalone drift analysis."""

from preprocessing.drift_analysis_cli import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
