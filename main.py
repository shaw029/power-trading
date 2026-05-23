#!/usr/bin/env python3
"""
Day-Ahead Power Trading — CLI entry point.

Usage:
    python main.py                              # default mode from config
    python main.py --mode virtual               # ML spread-trading pipeline
    python main.py --mode bess                  # battery storage pipeline
    python main.py --mode all                   # run both sequentially
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
        choices=["virtual", "bess", "all"],
        default=None,
        help="Strategy mode (default: from config.yaml strategy_type)",
    )
    parser.add_argument(
        "--config", "-c",
        default="configs/config.yaml",
        help="Path to a YAML experiment config (default: configs/config.yaml)",
    )
    args = parser.parse_args()

    config = _load_config(args.config)
    mode = args.mode or config.get("strategy_type", "virtual")

    run_full_pipeline(mode=mode, config=config)


if __name__ == "__main__":
    main()
