#!/usr/bin/env python3
"""
Electricity Trading System - Main Entry Point

This is the single entry point for running the complete electricity trading pipeline.

Usage:
    python main.py                    # Run full pipeline
    python main.py --mode features    # Skip data ingestion, use processed data
    python main.py --mode model       # Skip to model training using saved features
"""

import argparse
from pipeline import run_full_pipeline

def main():
    parser = argparse.ArgumentParser(description='Electricity Trading System')
    parser.add_argument('--mode', '-m',
                       choices=['full', 'features', 'model'],
                       default='full',
                       help='Execution mode: full (default), features, or model')

    args = parser.parse_args()

    print(f"Starting Electricity Trading System in {args.mode} mode...")

    # Run the simplified pipeline
    results = run_full_pipeline(execution_mode=args.mode)

    print("Pipeline completed successfully!")

if __name__ == "__main__":
    main()