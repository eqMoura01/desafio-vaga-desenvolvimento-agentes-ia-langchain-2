from src.ingest import Loaded
from src.ocr import interpretar
from src.pipeline import process_one
from tests.test_pipeline import Scripted, _doc


FICHA = [
    ("FICHA DE SERVIÇO", 0.999),
    ("Dt. Execução", 0.999),
    ("2023-07-10", 0.999),
    ("Patrimônio", 1.0),
    ("TI-2020-0156", 0.999),
    ("Colaborador", 0.999),
    ("Fernanda Costa Santo - 298765", 0.996),
    ("Equipamento: Servidor | Modelo: Dell PowerEdge R740 | Local: Data Center - Rack 07", 0.997),
    ("Ocorrência", 0.999),
    ("Servidor apresentando lentidão extrema e timeouts frequentes nas aplicações.", 0.995),
    ("Procedimento Adotado", 0.999),
    ("Realizada limpeza completa interna do servidor.", 0.994),
    ("Peças/Materiais:", 0.99),
]

FATURA = [
    ("FATURA", 1.0),
    ("Emitido em: 15/03/23", 0.999),
    ("Tech Solutions Ltda", 0.999),
    ("Documento: 12.345.678/0001-90", 0.988),
    ("Produtos", 1.0),
    ("- Notebook Dell Inspiron 15", 0.977),
    ("5 x R$ 3899,99", 0.995),
    ("BRL 19.499,95", 0.975),
    ("- Monitor LG 24 polegadas Full HD", 0.99),
    ("5 × 899,00", 0.953),
    ("BRL 4.495,00", 0.999),
    ("Total Geral", 1.0),
    ("R$ 25791,45", 1.0),
]

INSTRUMENTO_FRACO = [
    ("INSTRUMENTO PARTICULAR DE CONTRATO", 0.999),
    ("TOMADOR DO SERVIÇO", 0.999),
    ("Maria Aparecida Santos Silva, 123.456.789-00, Rua das Acácias, 234", 0.996),
    ("FORNECEDOR DO SERVIÇO", 0.998),
    ("Advocacia Especializada Dr. Roberto Mendes, 45.678.901/0001-23, Av. Presidente Vargas", 0.989),
    ("Escopo", 1.0),
    ("Prestação de serviços advocatícios para inventário.", 0.997),
    ("dae   ç  o  o n  oo d dio", 0.643),
    ("Duração", 1.0),
    ("Início: 2024-02-10 | Término: 10/08/2024", 0.971),
    ("Preço Acordado", 1.0),
    ("R$ 2.800,00 por mês", 0.996),
]

ACORDO = [
    ("ACORDO DE SERVIÇOS", 0.993),
    ("Parte A", 0.999),
    ("Parte B", 0.999),
    ("Hospital Regional São Lucas S.A.", 0.995),
    ("TechMed Sistemas de Informação Ltda", 0.994),
    ("23.098.765/0001-32", 0.99),
    ("34.567.654/0001-43", 0.99),
    ("Av. Getúlio Vargas, 5000, Centro, Porto Alegre - RS, CEP", 0.98),
    ("Rua dos Andradas, 1234, Sala 601", 0.98),
    ("Serviços", 0.999),
    ("Prestação de serviços de desenvolvimento do HIS.", 0.997),
    ("Período de Contrato", 0.999),
    ("Remuneração", 0.999),
    ("01/06/2024 - 31.05.2026", 0.993),
    ("R$ 45.000,00 /mês", 0.991),
]

