import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.rag.banking_experiment import calibrate, evaluate_holdout


def main():
    parser = argparse.ArgumentParser(description='Research calibration and a separate one-attempt reviewed holdout evaluation.')
    commands = parser.add_subparsers(dest='command', required=True)
    calibration = commands.add_parser('calibrate')
    calibration.add_argument('--bundle', required=True, type=Path)
    calibration.add_argument('--run-dir', required=True, type=Path)
    calibration.add_argument('--method', choices=['bm25', 'dense', 'hybrid_rrf'], default='bm25')
    calibration.add_argument('--min-precision', type=float, default=0.9)
    calibration.add_argument('--max-negative-far', type=float, default=0.05)
    holdout = commands.add_parser('holdout')
    holdout.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'calibrate':
        result = calibrate(args.bundle, args.run_dir, args.method, args.min_precision, args.max_negative_far)
        print(json.dumps({key: result[key] for key in ['status', 'method', 'selected_threshold', 'serving_approved']}, indent=2))
    else:
        result = evaluate_holdout(args.run_dir)
        print(json.dumps(dict(holdout_saved=True, serving_approved=result['serving_approved']), indent=2))


if __name__ == '__main__':
    main()
