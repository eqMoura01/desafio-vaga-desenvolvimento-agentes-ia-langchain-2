CLASSIFY_PROMPT = """Classifique o documento em um destes tipos:
- nota_fiscal: nota fiscal, DANFE ou NF-e, com fornecedor, CNPJ, itens e total.
- contrato: contrato de prestação de serviços, com partes, objeto, vigência e valor mensal.
- relatorio_manutencao: relatório de manutenção ou ordem de serviço, com data, técnico, equipamento, problema e reparo.
- desconhecido: qualquer outro documento.

Use desconhecido quando o papel não for um desses três. A confiança é alta, media ou baixa.
"""

EXTRACT_PROMPTS = {
    "nota_fiscal": (
        "Extraia a nota fiscal. Datas em YYYY-MM-DD. "
        "Quantidade, valor do item e valor total são números com ponto decimal. "
        "CNPJ como está impresso."
    ),
    "contrato": (
        "Extraia o contrato de prestação de serviços. "
        "vigencia_inicio e vigencia_fim em YYYY-MM-DD. valor_mensal é número com ponto decimal."
    ),
    "relatorio_manutencao": (
        "Extraia o relatório de manutenção ou a ordem de serviço. "
        "data em YYYY-MM-DD. tecnico é o profissional. equipamento é o ativo. "
        "problema é o defeito encontrado. solucao é o reparo efetuado."
    ),
}


def extraction_prompt(tipo: str, error: str | None) -> str:
    text = EXTRACT_PROMPTS[tipo]
    if error:
        text += (
            "\n\nA leitura anterior não coube no formato pedido. "
            f"Ajuste só o que o erro aponta:\n{error}"
        )
    return text