CLAUSULAS = [
    ("CONTRATO DE PRESTAÇÃO DE SERVIÇOS", 0.996),
    ("CONTRATANTE", 1.0),
    ("Ana Paula Ribeiro Costa MEI, inscrito no CNPJ/CPF sob o nº 01234987000110.", 0.987),
    ("CONTRATADA", 1.0),
    ("WebDev Curitiba Desenvolvimento de Software Ltda, inscrito no CNPJ/CPF sob o nº 12.345.876/0001-21.", 0.991),
    ("CLÁUSULA PRIMEIRA - DO OBJETO", 0.961),
    ("Prestação de serviços de loja virtual.", 0.997),
    ("me ro oo  o td  a  o o ars", 0.604),
    ("CLÁUSULA SEGUNDA - DA VIGÊNCIA", 0.999),
    ("O presente contrato terá vigência de 01-03-2024 a 30 de junho de 2024.", 0.999),
    ("CLÁUSULA TERCEIRA - DO VALOR", 0.986),
    ("Valor Mensal: R$ 3200,00", 0.991),
]


def test_ficha_stays_with_ocr_and_drops_the_badge_number():
    leitura = interpretar(FICHA)
    assert leitura["confianca"] >= 0.80
    assert leitura["tipo"] == "relatorio_manutencao"
    assert leitura["dados"]["tecnico"] == "Fernanda Costa Santo"
    assert leitura["dados"]["data"] == "2023-07-10"
    assert leitura["dados"]["equipamento"].startswith("Servidor")


def test_fatura_reads_split_lines_and_the_short_year():
    leitura = interpretar(FATURA)
    assert leitura["confianca"] >= 0.80
    assert leitura["dados"]["data"] == "2023-03-15"
    assert leitura["dados"]["cnpj"] == "12.345.678/0001-90"
    assert leitura["dados"]["itens"][1]["descricao"].startswith("Monitor")
    assert leitura["dados"]["itens"][1]["quantidade"] == 5
    assert leitura["dados"]["itens"][1]["valor"] == 4495.0
    assert leitura["dados"]["valor_total"] == 25791.45


def test_garbled_scope_stays_below_the_agent_threshold():
    instrumento = interpretar(INSTRUMENTO_FRACO)
    clausulas = interpretar(CLAUSULAS)
    assert instrumento["confianca"] < 0.80
    assert clausulas["confianca"] < 0.80
    assert clausulas["dados"]["vigencia_inicio"] == "2024-03-01"
    assert clausulas["dados"]["vigencia_fim"] == "2024-06-30"


def test_work_order_and_technical_report_use_ocr():
    ordem = interpretar([
        ("ORDEM DE SERVIÇO", 0.999),
        ("[x]", 0.97),
        ("Realizado em", 0.994),
        ("14/09/2023", 1.0),
        ("Profissional", 1.0),
        ("Marcos Vinícius Almeida (312456)", 0.992),
        ("Ativo", 1.0),
        ("Elevador de Passagei - Atlas Schindler 3300", 0.983),
        ("Defeito Encontrado", 1.0),
        ("Elevador parando entre andares.", 0.997),
        ("Reparo Efetuado", 1.0),
        ("Substituição do encoder incremental.", 0.994),
        ("Situação: Concluído", 0.999),
    ])
    tecnico = interpretar([
        ("Relatório Técnico", 0.997),
        ("Data: 18.11.2023", 0.997),
        ("Nome do Técnico", 1.0),
        ("Ricardo Barbosa Lima - Mecânica Automotiva (Mat. 198234)", 0.995),
        ("Identificação do Equipamento", 0.999),
        ("Tipo: Empilhadeira", 1.0),
        ("Modelo: Toyota 8FG25", 0.999),
        ("Diagnóstico", 1.0),
        ("Bicos injetores com vazamento.", 0.996),
        ("Ação Corretiva", 0.999),
        ("Substituição do jogo de bicos.", 0.994),
    ])
    assert ordem["confianca"] >= 0.80
    assert ordem["dados"]["tecnico"] == "Marcos Vinícius Almeida"
    assert ordem["dados"]["data"] == "2023-09-14"
    assert tecnico["confianca"] >= 0.80
    assert tecnico["dados"]["tecnico"] == "Ricardo Barbosa Lima"
    assert tecnico["dados"]["data"] == "2023-11-18"
    assert "Empilhadeira" in tecnico["dados"]["equipamento"]


