import json
from types import SimpleNamespace

from src.observability.dashboard.services.modbus_run_record import recorded_run


def test_successful_model_calls_and_persistence(tmp_path):
    def execute(instrument):
        llm = instrument(SimpleNamespace(chat=lambda: SimpleNamespace(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})), "test-model", "test-provider")
        llm.chat()
        llm.chat()
        return {"status": "completed", "answer": "private answer"}
    result = recorded_run(execute, tmp_path)
    m = result["run_metrics"]
    assert m["model_calls"] == 2 and m["token_usage"]["total_tokens"] == 30
    assert m["usage_complete"] and m["monetary_cost"] is None
    content = next(tmp_path.glob("*.json")).read_text(encoding="utf-8")
    assert "private answer" not in content
    assert json.loads(content)["run_id"] == m["run_id"]


def test_failed_call_does_not_expose_secret_or_claim_zero_usage(tmp_path):
    def fail():
        raise RuntimeError("secret credential")
    def execute(instrument):
        instrument(SimpleNamespace(chat=fail), "model", "provider").chat()
    result = recorded_run(execute, tmp_path)
    assert result["status"] == "execution_error"
    assert result["run_metrics"]["failed_model_calls"] == 1
    assert result["run_metrics"]["token_usage"]["total_tokens"] is None
    assert not result["run_metrics"]["usage_complete"]
    assert "secret credential" not in json.dumps(result)


def test_no_model_and_missing_usage_are_distinct(tmp_path):
    plain = recorded_run(lambda instrument: {"status": "analyzed"}, tmp_path)
    assert plain["run_metrics"]["token_usage"]["total_tokens"] == 0
    def execute(instrument):
        instrument(SimpleNamespace(chat=lambda: SimpleNamespace(usage=None)), "model", "provider").chat()
        return {"status": "completed"}
    missing = recorded_run(execute, tmp_path)
    assert missing["run_metrics"]["token_usage"]["total_tokens"] is None
    assert not missing["run_metrics"]["usage_complete"]


def test_recording_failure_preserves_result_and_exportable_metrics(tmp_path):
    blocked = tmp_path / "not_a_directory"
    blocked.write_text("occupied")
    result = recorded_run(lambda instrument: {"status": "completed", "answer": "usable answer"}, blocked, action="search")
    assert result["answer"] == "usable answer"
    assert result["recording_error"]
    assert result["run_metrics"]["action"] == "search"
