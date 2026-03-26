"""Tests for the evaluation framework (scorer and reporter)."""

from code_review_graph.eval.reporter import generate_markdown_report
from code_review_graph.eval.scorer import (
    compute_mrr,
    compute_precision_recall,
    compute_token_efficiency,
)


def test_token_efficiency():
    result = compute_token_efficiency(10000, 3000)
    assert result["raw_tokens"] == 10000
    assert result["graph_tokens"] == 3000
    assert result["ratio"] == 0.3
    assert result["reduction_percent"] == 70.0


def test_token_efficiency_zero_raw():
    result = compute_token_efficiency(0, 100)
    assert result["ratio"] == 0.0
    assert result["reduction_percent"] == 0.0


def test_mrr_found_at_rank_2():
    result = compute_mrr("b", ["a", "b", "c"])
    assert result == 0.5


def test_mrr_found_at_rank_1():
    result = compute_mrr("a", ["a", "b", "c"])
    assert result == 1.0


def test_mrr_not_found():
    result = compute_mrr("z", ["a", "b", "c"])
    assert result == 0.0


def test_precision_recall():
    predicted = {"a", "b", "c", "d"}
    actual = {"b", "c", "e"}
    result = compute_precision_recall(predicted, actual)
    # true positives = {b, c} = 2
    # precision = 2/4 = 0.5
    # recall = 2/3 = 0.6667
    assert result["precision"] == 0.5
    assert result["recall"] == round(2 / 3, 4)
    # f1 = 2 * 0.5 * 0.6667 / (0.5 + 0.6667)
    expected_f1 = round(2 * 0.5 * (2 / 3) / (0.5 + 2 / 3), 4)
    assert result["f1"] == expected_f1


def test_precision_recall_empty_sets():
    result = compute_precision_recall(set(), set())
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_precision_recall_no_overlap():
    result = compute_precision_recall({"a"}, {"b"})
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_generate_markdown_report():
    results = [
        {
            "benchmark": "token_efficiency",
            "ratio": 0.3,
            "reduction_percent": 70.0,
        },
        {
            "benchmark": "search_mrr",
            "ratio": "-",
            "reduction_percent": "-",
        },
    ]
    report = generate_markdown_report(results)
    assert "# Evaluation Report" in report
    assert "## Summary" in report
    assert "token_efficiency" in report
    assert "search_mrr" in report
    assert "70.0" in report
    assert "| Benchmark |" in report


def test_generate_markdown_report_empty():
    report = generate_markdown_report([])
    assert "No benchmark results" in report