def test_fiscal_document_without_a_masked_cnpj_goes_to_the_agent():
    leitura = interpretar([
        ("DOCUMENTO FISCAL", 0.992),
        ("Nome do Fornecedor: Limpeza Industrial HigienMax Eireli", 0.991),
        ("CNPJ/MF: 44.555.666/000177", 0.993),
        ("Data: 10/09/2024", 0.975),
        ("Valor Item", 1.0),
        ("Detergente industrial 5L", 1.0),
        ("30", 1.0),
        ("32,90", 1.0),
        ("987,00", 1.0),
        ("Valor a Pagar", 1.0),
        ("5.157,50", 1.0),
    ])
    assert leitura["confianca"] < 0.80


def test_service_contract_and_a_written_out_date_stay_on_ocr():
    contrato = interpretar([
        ("Contrato de Serviço", 0.996),
        ("Cliente", 1.0),
        ("Shopping Center Vitória Mall S.A. - 56.789.432/0001-65", 0.996),
        ("Prestador", 1.0),
        ("Climatizar Ar Condicionado Industrial Ltda - 67.890.321/0001-76", 0.997),
        ("Descrição do Serviço", 0.999),
        ("Prestação de serviços de manutenção preventiva e corretiva.", 0.992),
        ("De/Até", 1.0),
        ("01-07-2024 até 30/06/2026", 0.987),
        ("Honorários", 1.0),
        ("R$ 52000,00 mensais", 0.988),
    ])
    ordem = interpretar([
        ("ORDEM DE SERVIÇO", 0.999),
        ("Realizado em", 1.0),
        ("14 de setembro de 2023", 1.0),
        ("Profissional", 1.0),
        ("Marcos Vinícius Almeida (312456)", 0.992),
        ("Ativo", 1.0),
        ("Elevador de Passagei - Atlas Schindler 3300", 0.983),
        ("Defeito Encontrado", 1.0),
        ("Elevador parando entre andares.", 0.997),
        ("Reparo Efetuado", 1.0),
        ("Substituição do encoder incremental.", 0.994),
        ("Situação: Concluído", 0.999),
    ])
    assert contrato["confianca"] >= 0.80
    assert contrato["dados"]["contratante"] == "Shopping Center Vitória Mall S.A."
    assert contrato["dados"]["contratado"] == "Climatizar Ar Condicionado Industrial Ltda"
    assert contrato["dados"]["vigencia_inicio"] == "2024-07-01"
    assert contrato["dados"]["vigencia_fim"] == "2026-06-30"
    assert contrato["dados"]["valor_mensal"] == 52000.0
    assert ordem["confianca"] >= 0.80
    assert ordem["dados"]["data"] == "2023-09-14"


def test_fourteen_digits_become_a_cnpj_and_a_broken_mask_does_not():
    nota = interpretar([
        ("FATURA", 1.0),
        ("Emitido em: 12/11/24", 0.997),
        ("Transportadora Carga Segura S.A.", 0.997),
        ("Documento: 77888999000100", 0.994),
        ("Produtos", 1.0),
        ("- Frete rodoviário", 1.0),
        ("2 x BRL 3.200,00", 0.995),
        ("BRL 6.400,00", 1.0),
        ("Total Geral", 0.997),
        ("R$ 13160,00", 0.983),
    ])
    assert nota["confianca"] >= 0.80
    assert nota["dados"]["cnpj"] == "77.888.999/0001-00"
    assert nota["dados"]["data"] == "2024-11-12"
    quebrada = interpretar([
        ("NF-e", 1.0),
        ("Razão Social: Móveis Escritório Confort", 0.988),
        ("Inscrição: 66.777.888/000199 Dt. 28 de outubro de 2024", 0.996),
        ("V.Tot.", 0.999),
        ("Cadeira", 1.0),
        ("5", 1.0),
        ("BRL 1.290,00", 0.993),
        ("R$ 6450,00", 0.998),
        ("Montante", 1.0),
        ("R$ 14.760,00", 0.998),
    ])
    assert quebrada["confianca"] < 0.80


