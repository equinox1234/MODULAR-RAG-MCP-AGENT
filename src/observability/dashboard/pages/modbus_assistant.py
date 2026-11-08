"""Modbus demo UI, reusing the local domain services and LangGraph Agent."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[4]


def parse_events(data: bytes):
    if len(data) > 1024 * 1024:
        raise ValueError("日志文件不能超过 1 MB")
    try:
        events = json.loads(data.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as exc:
        raise ValueError("请上传 UTF-8 编码的 JSON 日志数组") from exc
    if not isinstance(events, list) or len(events) > 500:
        raise ValueError("日志必须是数组，最多 500 条事件")
    from src.core.modbus_log import analyze_rtu_log
    analyze_rtu_log(events)  # Validate structure and ordering before model calls.
    return events


def run_action(action, question, events, device, timeout_ms):
    from src.observability.dashboard.services.modbus_run_record import recorded_run
    def execute(instrument):
        return _execute_action(action, question, events, device, timeout_ms, instrument)
    return recorded_run(execute, ROOT / "data/modbus/runs", action=action)


def _execute_action(action, question, events, device, timeout_ms, instrument):
    if action == "analyze":
        from src.core.modbus_log import analyze_rtu_log
        if events is None:
            raise ValueError("请先选择样例或上传日志")
        return {"log_analysis": analyze_rtu_log(events, timeout_ms), "status": "analyzed"}
    from src.core.modbus_knowledge import ModbusKnowledge
    knowledge = ModbusKnowledge()
    if action == "search":
        return knowledge.answer(question, device=device)
    from src.core.modbus_agent import ModbusAgent
    from src.core.settings import load_settings
    from src.libs.llm.llm_factory import LLMFactory
    settings = load_settings()
    model = instrument(LLMFactory.create(settings), settings.llm.model, settings.llm.provider)
    result = ModbusAgent(model, knowledge).run(
        question, events=events, device=device, timeout_ms=timeout_ms, execution_mode="auto")
    result.pop("events", None)
    return result


def render():
    st.header("Modbus 故障排查")
    st.caption("技术文档检索 · RTU 主站日志分析 · LangGraph Agent")
    st.info("日志分析不调用模型；文档检索默认 hybrid（每次查询会对问题做一次 embedding），可在 settings.yaml 切回 bm25 离线模式；运行 Agent 使用本地配置的模型 API。样例均为模拟数据。")
    mode = st.radio("日志来源", ["不提供日志", "模拟样例", "上传 JSON"], horizontal=True, key="mb_source")
    events = None
    valid = True
    if mode == "模拟样例":
        events = parse_events((ROOT / "tests/fixtures/modbus_simulated_log.json").read_bytes())
    elif mode == "上传 JSON":
        upload = st.file_uploader("选择日志文件（UTF-8 JSON，最多 1 MB / 500 条）", type=["json"], key="mb_upload")
        if upload is None:
            valid = False
            st.caption("先上传文件再运行。每条包含 timestamp_ms、direction 和 hex_frame。")
        else:
            try:
                events = parse_events(upload.getvalue())
            except (ValueError, TypeError, KeyError) as exc:
                valid = False
                st.error(f"日志格式不正确：{type(exc).__name__}。请检查数组、时间顺序和事件字段。")
    if events is not None:
        with st.expander("查看输入日志"):
            st.json(events)
    with st.form("mb_form"):
        question = st.text_area("问题", "请分析日志中的通信现象，并结合协议给出下一步验证建议。", max_chars=4000, key="mb_question")
        left, right = st.columns(2)
        device_label = left.selectbox("设备范围", ["通用协议", "VT-100（虚拟设备）"], key="mb_device")
        timeout = right.number_input("响应超时（毫秒）", min_value=1, max_value=60000, value=1000, key="mb_timeout")
        st.caption("文档问答也可不提供日志。VT-100 参数只适用于本项目的虚拟设备。")
        c1, c2, c3 = st.columns(3)
        analyze = c1.form_submit_button("只分析日志", disabled=not valid or events is None)
        search = c2.form_submit_button("只检索文档", disabled=not valid)
        agent = c3.form_submit_button("运行 Agent（调用模型）", disabled=not valid)
    device = "VT-100" if device_label.startswith("VT-100") else None
    signature = hashlib.sha256(json.dumps([question, events, device, timeout], ensure_ascii=False).encode()).hexdigest()
    if analyze or search or agent:
        st.session_state.pop("mb_result", None)
        if not question.strip() and not analyze:
            st.error("请填写问题。")
        else:
            try:
                with st.spinner("正在分析，请稍候；Agent 可能需要数分钟。"):
                    result = run_action("analyze" if analyze else "search" if search else "agent", question, events, device, timeout)
                st.session_state["mb_result"] = (signature, result)
            except Exception as exc:
                st.error(f"本次执行未完成（{type(exc).__name__}）。请检查本地模型配置、知识库和输入，不要在页面粘贴 API Key。")
    saved = st.session_state.get("mb_result")
    if not valid or not saved:
        return
    if saved[0] != signature:
        st.caption("输入已更改，请重新运行以查看对应结果。")
        return
    result = saved[1]
    st.subheader("本次结果")
    status = result.get("status", result.get("mode", "unknown"))
    st.write(f"状态：{status}")
    if result.get("execution_path"):
        st.caption("执行路径：" + ("简单文档问答：检索后直接生成" if result["execution_path"] == "simple_document" else "完整 Agent 工具决策循环"))
    metrics = result.get("run_metrics")
    if metrics:
        c1, c2, c3 = st.columns(3)
        c1.metric("本次耗时", f"{metrics['elapsed_ms'] / 1000:.2f} 秒")
        c2.metric("模型调用次数", metrics["model_calls"])
        tokens = metrics["token_usage"]["total_tokens"]
        c3.metric("返回的总 token", tokens if tokens is not None else "未知")
        cin, cout = st.columns(2)
        cin.metric("输入 token", metrics["token_usage"]["prompt_tokens"] if metrics["token_usage"]["prompt_tokens"] is not None else "未知")
        cout.metric("输出 token", metrics["token_usage"]["completion_tokens"] if metrics["token_usage"]["completion_tokens"] is not None else "未知")
        cost = metrics.get("monetary_cost")
        st.caption(f"失败模型调用：{metrics['failed_model_calls']}；公开价估算：{'¥' + format(cost, '.6f') if cost is not None else '未知/暂不支持该价格配置'}；回答质量：待人工复核。")
        if metrics.get("cost_estimate"):
            st.caption(metrics["cost_estimate"].get("assumptions", "费用估算不是实际账单。"))
        if not metrics["usage_complete"]:
            st.warning("用量记录不完整：失败或缺少usage的调用可能仍产生费用，不能将返回的token当作账单总量。")
        with st.expander("输入/输出用量与运行编号"):
            st.write(metrics)
    if result.get("recording_error"):
        st.warning("本地记录保存失败，本次统计仍包含在可下载的结果中。")
    if status in {"execution_error", "answer_error", "decision_error", "budget_exhausted", "duplicate_action", "insufficient_evidence"}:
        st.warning("本轮未形成完整可靠回答，请结合下面的工具记录检查。")
    if result.get("answer_source") == "retrieved_protocol_rule":
        st.caption("本次广播说明由程序根据检索到的协议规则组织，未使用自由生成回答。")
    analysis = result.get("log_analysis")
    if analysis:
        st.subheader("已确认日志事实")
        from src.core.modbus_facts import transaction_facts
        facts = transaction_facts(analysis)
        if facts:
            st.dataframe(facts, hide_index=True, use_container_width=True)
        if analysis.get("issues"):
            st.json(analysis["issues"])
        st.caption("pending 不等于 timeout；CRC 不匹配不能单独证明电磁干扰。")
    if result.get("answer"):
        st.subheader("回答与建议")
        st.markdown(result["answer"])
    for citation in result.get("citations", []):
        with st.expander(f"[{citation['id']}] {citation['title']} · {citation.get('version', '')} · PDF 页码 {citation.get('page') or '不适用'}"):
            st.text(citation["text"])
            st.caption(f"章节：{citation.get('section', '未识别')}；来源类型：{citation['kind']}")
            if citation.get("url", "").startswith("https://www.modbus.org/"):
                st.link_button("官方来源", citation["url"])
            path = Path(citation.get("local_path") or ROOT / "missing")
            if path.resolve().is_relative_to((ROOT / "data/modbus/raw").resolve()) and path.is_file() and path.suffix.lower() == ".pdf":
                st.download_button("下载原 PDF（按上述页码核对）", path.read_bytes(), file_name=path.name,
                                   mime="application/pdf", key=f"mb_pdf_{citation['id']}")
    if result.get("trace"):
        with st.expander("工具调用过程"):
            st.json(result["trace"])
    st.download_button("下载本次结果 JSON", json.dumps(result, ensure_ascii=False, indent=2),
                       file_name="modbus_result.json", mime="application/json", key="mb_download")
