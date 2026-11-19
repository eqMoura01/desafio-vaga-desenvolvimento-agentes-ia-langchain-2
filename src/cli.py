import argparse
import sys
from collections import Counter

from src.config import DEFAULT_ZIP, OUTPUT_PATH, RAW_DIR
from src.errors import MissingModelConfig, NoDocuments
from src.ingest import iter_sources
from src.pipeline import run_batch, write_output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classifica e extrai documentos")
    parser.add_argument("--input", default=str(RAW_DIR), help="Pasta com PDFs ou zips")
    parser.add_argument("--zip", default=str(DEFAULT_ZIP), help="Zip usado quando a pasta não tem PDF nem zip")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    parser.add_argument("--limit", type=int, default=0, help="Quantidade máxima de arquivos. 0 lê todos.")
    args = parser.parse_args(argv)
    try:
        sources = iter_sources(_path(args.input), _path(args.zip))
        result = run_batch(sources, limit=args.limit or None)
    except MissingModelConfig as exc:
        print(exc, file=sys.stderr)
        return 2
    except NoDocuments as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        if "sources" in locals():
            sources.close()
    write_output(result, _path(args.output))
    _report(result, _path(args.output))
    return 0


def _path(raw: str):
    from pathlib import Path

    return Path(raw)


def _report(result: dict, output) -> None:
    counts = Counter(item["tipo"] for item in result["documentos"])
    origem = Counter(item.get("origem") for item in result["documentos"])
    print(f"documentos: {len(result['documentos'])}")
    print(f"falhas: {len(result['falhas'])}")
    print(f"ocr: {origem.get('ocr', 0)}")
    print(f"agente: {origem.get('agente', 0)}")
    for tipo in ("nota_fiscal", "contrato", "relatorio_manutencao", "desconhecido"):
        print(f"{tipo}: {counts.get(tipo, 0)}")
    print(output)


if __name__ == "__main__":
    raise SystemExit(main())