def test_invoice_table_keeps_a_measure_inside_the_description():
    fiscal = interpretar([
        ("DOCUMENTO FISCAL", 0.999),
        ("Nome do Fornecedor: Móveis Escritório Conforto ME", 0.999),
        ("CNPJ/MF: 66.777.888/0001-99", 0.959),
        ("Data: 28.10.2024", 0.990),
        ("Valor Item", 0.977),
        ("Mesa escritório 1,50m c/ gavetas", 0.995),
        ("5", 1.0),
        ("R$850,00", 0.999),
        ("R$ 4.250,00", 0.996),
        ("Valor a Pagar", 0.972),
        ("BRL 14.760,00", 1.0),
    ])
    nota = interpretar([
        ("NF-e", 1.0),
        ("Razão Social: Indústria Têxtil Fibras d", 0.994),
        ("Inscrição: 90123456000178", 0.994),
        ("Dt. 2024-04-20", 0.996),
        ("V.Tot.", 0.999),
        ("Tecido algodão cru metro linear", 0.997),
        ("500", 1.0),
        ("18,90", 1.0),
        ("BRL 9.450,00", 0.988),
        ("Montante", 1.0),
        ("R$15.150,00", 1.0),
    ])
    assert fiscal["confianca"] >= 0.80
    assert "1,50m" in fiscal["dados"]["itens"][0]["descricao"]
    assert fiscal["dados"]["data"] == "2024-10-28"
    assert nota["confianca"] >= 0.80
    assert nota["dados"]["cnpj"] == "90.123.456/0001-78"
    assert nota["dados"]["data"] == "2024-04-20"
    assert nota["dados"]["itens"][0]["quantidade"] == 500
    assert nota["dados"]["valor_total"] == 15150.0


def test_side_by_side_agreement_keeps_the_two_parties():
    leitura = interpretar(ACORDO)
    assert leitura["confianca"] >= 0.80
    assert leitura["dados"]["contratante"] == "Hospital Regional São Lucas S.A."
    assert leitura["dados"]["contratado"] == "TechMed Sistemas de Informação Ltda"
    assert leitura["dados"]["vigencia_inicio"] == "2024-06-01"
    assert leitura["dados"]["vigencia_fim"] == "2026-05-31"
    assert leitura["dados"]["valor_mensal"] == 45000.0


def test_confident_ocr_does_not_call_the_model(monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.ler_documento",
        lambda doc: {
            "tipo": "relatorio_manutencao",
            "confianca": 0.97,
            "dados": {
                "data": "2023-07-10",
                "tecnico": "Fernanda Costa Santo",
                "equipamento": "Servidor",
                "problema": "Lentidão",
                "solucao": "Limpeza",
            },
            "texto": "FICHA",
        },
    )

    class Explode:
        def classify(self, doc: Loaded):
            raise AssertionError("o agente não deveria classificar")

        def extract(self, doc: Loaded, tipo: str, error: str | None = None):
            raise AssertionError("o agente não deveria extrair")

    result = process_one(_doc("ficha.pdf"), Explode())
    assert result["origem"] == "ocr"
    assert result["dados"]["tecnico"] == "Fernanda Costa Santo"


def test_weak_ocr_still_calls_the_model(monkeypatch):
    monkeypatch.setattr(
        "src.pipeline.ler_documento",
        lambda doc: {"tipo": "contrato", "confianca": 0.64, "dados": {"objeto": "ilegível"}, "texto": "contrato"},
    )
    result = process_one(_doc("contrato.pdf"), Scripted())
    assert result["origem"] == "agente"
    assert result["tipo"] == "relatorio_manutencao"
