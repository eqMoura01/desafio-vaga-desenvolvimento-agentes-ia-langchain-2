from typing import Literal

from pydantic import BaseModel, Field


class ItemNota(BaseModel):
    descricao: str
    quantidade: float
    valor: float


class NotaFiscal(BaseModel):
    fornecedor: str
    cnpj: str
    data: str = Field(description="Data em YYYY-MM-DD")
    itens: list[ItemNota]
    valor_total: float


class Contrato(BaseModel):
    contratante: str
    contratado: str
    objeto: str
    vigencia_inicio: str = Field(description="Data em YYYY-MM-DD")
    vigencia_fim: str = Field(description="Data em YYYY-MM-DD")
    valor_mensal: float


class RelatorioManutencao(BaseModel):
    data: str = Field(description="Data em YYYY-MM-DD")
    tecnico: str
    equipamento: str
    problema: str
    solucao: str


class Classification(BaseModel):
    tipo: Literal["nota_fiscal", "contrato", "relatorio_manutencao", "desconhecido"]
    confianca: Literal["alta", "media", "baixa"] = "media"


SCHEMAS = {
    "nota_fiscal": NotaFiscal,
    "contrato": Contrato,
    "relatorio_manutencao": RelatorioManutencao,
}
