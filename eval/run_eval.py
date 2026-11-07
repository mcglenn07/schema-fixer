"""Run with the project environment: uv run python eval/run_eval.py."""

from pathlib import Path

from schema_fixer.eval_runner import main

if __name__ == "__main__":
    raise SystemExit(main(Path(__file__).resolve().parents[1]))
