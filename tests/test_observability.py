"""Cost / metrics helpers."""

from __future__ import annotations

from app.observability import JobMetrics, begin_job_metrics, end_job_metrics, record_api_usage


def test_estimated_usd_haiku():
    m = JobMetrics(job_id="x", model="claude-3-5-haiku-20241022", cost_mode="min")
    m.add_usage(input_tokens=1_000_000, output_tokens=1_000_000)
    # 0.80 + 4.00 = 4.80
    assert abs(m.estimated_usd() - 4.80) < 1e-6


def test_record_api_usage_via_context():
    begin_job_metrics("job-obs", model="claude-3-5-haiku-20241022", cost_mode="min")
    record_api_usage(100, 50)
    m = end_job_metrics("job-obs")
    assert m is not None
    assert m.api_calls == 1
    assert m.input_tokens == 100
    assert m.output_tokens == 50
