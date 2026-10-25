"""Eval set: facts, citations that match retrieved sources, coverage."""

from __future__ import annotations

import pytest

from app.eval.dataset import EVAL_CASES, EvalCase
from app.eval.run import main
from app.eval.score import mean_scores, score_case, score_regressions


def _perfect_report(case: EvalCase, url: str = "https://example.com/source") -> str:
    phrases = [group[0] for group in (*case.facts, *case.aspects)]
    body = ". ".join(phrases)
    return f"# {case.topic}\n\n{body} [1]\n\n## Sources\n\n[1] {url}\n"


def test_dataset_has_between_10_and_20_questions():
    assert 10 <= len(EVAL_CASES) <= 20
    ids = [case.id for case in EVAL_CASES]
    assert len(ids) == len(set(ids))
    for case in EVAL_CASES:
        assert case.topic
        assert case.facts
        assert case.aspects
        for group in (*case.facts, *case.aspects):
            assert group
            assert all(phrase.strip() for phrase in group)


@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda case: case.id)
def test_perfect_report_scores_all_dimensions(case: EvalCase):
    url = "https://example.com/source"
    scored = score_case(
        case,
        _perfect_report(case, url),
        [{"url": url, "title": "Source"}],
    )
    assert scored["factual"] == 1
    assert scored["citations"] == 1
    assert scored["coverage"] == 1
    assert scored["overall"] == 1


def test_missing_fact_lowers_factual_and_is_a_regression():
    case = next(item for item in EVAL_CASES if item.id == "origin-of-species")
    report = _perfect_report(case).replace("charles darwin", "an unnamed naturalist")
    scored = score_case(case, report, [{"url": "https://example.com/source"}])
    assert scored["factual"] < 1
    assert "charles darwin | darwin" in scored["details"]["facts_missed"]
    before = {"factual": 1.0, "citations": 1.0, "coverage": 1.0, "overall": 1.0}
    assert score_regressions(before, scored) == ["factual", "overall"]


def test_invented_citation_does_not_match():
    case = EVAL_CASES[0]
    report = (
        f"# Note\n\n{case.facts[0][0]} [1]\n\n## Sources\n\n"
        "[1] https://evil.example/made-up\n"
    )
    scored = score_case(case, report, [{"url": "https://example.com/real"}])
    assert scored["citations"] == 0


def test_dangling_marker_is_only_a_partial_citation_score():
    case = EVAL_CASES[0]
    url = "https://example.com/source"
    report = (
        f"# Note\n\n{case.facts[0][0]} [1] [2]\n\n## Sources\n\n"
        f"[1] {url}\n"
    )
    scored = score_case(case, report, [{"url": url}])
    assert scored["citations"] == 0.5


def test_url_fragment_and_trailing_slash_still_match():
    case = EVAL_CASES[0]
    report = (
        f"# Note\n\n{case.facts[0][0]} [1]\n\n## Sources\n\n"
        "[1] https://Example.com/source/#section\n"
    )
    scored = score_case(
        case,
        report,
        [{"url": "https://example.com/source/"}],
    )
    assert scored["citations"] == 1


def test_short_symbol_does_not_match_inside_a_word():
    case = next(item for item in EVAL_CASES if item.id == "gold-symbol")
    report = "The author of the paper discussed August weather."
    scored = score_case(case, report, [])
    assert scored["factual"] == 0


def test_mean_scores_and_flat_change_is_not_a_regression():
    rows = [
        {"factual": 1.0, "citations": 0.5, "coverage": 1.0, "overall": 0.8333},
        {"factual": 0.5, "citations": 0.5, "coverage": 0.5, "overall": 0.5},
    ]
    means = mean_scores(rows)
    assert means["factual"] == 0.75
    assert score_regressions(means, dict(means)) == []


def test_cli_without_live_does_not_require_an_api_key(capsys, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "16 eval questions" in out
    assert "--live" in out
