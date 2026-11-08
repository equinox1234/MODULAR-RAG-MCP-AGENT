"""python -m scripts.ingest_modbus_docs -- builds page-preserving domain corpus."""
import json

from src.core.modbus_knowledge import ModbusKnowledge, ROOT
from src.ingestion.modbus_pdf import build_corpus


def main():
    report = build_corpus(ROOT / "data/modbus/raw", ROOT / "data/modbus/processed",
                          ROOT / "data/modbus/knowledge.json")
    # Build the same index used by modbus_qa, rather than leaving an unused corpus.
    ModbusKnowledge(corpus_path=ROOT / "data/modbus/processed/knowledge.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
