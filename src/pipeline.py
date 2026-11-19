import base64
import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from src.config import model_name, ocr_min_confidence
from src.errors import DocumentUnreadable, MissingModelConfig
from src.ingest import Loaded, load_pdf
from src.ocr import ler_documento
from src.prompts import CLASSIFY_PROMPT, extraction_prompt
from src.schemas import SCHEMAS, Classification


class VisionModel(Protocol):
    def classify(self, doc: Loaded) -> Classification: ...

    def extract(self, doc: Loaded, tipo: str, error: str | None = None) -> dict: ...


class LangchainVisionModel:
    def __init__(self, llm: ChatOpenAI):
        self._llm = llm

    def classify(self, doc: Loaded) -> Classification:
        structured = self._llm.with_structured_output(Classification, method="function_calling")
        result = structured.invoke(
            [SystemMessage(content=CLASSIFY_PROMPT), _human(doc, "Classifique este documento.")]
        )
        if isinstance(result, Classification):
            return result
        return Classification.model_validate(result)

    def extract(self, doc: Loaded, tipo: str, error: str | None = None) -> dict:
        schema = SCHEMAS[tipo]
        structured = self._llm.with_structured_output(schema, method="function_calling")
        result = structured.invoke(
            [
                SystemMessage(content="Extraia somente o que está no documento. Não invente campo."),
                _human(doc, extraction_prompt(tipo, error)),
            ]
        )
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return dict(result)


def build_model() -> LangchainVisionModel:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise MissingModelConfig()
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
    llm = ChatOpenAI(model=model_name(), api_key=key, base_url=base_url, temperature=0)
    return LangchainVisionModel(llm)


def run_batch(
    pairs: Iterable[tuple[str, bytes]],
    model: VisionModel | None = None,
    limit: int | None = None,
) -> dict:
    documentos: list[dict] = []
    falhas: list[dict] = []
    for index, (name, data) in enumerate(pairs):
        if limit and index >= limit:
            break
        try:
            doc = load_pdf(name, data)
        except DocumentUnreadable as exc:
            falhas.append({"arquivo": name, "erro": str(exc)})
            continue
        try:
            documentos.append(process_one(doc, model))
        except Exception as exc:
            falhas.append({"arquivo": name, "erro": str(exc)})
    return {"documentos": documentos, "falhas": falhas}


def process_one(doc: Loaded, model: VisionModel | None = None) -> dict:
    leitura = ler_documento(doc)
    if (
        leitura
        and leitura.get("dados")
        and leitura["confianca"] >= ocr_min_confidence()
    ):
        return {
            "arquivo": doc.name,
            "sha256": doc.sha256,
            "tipo": leitura["tipo"],
            "confianca": leitura["confianca"],
            "dados": leitura["dados"],
            "origem": "ocr",
        }
    if leitura and leitura.get("texto"):
        doc = Loaded(
            name=doc.name,
            sha256=doc.sha256,
            text=leitura["texto"],
            images=doc.images,
        )
    if model is None:
        model = build_model()
    final = _compile(doc, model).invoke(
        {
            "arquivo": doc.name,
            "sha256": doc.sha256,
            "tipo": None,
            "confianca": None,
            "dados": None,
        },
        config={"recursion_limit": 10},
    )
    return {
        "arquivo": doc.name,
        "sha256": doc.sha256,
        "tipo": final["tipo"],
        "confianca": final["confianca"],
        "dados": final["dados"],
        "origem": "agente",
    }


def write_output(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def _compile(doc: Loaded, model: VisionModel):
    def classify(state: dict) -> dict:
        decision = model.classify(doc)
        return {**state, "tipo": decision.tipo, "confianca": decision.confianca}

    def extract(state: dict) -> dict:
        return {**state, "dados": _extract(doc, model, state["tipo"])}

    def route(state: dict) -> str:
        if state.get("tipo") in SCHEMAS:
            return "extract"
        return "end"

    graph = StateGraph(dict)
    graph.add_node("classify", classify)
    graph.add_node("extract", extract)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route, {"extract": "extract", "end": END})
    graph.add_edge("extract", END)
    return graph.compile()


def _extract(doc: Loaded, model: VisionModel, tipo: str) -> dict:
    schema = SCHEMAS[tipo]
    raw = model.extract(doc, tipo, error=None)
    try:
        return schema.model_validate(raw).model_dump()
    except ValidationError as exc:
        retried = model.extract(doc, tipo, error=str(exc))
        return schema.model_validate(retried).model_dump()


def _human(doc: Loaded, prompt: str) -> HumanMessage:
    body = prompt
    if doc.text:
        body += "\n\nConteúdo textual:\n" + doc.text[:6000]
    if not doc.images:
        return HumanMessage(content=body)
    parts: list[dict] = [{"type": "text", "text": body}]
    for mime, blob in doc.images:
        encoded = base64.standard_b64encode(blob).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    return HumanMessage(content=parts)
