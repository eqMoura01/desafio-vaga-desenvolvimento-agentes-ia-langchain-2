import io
import re
import unicodedata
from functools import lru_cache

import numpy as np
from PIL import Image
from pydantic import ValidationError

from src.schemas import SCHEMAS

_CNPJ = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
_QTD = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(?:R\$|BRL)?\s*([\d.,]+)",
    re.IGNORECASE,
)
_DINHEIRO = re.compile(r"(?:R\$|BRL)\s*([\d.]+,\d{2}|\d+)|([\d.]+,\d{2})", re.IGNORECASE)
_DATA_NUM = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")
_DATA_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATA_EXTENSO = re.compile(
    r"(\d{1,2})\s+de\s+([A-Za-zçÇ]+)\s+de\s+(\d{4})",
    re.IGNORECASE,
)
_MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_ENGINE = None


def ler_documento(doc) -> dict | None:
    if doc.images:
        linhas = ler_linhas(doc.images)
    elif len((doc.text or "").strip()) >= 80:
        linhas = [(line.strip(), 0.99) for line in doc.text.splitlines() if line.strip()]
    else:
        return None
    if not linhas:
        return None
    leitura = interpretar(linhas)
    leitura["texto"] = "\n".join(texto for texto, _ in linhas)
    return leitura


def ler_linhas(images: list[tuple[str, bytes]]) -> list[tuple[str, float]]:
    linhas: list[tuple[str, float]] = []
    for _mime, blob in images:
        image = Image.open(io.BytesIO(blob)).convert("RGB")
        raw = _engine()(np.array(image))
        textos = list(getattr(raw, "txts", None) or [])
        notas = list(getattr(raw, "scores", None) or [])
        for index, texto in enumerate(textos):
            limpo = str(texto or "").strip()
            if not limpo:
                continue
            nota = float(notas[index]) if index < len(notas) else 0.0
            linhas.append((limpo, nota))
    return linhas


def interpretar(linhas: list[tuple[str, float]]) -> dict:
    tipo = _tipo(linhas)
    if tipo == "nota_fiscal":
        bruto, nota = _nota(linhas)
    elif tipo == "contrato":
        bruto, nota = _contrato(linhas)
    elif tipo == "relatorio_manutencao":
        bruto, nota = _relatorio(linhas)
    else:
        return {"tipo": None, "confianca": 0.0, "dados": None}
    if bruto is None:
        return {"tipo": tipo, "confianca": 0.0, "dados": None}
    try:
        dados = SCHEMAS[tipo].model_validate(bruto).model_dump()
    except ValidationError:
        return {"tipo": tipo, "confianca": 0.0, "dados": None}
    return {"tipo": tipo, "confianca": round(nota, 4), "dados": dados}


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR

        _ENGINE = RapidOCR()
    return _ENGINE


def _tipo(linhas: list[tuple[str, float]]) -> str | None:
    for texto, _nota in linhas[:6]:
        chave = _sem_acento(texto)
        if "FICHA DE SERVICO" in chave or chave.startswith("ORDEM DE SERVICO") or chave.startswith("RELATORIO TECNICO"):
            return "relatorio_manutencao"
        if chave.startswith("FATURA") or chave.startswith("DOCUMENTO FISCAL") or chave.startswith("NF-E"):
            return "nota_fiscal"
        if (
            "INSTRUMENTO PARTICULAR" in chave
            or "ACORDO DE SERVICO" in chave
            or "CONTRATO DE PRESTACAO" in chave
            or chave.startswith("CONTRATO DE SERVICO")
        ):
            return "contrato"
    return None


