from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
GROUND_TRUTH = EVAL_DIR / "ground_truth.json"
RESULTS_DIR = EVAL_DIR / "results"
