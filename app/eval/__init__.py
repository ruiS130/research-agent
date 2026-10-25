"""Offline quality checks for research reports."""

from app.eval.dataset import EVAL_CASES, EvalCase
from app.eval.score import mean_scores, score_case, score_regressions

__all__ = [
    "EVAL_CASES",
    "EvalCase",
    "mean_scores",
    "score_case",
    "score_regressions",
]