def _nota(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    cabecalho = _sem_acento(linhas[0][0]) if linhas else ""
    if cabecalho.startswith("DOCUMENTO FISCAL"):
        return _documento_fiscal(linhas)
    if cabecalho.startswith("NF-E"):
        return _nfe(linhas)
    return _fatura(linhas)


def _fatura(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    notas: list[float] = []
    fornecedor = ""
    cnpj = ""
    data = ""
    for index, (texto, nota) in enumerate(linhas):
        chave = _sem_acento(texto)
        if chave.startswith("EMITIDO EM"):
            token = texto.split(":", 1)[-1].strip()
            data = _data_de_texto(token) or ""
            notas.append(nota)
        elif chave.startswith("DOCUMENTO"):
            achado = _cnpj(texto)
            if achado:
                cnpj = achado
                notas.append(nota)
            if index > 0 and not fornecedor:
                fornecedor = linhas[index - 1][0].strip()
                notas.append(linhas[index - 1][1])
    inicio = _indice(linhas, "PRODUTOS")
    fim = _indice(linhas, "TOTAL GERAL")
    itens, notas_itens, completos = _itens(linhas[inicio + 1 : fim] if inicio >= 0 else [])
    if not completos:
        return None, 0.0
    notas.extend(notas_itens)
    total = None
    if fim >= 0:
        total = _dinheiro(linhas[fim][0])
        notas.append(linhas[fim][1])
        if total is None and fim + 1 < len(linhas):
            total = _dinheiro(linhas[fim + 1][0])
            notas.append(linhas[fim + 1][1])
    if not (fornecedor and cnpj and data and itens and total is not None):
        return None, 0.0
    return {
        "fornecedor": fornecedor,
        "cnpj": cnpj,
        "data": data,
        "itens": itens,
        "valor_total": total,
    }, min(notas)


def _itens(linhas: list[tuple[str, float]]) -> tuple[list[dict], list[float], bool]:
    itens: list[dict] = []
    notas: list[float] = []
    index = 0
    while index < len(linhas):
        texto, nota = linhas[index]
        if not texto.lstrip().startswith("-"):
            index += 1
            continue
        descricao = texto.lstrip("- ").strip()
        usadas = [nota]
        quantidade = _quantidade(texto)
        valor = None
        cursor = index + 1
        while cursor < len(linhas) and not linhas[cursor][0].lstrip().startswith("-"):
            pedaco, pedaco_nota = linhas[cursor]
            usadas.append(pedaco_nota)
            if quantidade is None and _quantidade(pedaco) is not None:
                quantidade = _quantidade(pedaco)
            elif _so_dinheiro(pedaco):
                valor = _dinheiro(pedaco)
            elif quantidade is None:
                descricao = f"{descricao} {pedaco}".strip()
            cursor += 1
        if quantidade is None or valor is None or not descricao:
            return [], [], False
        itens.append({"descricao": descricao, "quantidade": quantidade, "valor": valor})
        notas.extend(usadas)
        index = cursor
    return itens, notas, bool(itens)


def _documento_fiscal(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    fornecedor = _valor_na_mesma_linha(linhas, "NOME DO FORNECEDOR")
    cnpj_linha = _linha_que_contem(linhas, "CNPJ")
    data_linha = _linha_que_contem(linhas, "DATA:")
    if not all((fornecedor, cnpj_linha, data_linha)):
        return None, 0.0
    cnpj = _cnpj(cnpj_linha[0])
    data = _data_de_texto(data_linha[0].split(":", 1)[-1].strip())
    if cnpj is None or data is None:
        return None, 0.0
    inicio = _indice(linhas, "VALOR ITEM")
    fim = _indice(linhas, "VALOR A PAGAR")
    if inicio < 0 or fim < 0:
        return None, 0.0
    itens, notas_itens = _tabela(linhas[inicio + 1 : fim])
    if not itens:
        return None, 0.0
    total_linha = linhas[fim + 1] if fim + 1 < len(linhas) else linhas[fim]
    total = _dinheiro(total_linha[0])
    if total is None:
        return None, 0.0
    notas = [fornecedor[1], cnpj_linha[1], data_linha[1], total_linha[1], *notas_itens]
    return {
        "fornecedor": fornecedor[0],
        "cnpj": cnpj,
        "data": data,
        "itens": itens,
        "valor_total": total,
    }, min(notas)


def _tabela(linhas: list[tuple[str, float]]) -> tuple[list[dict], list[float]]:
    itens: list[dict] = []
    notas: list[float] = []
    index = 0
    while index < len(linhas):
        descricao, nota_descricao = linhas[index]
        if _so_dinheiro(descricao) or re.fullmatch(r"\d+", descricao.strip()):
            return [], []
        if index + 3 >= len(linhas):
            return [], []
        quantidade = linhas[index + 1]
        total = linhas[index + 3]
        qtd = quantidade[0].strip().replace(",", ".")
        valor = _dinheiro(total[0])
        if not re.fullmatch(r"\d+(?:\.\d+)?", qtd) or valor is None:
            return [], []
        itens.append({"descricao": descricao.strip(), "quantidade": float(qtd), "valor": valor})
        notas.extend((nota_descricao, quantidade[1], linhas[index + 2][1], total[1]))
        index += 4
    return itens, notas


def _contrato(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    cabecalho = _sem_acento(linhas[0][0]) if linhas else ""
    if cabecalho.startswith("ACORDO DE SERVICO"):
        return _acordo(linhas)
    if cabecalho.startswith("CONTRATO DE PRESTACAO"):
        return _clausulas(linhas)
    if cabecalho.startswith("CONTRATO DE SERVICO"):
        return _contrato_curto(linhas)
    return _instrumento(linhas)


def _contrato_curto(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    cliente = _linha_depois(linhas, "CLIENTE")
    prestador = _linha_depois(linhas, "PRESTADOR")
    objeto, nota_objeto = _faixa(linhas, "DESCRICAO DO SERVICO", "DE/ATE")
    periodo = _linha_com_duas_datas(linhas)
    valor_linha = _linha_valor_mensal(linhas)
    if not all((cliente, prestador, objeto, periodo, valor_linha)):
        return None, 0.0
    contratante, _cnpj_cliente = _nome_e_cnpj(cliente[0])
    contratado, _cnpj_prestador = _nome_e_cnpj(prestador[0])
    datas = _datas_na_linha(periodo[0])
    valor = _dinheiro(valor_linha[0])
    if len(datas) < 2 or valor is None or not contratante or not contratado:
        return None, 0.0
    notas = [cliente[1], prestador[1], nota_objeto, periodo[1], valor_linha[1]]
    return {
        "contratante": contratante,
        "contratado": contratado,
        "objeto": objeto,
        "vigencia_inicio": datas[0],
        "vigencia_fim": datas[1],
        "valor_mensal": valor,
    }, min(notas)


def _nfe(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    fornecedor = _valor_na_mesma_linha(linhas, "RAZAO SOCIAL")
    inscricao = _linha_que_contem(linhas, "INSCRICAO")
    if not all((fornecedor, inscricao)):
        return None, 0.0
    cnpj = _cnpj(inscricao[0])
    data, nota_data = _data_da_inscricao(linhas)
    if cnpj is None or data is None:
        return None, 0.0
    inicio = _indice(linhas, "V.TOT.")
    fim = _indice(linhas, "MONTANTE")
    if inicio < 0 or fim < 0:
        return None, 0.0
    itens, notas_itens = _tabela(linhas[inicio + 1 : fim])
    if not itens:
        return None, 0.0
    total = _dinheiro(linhas[fim + 1][0]) if fim + 1 < len(linhas) else None
    if total is None:
        return None, 0.0
    notas = [fornecedor[1], nota_data, linhas[fim + 1][1], *notas_itens]
    return {
        "fornecedor": fornecedor[0],
        "cnpj": cnpj,
        "data": data,
        "itens": itens,
        "valor_total": total,
    }, min(notas)


def _instrumento(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    tomador, nota_tomador = _faixa(linhas, "TOMADOR DO SERVICO", "FORNECEDOR DO SERVICO")
    fornecedor, nota_fornecedor = _faixa(linhas, "FORNECEDOR DO SERVICO", "ESCOPO")
    objeto, nota_objeto = _faixa(linhas, "ESCOPO", "DURACAO")
    duracao = _linha_que_contem(linhas, "INICIO:")
    preco = _linha_depois(linhas, "PRECO ACORDADO")
    if not all((tomador, fornecedor, objeto, duracao, preco)):
        return None, 0.0
    datas = _datas_na_linha(duracao[0])
    valor = _dinheiro(preco[0])
    if len(datas) < 2 or valor is None:
        return None, 0.0
    notas = [nota_tomador, nota_fornecedor, nota_objeto, duracao[1], preco[1]]
    return {
        "contratante": _nome_antes_da_virgula(tomador),
        "contratado": _nome_antes_da_virgula(fornecedor),
        "objeto": objeto,
        "vigencia_inicio": datas[0],
        "vigencia_fim": datas[1],
        "valor_mensal": valor,
    }, min(notas)


def _acordo(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    depois_das_partes = max(_indice(linhas, "PARTE A"), _indice(linhas, "PARTE B")) + 1
    fim_partes = _indice(linhas, "SERVICOS")
    nomes = [
        (texto, nota)
        for texto, nota in linhas[depois_das_partes:fim_partes]
        if not _CNPJ.search(texto)
        and not _sem_acento(texto).startswith(("AV ", "AV.", "RUA ", "CEP"))
        and "PARTE " not in _sem_acento(texto)
    ]
    objeto, nota_objeto = _faixa(linhas, "SERVICOS", "PERIODO DE CONTRATO")
    periodo = _linha_com_duas_datas(linhas)
    remuneracao = _linha_valor_mensal(linhas)
    if len(nomes) < 2 or not objeto or periodo is None or remuneracao is None:
        return None, 0.0
    datas = _datas_na_linha(periodo[0])
    valor = _dinheiro(remuneracao[0])
    if len(datas) < 2 or valor is None:
        return None, 0.0
    notas = [nomes[0][1], nomes[1][1], nota_objeto, periodo[1], remuneracao[1]]
    return {
        "contratante": nomes[0][0],
        "contratado": nomes[1][0],
        "objeto": objeto,
        "vigencia_inicio": datas[0],
        "vigencia_fim": datas[1],
        "valor_mensal": valor,
    }, min(notas)


def _clausulas(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    contratante, nota_contratante = _faixa(linhas, "CONTRATANTE", "CONTRATADA")
    contratado, nota_contratado = _faixa(linhas, "CONTRATADA", "CLAUSULA PRIMEIRA")
    objeto, nota_objeto = _faixa(linhas, "DO OBJETO", "CLAUSULA SEGUNDA")
    vigencia = _linha_que_contem(linhas, "VIGENCIA DE")
    if vigencia is None:
        vigencia = _linha_depois(linhas, "DA VIGENCIA")
    valor_linha = _linha_que_contem(linhas, "VALOR MENSAL")
    if not all((contratante, contratado, objeto, vigencia, valor_linha)):
        return None, 0.0
    datas = _datas_na_linha(vigencia[0])
    valor = _dinheiro(valor_linha[0])
    if len(datas) < 2 or valor is None:
        return None, 0.0
    notas = [nota_contratante, nota_contratado, nota_objeto, vigencia[1], valor_linha[1]]
    return {
        "contratante": _nome_inscrito(contratante),
        "contratado": _nome_inscrito(contratado),
        "objeto": objeto,
        "vigencia_inicio": datas[0],
        "vigencia_fim": datas[1],
        "valor_mensal": valor,
    }, min(notas)


def _relatorio(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    cabecalho = _sem_acento(linhas[0][0]) if linhas else ""
    if cabecalho.startswith("ORDEM DE SERVICO"):
        return _ordem(linhas)
    if cabecalho.startswith("RELATORIO TECNICO"):
        return _tecnico_relatorio(linhas)
    return _ficha(linhas)


def _ordem(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    data_linha = _linha_depois(linhas, "REALIZADO EM")
    tecnico_linha = _linha_depois(linhas, "PROFISSIONAL")
    ativo = _linha_depois(linhas, "ATIVO")
    problema, nota_problema = _faixa(linhas, "DEFEITO ENCONTRADO", "REPARO EFETUADO")
    solucao, nota_solucao = _faixa(linhas, "REPARO EFETUADO", "SITUACAO")
    if not all((data_linha, tecnico_linha, ativo, problema, solucao)):
        return None, 0.0
    data = _data_de_texto(data_linha[0])
    if not data:
        return None, 0.0
    notas = [data_linha[1], tecnico_linha[1], ativo[1], nota_problema, nota_solucao]
    return {
        "data": data,
        "tecnico": _pessoa(tecnico_linha[0]),
        "equipamento": ativo[0],
        "problema": problema,
        "solucao": solucao,
    }, min(notas)


def _tecnico_relatorio(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    data_linha = _linha_que_contem(linhas, "DATA:")
    tecnico_linha = _linha_depois(linhas, "NOME DO TECNICO")
    equipamento, nota_equipamento = _faixa(linhas, "IDENTIFICACAO DO EQUIPAMENTO", "DIAGNOSTICO")
    problema, nota_problema = _faixa(linhas, "DIAGNOSTICO", "ACAO CORRETIVA")
    solucao, nota_solucao = _faixa(linhas, "ACAO CORRETIVA", "FIM QUE NAO EXISTE")
    if not all((data_linha, tecnico_linha, equipamento, problema, solucao)):
        return None, 0.0
    data = _data_de_texto(data_linha[0].split(":", 1)[-1].strip())
    if not data:
        return None, 0.0
    notas = [data_linha[1], tecnico_linha[1], nota_equipamento, nota_problema, nota_solucao]
    return {
        "data": data,
        "tecnico": _pessoa(tecnico_linha[0]),
        "equipamento": equipamento,
        "problema": problema,
        "solucao": solucao,
    }, min(notas)


def _ficha(linhas: list[tuple[str, float]]) -> tuple[dict | None, float]:
    data_linha = _linha_depois(linhas, "DT. EXECUCAO")
    tecnico_linha = _linha_depois(linhas, "COLABORADOR")
    equipamento = _valor_na_mesma_linha(linhas, "EQUIPAMENTO")
    problema, nota_problema = _faixa(linhas, "OCORRENCIA", "PROCEDIMENTO ADOTADO")
    solucao, nota_solucao = _faixa(linhas, "PROCEDIMENTO ADOTADO", "PECAS/MATERIAIS")
    if solucao == "" and nota_solucao == 0:
        solucao, nota_solucao = _faixa(linhas, "PROCEDIMENTO ADOTADO", "PECAS")
    if not all((data_linha, tecnico_linha, equipamento, problema, solucao)):
        return None, 0.0
    data = _data_de_texto(data_linha[0])
    if not data:
        return None, 0.0
    tecnico = _pessoa(tecnico_linha[0])
    notas = [data_linha[1], tecnico_linha[1], equipamento[1], nota_problema, nota_solucao]
    return {
        "data": data,
        "tecnico": tecnico,
        "equipamento": equipamento[0],
        "problema": problema,
        "solucao": solucao,
    }, min(notas)


def _faixa(linhas: list[tuple[str, float]], inicio: str, fim: str) -> tuple[str, float]:
    começo = _indice(linhas, inicio)
    if começo < 0:
        return "", 0.0
    termina = _indice(linhas, fim, começo + 1)
    trecho = linhas[começo + 1 : termina if termina >= 0 else None]
    trecho = [(texto, nota) for texto, nota in trecho if not _ignorar(texto)]
    if not trecho:
        return "", 0.0
    return " ".join(texto for texto, _nota in trecho).strip(), min(nota for _texto, nota in trecho)


def _indice(linhas: list[tuple[str, float]], rotulo: str, desde: int = 0) -> int:
    for index, (texto, _nota) in enumerate(linhas[desde:], desde):
        if _bate(_sem_acento(texto), rotulo):
            return index
    return -1


def _bate(chave: str, rotulo: str) -> bool:
    if chave == rotulo or chave.startswith(rotulo + " ") or chave.startswith(rotulo + ":"):
        return True
    return chave.endswith(" - " + rotulo)


def _indice_contem(linhas: list[tuple[str, float]], rotulo: str, desde: int = 0) -> int:
    for index, (texto, _nota) in enumerate(linhas[desde:], desde):
        if rotulo in _sem_acento(texto):
            return index
    return -1


def _linha_depois(linhas: list[tuple[str, float]], rotulo: str) -> tuple[str, float] | None:
    index = _indice(linhas, rotulo)
    if index < 0:
        return None
    cursor = index + 1
    while cursor < len(linhas) and _ignorar(linhas[cursor][0]):
        cursor += 1
    if cursor >= len(linhas):
        return None
    return linhas[cursor]


def _linha_que_contem(linhas: list[tuple[str, float]], rotulo: str) -> tuple[str, float] | None:
    index = _indice_contem(linhas, rotulo)
    if index < 0:
        return None
    return linhas[index]


def _valor_na_mesma_linha(linhas: list[tuple[str, float]], rotulo: str) -> tuple[str, float] | None:
    index = _indice(linhas, rotulo)
    if index < 0:
        return None
    texto, nota = linhas[index]
    if ":" not in texto:
        return None
    return texto.split(":", 1)[1].strip(), nota


def _datas_na_linha(texto: str) -> list[str]:
    padrao = re.compile(
        r"\d{1,2}\s+de\s+[A-Za-zçÇ]+\s+de\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",
        re.IGNORECASE,
    )
    achadas: list[str] = []
    for token in padrao.findall(texto):
        convertida = _uma_data(token)
        if convertida:
            achadas.append(convertida)
    return achadas


def _uma_data(token: str) -> str | None:
    if _DATA_ISO.fullmatch(token):
        return token
    extenso = _DATA_EXTENSO.fullmatch(token)
    if extenso:
        dia, mes, ano = extenso.groups()
        numero = _MESES.get(_sem_acento(mes).lower())
        if numero:
            return f"{int(ano):04d}-{numero:02d}-{int(dia):02d}"
        return None
    return _data(token.replace(".", "/").replace("-", "/"))


def _linha_com_duas_datas(linhas: list[tuple[str, float]]) -> tuple[str, float] | None:
    for texto, nota in linhas:
        if len(_datas_na_linha(texto)) >= 2:
            return texto, nota
    return None


def _linha_valor_mensal(linhas: list[tuple[str, float]]) -> tuple[str, float] | None:
    for texto, nota in linhas:
        chave = _sem_acento(texto)
        if _dinheiro(texto) is None:
            continue
        if re.search(r"MENSA|/MES|\bMES\b", chave):
            return texto, nota
    return None


def _data_da_inscricao(linhas: list[tuple[str, float]]) -> tuple[str | None, float]:
    index = _indice_contem(linhas, "INSCRICAO")
    if index < 0:
        return None, 0.0
    datas = _datas_na_linha(linhas[index][0])
    nota = linhas[index][1]
    if not datas and index + 1 < len(linhas) and _sem_acento(linhas[index + 1][0]).startswith("DT"):
        datas = _datas_na_linha(linhas[index + 1][0])
        nota = min(nota, linhas[index + 1][1])
    if not datas:
        return None, 0.0
    return datas[0], nota


def _data_de_texto(texto: str) -> str | None:
    direta = _data(texto.strip())
    if direta:
        return direta
    achadas = _datas_na_linha(texto)
    return achadas[0] if achadas else None


def _cnpj(texto: str) -> str | None:
    mascarado = _CNPJ.search(texto)
    if mascarado:
        return mascarado.group(0)
    if re.search(r"\d{2}\.\d{3}\.\d{3}/\d{5,}", texto):
        return None
    corridos = re.findall(r"\d{14}", texto)
    if len(corridos) != 1:
        return None
    candidato = corridos[0]
    return (
        f"{candidato[:2]}.{candidato[2:5]}.{candidato[5:8]}/"
        f"{candidato[8:12]}-{candidato[12:]}"
    )


def _nome_e_cnpj(texto: str) -> tuple[str, str | None]:
    mascarado = _CNPJ.search(texto)
    if mascarado:
        return texto[: mascarado.start()].strip(" -"), mascarado.group(0)
    return texto.strip(), _cnpj(texto)


def _data(token: str) -> str | None:
    token = token.strip().rstrip(".")
    iso = _DATA_ISO.fullmatch(token)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    numerica = _DATA_NUM.fullmatch(token)
    if not numerica:
        return None
    dia, mes, ano = (int(parte) for parte in numerica.groups())
    if ano < 100:
        ano += 2000 if ano < 70 else 1900
    return f"{ano:04d}-{mes:02d}-{dia:02d}"


def _dinheiro(texto: str) -> float | None:
    achado = _DINHEIRO.search(texto)
    if not achado:
        return None
    token = achado.group(1) or achado.group(2)
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    try:
        return float(token)
    except ValueError:
        return None


def _quantidade(texto: str) -> float | None:
    achado = _QTD.search(texto)
    if not achado:
        return None
    return float(achado.group(1).replace(",", "."))


def _so_dinheiro(texto: str) -> bool:
    limpo = texto.strip()
    if _quantidade(limpo) is not None or limpo.startswith("-"):
        return False
    return _dinheiro(limpo) is not None and bool(
        re.fullmatch(r"(?:(?:R\$|BRL)\s*)?[\d.]+,\d{2}", limpo, re.IGNORECASE)
    )


def _pessoa(texto: str) -> str:
    sem_matricula = re.sub(r"\s*\((?:mat\.?\s*)?[^)]*\)\s*$", "", texto, flags=re.IGNORECASE)
    return re.sub(r"\s+-\s+.*$", "", sem_matricula).strip()


def _ignorar(texto: str) -> bool:
    chave = _sem_acento(texto).strip()
    return bool(re.fullmatch(r"\d+\.", texto.strip())) or chave in {"[X]", "X"}


def _nome_antes_da_virgula(texto: str) -> str:
    return texto.split(",", 1)[0].strip()


def _nome_inscrito(texto: str) -> str:
    return re.split(r",?\s+inscrit", texto, maxsplit=1, flags=re.IGNORECASE)[0].strip(" ,")


@lru_cache(maxsize=512)
def _sem_acento(texto: str) -> str:
    base = unicodedata.normalize("NFD", texto)
    sem = "".join(caractere for caractere in base if unicodedata.category(caractere) != "Mn")
    return sem.upper()
