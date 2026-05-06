#!/usr/bin/env python3
"""
Day-Ahead Power Trading — CLI entry point.

Usage:
    python main.py                              # full pipeline, default settings
    python main.py --mode features              # rebuild features from processed data
    python main.py --mode model                 # retrain on saved features
    python main.py --config configs/config.yaml
"""

import argparse
import yaml
from pipeline import run_full_pipeline


def _load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Day-Ahead Power Trading Pipeline")
    parser.add_argument(
        "--mode", "-m",
        choices=["full", "features", "model"],
        default="full",
        help="Execution mode (default: full)",
    )
    parser.add_argument(
        "--config", "-c",
        default=None,
        help="Path to a YAML experiment config (e.g. configs/config.yaml)",
    )
    args = parser.parse_args()

    config = _load_config(args.config) if args.config else None

    run_full_pipeline(execution_mode=args.mode, config=config)


if __name__ == "__main__":
    main()
