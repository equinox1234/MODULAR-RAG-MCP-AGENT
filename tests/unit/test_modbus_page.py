import json

import pytest
from streamlit.testing.v1 import AppTest

from src.observability.dashboard.pages import modbus_assistant as page


def test_upload_validation():
    with pytest.raises(ValueError):
        page.parse_events(b'{"bad":1}')
    with pytest.raises(ValueError):
        page.parse_events(b"not json")
    with pytest.raises(ValueError):
        page.parse_events(b"x" * (1024 * 1024 + 1))
    events = [{"timestamp_ms": 0, "direction": "TX", "hex_frame": "01 03 00 00 00 02 C4 0B"}]
    assert page.parse_events(json.dumps(events).encode()) == events


def app():
    return AppTest.from_string("from src.observability.dashboard.pages.modbus_assistant import render\nrender()").run(timeout=20)


def test_initial_render_never_calls_model(monkeypatch):
    monkeypatch.setattr(page, "run_action", lambda *a: pytest.fail("Render must not run a tool"))
    at = app()
    assert not at.exception
    assert at.header[0].value == "Modbus 故障排查"
    assert at.button[0].disabled


def test_sample_analysis_and_stale_result(monkeypatch, tmp_path):
    from src.observability.dashboard.services import modbus_run_record
    original = modbus_run_record.recorded_run
    monkeypatch.setattr(modbus_run_record, "recorded_run", lambda execute, directory, **kwargs: original(execute, tmp_path, **kwargs))
    at = app()
    at.radio[0].set_value("模拟样例").run()
    at.button[0].click().run(timeout=20)
    assert not at.exception
    assert len(at.dataframe) == 1
    assert "analyzed" in " ".join(x.value for x in at.markdown)
    assert len(at.metric) == 5
    assert at.metric[1].value == "0"
    assert at.metric[2].value == "0"
    assert len(list(tmp_path.glob("*.json"))) == 1
    at.text_area[0].set_value("更换问题").run()
    assert not at.dataframe


def test_agent_button_displays_mocked_answer_and_trace(monkeypatch):
    monkeypatch.setattr(page, "run_action", lambda *a: {"status": "completed", "answer": "测试回答 [D1]", "trace": [{"node": "respond"}]})
    at = app()
    at.button[2].click().run(timeout=20)
    assert not at.exception
    assert any("测试回答" in x.value for x in at.markdown)
    assert len(at.json) == 1
