"""The versioned evaluation suites must stay mechanically verifiable.

A label whose anchor is not in the corpus silently measures the label rather
than the retriever, so this guards the fixtures themselves.  v2 is kept as the
frozen 60-case suite that produced the T-3/T-5 numbers; v3 is the current
100-case suite.
"""

import json
from pathlib import Path

import pytest

from scripts.validate_modbus_eval_suite import validate_suite

ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data/modbus/processed"
SUITES = {
    "v2": (ROOT / "tests/fixtures/modbus_eval_v2.json", 60, 40, 20),
    "v3": (ROOT / "tests/fixtures/modbus_eval_v3.json", 100, 65, 35),
}

pytestmark = pytest.mark.skipif(
    not (PROCESSED / "knowledge.json").exists(),
    reason="Run python -m scripts.ingest_modbus_docs first",
)


@pytest.mark.parametrize("name", sorted(SUITES))
def test_every_label_is_findable_in_the_corpus(name):
    path, *_ = SUITES[name]
    assert validate_suite(path) == []


@pytest.mark.parametrize("name", sorted(SUITES))
def test_suite_has_a_tuning_and_a_test_split(name):
    path, expected_total, expected_tuning, expected_test = SUITES[name]
    cases = json.loads(path.read_text(encoding="utf-8"))["retrieval_cases"]

    tuning = [case for case in cases if case["split"] == "tuning"]
    test = [case for case in cases if case["split"] == "test"]
    assert len(cases) == expected_total
    assert len(tuning) == expected_tuning
    assert len(test) == expected_test
    # The test split must never reuse a tuning question.
    assert not ({case["question"] for case in test} & {case["question"] for case in tuning})


@pytest.mark.parametrize("name", sorted(SUITES))
def test_ids_are_unique_and_questions_non_trivial(name):
    path, *_ = SUITES[name]
    cases = json.loads(path.read_text(encoding="utf-8"))["retrieval_cases"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert all(len(case["question"].strip()) >= 6 for case in cases)
    assert all(case["question"].strip() for case in cases)


def test_v3_review_status_is_recorded_for_every_case():
    """A completed review must leave a machine-readable trail per case."""
    path, *_ = SUITES["v3"]
    suite = json.loads(path.read_text(encoding="utf-8"))

    assert suite["review"]["status"] == "completed"
    assert suite["review"]["by"] == "assistant-self-review"
    assert suite["review"]["reviewed"] == len(suite["retrieval_cases"])
    for case in suite["retrieval_cases"]:
        review = case.get("review")
        assert review, f"{case['id']} has no review record"
        assert review["status"] in {"approved", "fixed", "removed"}
        assert review["by"] == "assistant-self-review"
        if review["status"] == "fixed":
            assert review.get("note"), f"{case['id']} was fixed without a note"


def test_validator_catches_a_broken_anchor(tmp_path):
    path, *_ = SUITES["v3"]
    suite = json.loads(path.read_text(encoding="utf-8"))
    suite["retrieval_cases"][0]["evidence"][0]["anchor"] = "this text is not in the corpus"
    broken = tmp_path / "broken_suite.json"
    broken.write_text(json.dumps(suite, ensure_ascii=False), encoding="utf-8")

    problems = validate_suite(broken)

    assert problems
    assert any("anchor not found" in problem for problem in problems)
