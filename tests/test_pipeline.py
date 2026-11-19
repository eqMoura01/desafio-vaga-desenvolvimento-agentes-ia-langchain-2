import pytest
from pydantic import ValidationError

from src.ingest import Loaded
from src.pipeline import process_one, run_batch
from src.schemas import Classification


class Scripted:
    def __init__(self, tipo: str = "relatorio_manutencao", fail: str | None = None):
        self.tipo = tipo
        self.fail = fail
        self.errors: list[str | None] = []

    def classify(self, doc: Loaded) -> Classification:
        if doc.name == self.fail:
            raise RuntimeError("modelo recusou")
        return Classification(tipo=self.tipo, confianca="alta")

    def extract(self, doc: Loaded, tipo: str, error: str | None = None) -> dict:
        self.errors.append(error)
        if error is None and tipo == "nota_fiscal":
            return {}
        if tipo == "nota_fiscal":
            return {
                "fornecedor": "Oficina Atlas",
                "cnpj": "00.000.000/0001-00",
                "data": "2023-09-14",
                "itens": [{"descricao": "Encoder", "quantidade": 1, "valor": 80.0}],
                "valor_total": 80.0,
            }
        return {
            "data": "2023-09-14",
            "tecnico": "Marcos Vinicius Almeida",
            "equipamento": "Elevador de Passagei",
            "problema": "Trancos na aceleração",
            "solucao": "Troca do encoder",
        }


def _doc(name: str) -> Loaded:
    return Loaded(name=name, sha256="abc", text="ordem de serviço", images=[])


def test_routes_a_work_order_to_the_maintenance_schema():
    result = process_one(_doc("os.pdf"), Scripted())
    assert result["tipo"] == "relatorio_manutencao"
    assert result["dados"]["tecnico"] == "Marcos Vinicius Almeida"
    assert result["dados"]["data"] == "2023-09-14"


def test_unknown_document_skips_extraction():
    model = Scripted(tipo="desconhecido")
    result = process_one(_doc("outro.pdf"), model)
    assert result["dados"] is None
    assert model.errors == []


def test_invalid_extraction_is_sent_back_once():
    model = Scripted(tipo="nota_fiscal")
    result = process_one(_doc("nf.pdf"), model)
    assert model.errors[0] is None
    assert "fornecedor" in (model.errors[1] or "")
    assert result["dados"]["valor_total"] == 80.0


def test_one_bad_document_does_not_stop_the_batch(monkeypatch):
    docs = {
        "bom.pdf": _doc("bom.pdf"),
        "ruim.pdf": _doc("ruim.pdf"),
    }

    def fake_load(name: str, data: bytes) -> Loaded:
        return docs[name]

    monkeypatch.setattr("src.pipeline.load_pdf", fake_load)
    result = run_batch(
        [("bom.pdf", b"1"), ("ruim.pdf", b"2")],
        Scripted(fail="ruim.pdf"),
    )
    assert [item["arquivo"] for item in result["documentos"]] == ["bom.pdf"]
    assert result["falhas"][0]["arquivo"] == "ruim.pdf"


def test_second_invalid_extraction_raises():
    class AlwaysEmpty:
        def classify(self, doc: Loaded) -> Classification:
            return Classification(tipo="nota_fiscal", confianca="baixa")

        def extract(self, doc: Loaded, tipo: str, error: str | None = None) -> dict:
            return {}

    with pytest.raises(ValidationError):
        process_one(_doc("nf.pdf"), AlwaysEmpty())
