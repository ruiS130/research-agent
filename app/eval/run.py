"""Run the research eval set.

Lexical scoring needs no API key. ``--live`` runs each question through the
graph and writes ``eval_results/latest.json``. If a same-mode baseline exists,
a drop in factual accuracy, citations, coverage, or overall exits 1 so the
change can be reverted.

Matching is phrase-based and misses paraphrases. A lower score is evidence
something got worse. An unchanged score is not proof the answers are equal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from app.eval.dataset import EVAL_CASES
from app.eval.score import mean_scores, score_case, score_regressions

_PLACEHOLDER_KEYS = {"", "sk-ant-your-key-here", "test-key-not-real"}


def _results_dir() -> Path:
    return Path(os.getenv("EVAL_RESULTS_DIR", "eval_results"))


def _api_key_ready() -> bool:
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    return key not in _PLACEHOLDER_KEYS and not key.startswith("sk-ant-your-key")


async def run_live() -> list[dict]:
    from app.agent.graph import build_research_graph
    from app.agent.settings import anthropic_model, cost_mode
    from app.agent.state import initial_state
    from app.observability import begin_job_metrics, end_job_metrics
    from app.rag.retriever import format_sources_for_response

    graph = build_research_graph()
    model = anthropic_model()
    mode = cost_mode()
    scored: list[dict] = []
    for index, case in enumerate(EVAL_CASES, start=1):
        print(f"[{index}/{len(EVAL_CASES)}] {case.id}", flush=True)
        begin_job_metrics(case.id, model=model, cost_mode=mode)
        try:
            state = initial_state(case.id, case.topic, use_past_research=False)
            final = await graph.ainvoke(state)
        finally:
            metrics = end_job_metrics(case.id)
        report = final.get("report") or ""
        sources = format_sources_for_response(final.get("extracted_findings") or [])
        row = score_case(case, report, sources)
        row["report"] = report
        row["sources"] = sources
        if metrics is not None:
            row["cost"] = metrics.to_cost_dict()
        scored.append(row)
        cost = (row.get("cost") or {}).get("estimated_usd")
        print(
            f"  factual={row['factual']:.2f} citations={row['citations']:.2f} "
            f"coverage={row['coverage']:.2f} overall={row['overall']:.2f} "
            f"usd={cost}",
            flush=True,
        )
    return scored


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score research quality.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run all questions through the agent (spends API credits).",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Also copy this run to the baseline file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Where to write the live run (default: eval_results/latest.json).",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Baseline to compare (default: eval_results/baseline.json).",
    )
    args = parser.parse_args(argv)

    results_dir = _results_dir()
    output = args.output or (results_dir / "latest.json")
    baseline_path = args.baseline or (results_dir / "baseline.json")

    print(f"{len(EVAL_CASES)} eval questions.")
    print(
        "Scores are lexical (facts, citations that match retrieved URLs, "
        "coverage). A drop versus the baseline should be reverted or flagged."
    )
    if not args.live:
        print("Pass --live to run the agent. That spends ANTHROPIC_API_KEY credits.")
        return 0

    if not _api_key_ready():
        print(
            "ANTHROPIC_API_KEY is missing or still the placeholder. "
            "Refusing to start a live eval.",
            file=sys.stderr,
        )
        return 2

    from app.agent.settings import anthropic_model, cost_mode

    scored = asyncio.run(run_live())
    means = mean_scores(scored)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "cost_mode": cost_mode(),
        "model": anthropic_model(),
        "means": means,
        "cases": scored,
    }
    _write(output, payload)
    print(
        "mean "
        f"factual={means['factual']:.2f} citations={means['citations']:.2f} "
        f"coverage={means['coverage']:.2f} overall={means['overall']:.2f}"
    )
    print(f"wrote {output}")

    if args.save_baseline:
        _write(baseline_path, payload)
        print(f"wrote baseline {baseline_path}")

    previous = _load(baseline_path)
    if previous is None or args.save_baseline:
        return 0
    if previous.get("cost_mode") != payload["cost_mode"] or previous.get("model") != payload["model"]:
        print(
            "Baseline model/mode is "
            f"{previous.get('model')} / {previous.get('cost_mode')}; "
            f"this run is {payload['model']} / {payload['cost_mode']}. "
            "Not treating the score delta as a regression.",
        )
        return 0

    dropped = score_regressions(previous.get("means") or {}, means)
    if not dropped:
        print("No score regression versus baseline.")
        return 0
    print(
        "Quality dropped versus baseline: " + ", ".join(dropped) + ". "
        "Revert this change or keep it flagged.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
