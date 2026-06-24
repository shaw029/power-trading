#!/usr/bin/env python3
"""
Day-Ahead Power Trading — CLI entry point.

Usage:
    python main.py --mode download   # fetch all raw data sources
    python main.py --mode features   # download + preprocess + build features
    python main.py --mode model      # train + backtest on existing features
    python main.py --mode virtual    # full ML spread-trading pipeline
    python main.py --mode bess       # full battery storage pipeline
    python main.py --mode all        # virtual + bess sequentially
    python main.py                   # default mode from config.yaml strategy_type
"""

import argparse
from pipeline import run_full_pipeline
from src.utils.config import load_config


def main():
    parser = argparse.ArgumentParser(description="Day-Ahead Power Trading Pipeline")
    parser.add_argument(
        "--mode",
        "-m",
        choices=["download", "features", "model", "virtual", "bess", "all"],
        default=None,
        help="Pipeline mode (default: from config.yaml strategy_type)",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="configs/config.yaml",
        help="Path to a YAML experiment config (default: configs/config.yaml)",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    mode = args.mode or config.get("strategy_type", "virtual")

    run_full_pipeline(mode=mode, config=config)


if __name__ == "__main__":
    main()
