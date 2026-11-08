"""Compare full Agent and auto-routing for the same document question (paid API)."""
import json
from pathlib import Path

from src.core.modbus_agent import ModbusAgent
from src.core.modbus_knowledge import ModbusKnowledge, ROOT
from src.core.settings import load_settings
from src.libs.llm.llm_factory import LLMFactory
from src.observability.dashboard.services.modbus_run_record import recorded_run


def main():
    settings = load_settings()
    knowledge = ModbusKnowledge()
    question = "请解释 Modbus 功能码03和04的区别，并引用官方文档。"
    report = {"question": question, "purpose": "Paired development comparison; not a held-out quality benchmark",
              "note": "Both modes use compact context; this isolates routing, not the old uncompressed implementation.", "results": {}}
    output = ROOT / "data/modbus/evaluation/call_optimization_comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    for mode in ("agent", "auto"):
        def execute(instrument):
            model = instrument(LLMFactory.create(settings), settings.llm.model, settings.llm.provider)
            state = ModbusAgent(model, knowledge).run(question, execution_mode=mode)
            state.pop("events", None)
            return state
        result = recorded_run(execute, ROOT / "data/modbus/benchmark_runs", action=f"benchmark_{mode}")
        report["results"][mode] = result
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"mode": mode, "status": result.get("status"), "metrics": result["run_metrics"]}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
