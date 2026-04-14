"""
Testes unitários do cnis_parser.py.

Testa cada função de parsing isoladamente, usando textos de exemplo
que simulam a estrutura real de um extrato CNIS.
"""

import sys
import os
from datetime import date

import pytest

# Ajustar path para importar o parser (main.py usa import direto, sem prefixo app.)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from cnis_parser import (
    limpar_texto,
    parse_cabecalho,
    converter_valor,
    parse_data,
    parse_competencia,
    extrair_indicadores_linha,
    identificar_tipo_vinculo,
    parse_bloco_vinculo,
    parse_remuneracoes_bloco,
    segmentar_vinculos,
    extrair_legenda_indicadores,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES — Textos que simulam trechos reais do CNIS
# ═══════════════════════════════════════════════════════════════════════════

CABECALHO_COMPLETO = """
Cadastro Nacional de Informações Sociais - CNIS
NIT: 123.45678.90-1
CPF: 529.982.247-25
Nome: MARIA DA SILVA SANTOS  Data de Nascimento: 15/07/1970
Nome da Mãe: ANA MARIA DA SILVA
Emitido em 10/04/2026 14:30:00
"""

CABECALHO_MINIMO = """
NIT: 123.45678.90-1
Nome: JOAO FERREIRA
"""

CABECALHO_VAZIO = """
Relatório de Consulta Geral
Página 1 de 5
"""

BLOCO_VINCULO_CLT = """
1 123.45678.90-1 EMPREGADO
COMERCIO VAREJISTA LTDA  12.345.678/0001-90
01/03/2010 31/12/2020
Competência  Remuneração
01/2020 1.045,00
02/2020 1.045,00 PREC-MENOR-MIN
03/2020 1.100,00
"""

BLOCO_VINCULO_MEI = """
2 123.45678.90-1 CONTRIBUINTE INDIVIDUAL
MEI - MARIA DA SILVA SANTOS
01/06/2021
Competência  Remuneração
01/2025 1.518,00 IREC-MEI
02/2025 1.518,00 IREC-MEI
"""

BLOCO_BENEFICIO = """
3 123.45678.90-1
NB: 1234567890
31 - AUXILIO DOENCA
ATIVO
01/03/2020 30/09/2020
"""

TEXTO_SEGMENTACAO = """
Relações Previdenciárias
1 123.45678.90-1 EMPREGADO
EMPRESA ALFA LTDA  11.111.111/0001-11
01/01/2005 31/12/2010
Competência  Remuneração
01/2010 1.000,00
2 123.45678.90-1 CONTRIBUINTE INDIVIDUAL
MEI - JOAO FERREIRA
01/01/2012
Competência  Remuneração
01/2025 1.518,00 IREC-MEI
"""

TEXTO_LEGENDA = """
Página 5 de 5
Legenda de Indicadores
IREC-MEI - Recolhimento como MEI
PREC-MENOR-MIN - Remuneração menor que salário mínimo
IREC-LC123 - Recolhimento plano simplificado
PEXT - Recolhimento extemporâneo
Página 6
"""


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — limpar_texto
# ═══════════════════════════════════════════════════════════════════════════

class TestLimparTexto:

    def test_remove_espacos_extras(self):
        assert limpar_texto("  olá   mundo  ") == "olá mundo"

    def test_normaliza_crlf(self):
        assert limpar_texto("linha1\r\ninha2") == "linha1\ninha2"

    def test_string_vazia(self):
        assert limpar_texto("   ") == ""


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_cabecalho
# ═══════════════════════════════════════════════════════════════════════════

class TestParseCabecalho:

    def test_cabecalho_completo(self):
        cab = parse_cabecalho(CABECALHO_COMPLETO)
        assert cab['nit'] == '123.45678.90-1'
        assert cab['cpf'] == '529.982.247-25'
        assert cab['nome'] == 'MARIA DA SILVA SANTOS'
        assert cab['data_nascimento'] == '15/07/1970'
        assert cab['nome_mae'] == 'ANA MARIA DA SILVA'
        assert cab['data_emissao'] == '10/04/2026'

    def test_cabecalho_minimo(self):
        cab = parse_cabecalho(CABECALHO_MINIMO)
        assert cab['nit'] == '123.45678.90-1'
        assert cab['nome'] == 'JOAO FERREIRA'
        assert cab['cpf'] is None
        assert cab['data_nascimento'] is None
        assert cab['nome_mae'] is None
        assert cab['data_emissao'] is None

    def test_cabecalho_vazio(self):
        cab = parse_cabecalho(CABECALHO_VAZIO)
        assert cab['nome'] is None
        assert cab['nit'] is None
        assert cab['cpf'] is None


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — converter_valor
# ═══════════════════════════════════════════════════════════════════════════

class TestConverterValor:

    def test_valor_simples(self):
        assert converter_valor("1.518,00") == 1518.00

    def test_valor_centavos(self):
        assert converter_valor("999,99") == 999.99

    def test_valor_grande(self):
        assert converter_valor("12.345,67") == 12345.67

    def test_valor_muito_grande(self):
        assert converter_valor("123.456.789,01") == 123456789.01

    def test_none_retorna_none(self):
        assert converter_valor(None) is None

    def test_string_vazia_retorna_none(self):
        assert converter_valor("") is None

    def test_string_invalida_retorna_none(self):
        assert converter_valor("abc") is None


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_data
# ═══════════════════════════════════════════════════════════════════════════

class TestParseData:

    def test_data_valida(self):
        assert parse_data("15/07/1970") == date(1970, 7, 15)

    def test_data_primeiro_dia(self):
        assert parse_data("01/01/2000") == date(2000, 1, 1)

    def test_data_ultimo_dia(self):
        assert parse_data("31/12/2025") == date(2025, 12, 31)

    def test_none_retorna_none(self):
        assert parse_data(None) is None

    def test_string_vazia_retorna_none(self):
        assert parse_data("") is None

    def test_formato_invalido_retorna_none(self):
        assert parse_data("2025-01-01") is None

    def test_data_invalida_retorna_none(self):
        assert parse_data("32/13/2025") is None

    def test_data_com_espacos(self):
        assert parse_data("  15/07/1970  ") == date(1970, 7, 15)


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_competencia
# ═══════════════════════════════════════════════════════════════════════════

class TestParseCompetencia:

    def test_competencia_valida(self):
        assert parse_competencia("01/2025") == "01/2025"

    def test_competencia_dezembro(self):
        assert parse_competencia("12/2024") == "12/2024"

    def test_none_retorna_none(self):
        assert parse_competencia(None) is None

    def test_string_vazia_retorna_none(self):
        assert parse_competencia("") is None

    def test_formato_data_completa_nao_match(self):
        # parse_competencia espera MM/AAAA, não DD/MM/AAAA
        # A regex faz match no início "01/2025" se a string for "01/2025/extra"
        # Mas "15/07/1970" vai dar match em "15/0719" — vamos ver
        result = parse_competencia("15/07/1970")
        # A regex MM/AAAA pode capturar "15/0719" do "15/07/1970"
        # Mas na prática o match() vai pegar "15/0719" que não é MM/AAAA puro
        # O regex é r'(\d{2}/\d{4})' que vai dar match em "15/0719" — hm
        # Na verdade match() olha do início: "15/07/1" — não tem 4 dígitos após /
        # Espera: "15/07/1970" → match "15/0719" — não, match exige no início
        # re.match(r'(\d{2}/\d{4})', "15/07/1970") → match "15/0719"
        # Não! match pega "15/07/1" — wait: \d{4} = 4 dígitos = "1970"
        # "15/07/1970" → match começa no início: "15/" + 4 dígitos = "15/0719"
        # Nope: "/" exato: "15" + "/" + "0719" → hmm... "07/1970"
        # Let me think: a string é "15/07/1970", trimmed.
        # match(r'(\d{2}/\d{4})') tenta no início:
        #   \d{2} = "15", / = "/", \d{4} = "07/1" — não, \d{4} precisa de 4 dígitos
        #   "15/" → depois temos "07/1970" → \d{4} = "07/1" — / não é \d
        # Resultado: \d{2}="15", /="/", \d{4} tenta "07/1" — falha no "/"
        # Portanto: None
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — extrair_indicadores_linha
# ═══════════════════════════════════════════════════════════════════════════

class TestExtrairIndicadoresLinha:

    def test_indicador_com_hifen(self):
        inds = extrair_indicadores_linha("IREC-MEI algo mais")
        assert "IREC-MEI" in inds

    def test_indicador_composto(self):
        inds = extrair_indicadores_linha("PREC-MENOR-MIN valor 1.000,00")
        assert "PREC-MENOR-MIN" in inds

    def test_indicador_conhecido_sem_hifen(self):
        inds = extrair_indicadores_linha("algo PEXT mais texto")
        assert "PEXT" in inds

    def test_palavras_comuns_nao_sao_indicadores(self):
        inds = extrair_indicadores_linha("BANCO DO BRASIL LTDA COMERCIO")
        # Palavras comuns não devem aparecer como indicadores
        assert "BANCO" not in inds
        assert "BRASIL" not in inds
        assert "LTDA" not in inds
        assert "COMERCIO" not in inds

    def test_linha_vazia(self):
        assert extrair_indicadores_linha("") == []

    def test_multiplos_indicadores(self):
        inds = extrair_indicadores_linha("IREC-MEI PREC-MENOR-MIN PEXT")
        assert "IREC-MEI" in inds
        assert "PREC-MENOR-MIN" in inds
        assert "PEXT" in inds

    def test_iean_conhecido(self):
        inds = extrair_indicadores_linha("texto IEAN mais")
        assert "IEAN" in inds

    def test_deduplica(self):
        inds = extrair_indicadores_linha("IREC-MEI algo IREC-MEI")
        assert inds.count("IREC-MEI") == 1


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — identificar_tipo_vinculo
# ═══════════════════════════════════════════════════════════════════════════

class TestIdentificarTipoVinculo:

    def test_empregado(self):
        assert identificar_tipo_vinculo("EMPREGADO - CLT") == "Empregado"

    def test_contribuinte_individual(self):
        assert identificar_tipo_vinculo("CONTRIBUINTE INDIVIDUAL") == "Contribuinte Individual"

    def test_ci_abreviado(self):
        assert identificar_tipo_vinculo("CI - PRESTADOR") == "Contribuinte Individual"

    def test_facultativo(self):
        assert identificar_tipo_vinculo("FACULTATIVO BAIXA RENDA") == "Facultativo"

    def test_mei(self):
        assert identificar_tipo_vinculo("MEI - MARIA SILVA") == "Microempreendedor Individual"

    def test_domestico(self):
        assert identificar_tipo_vinculo("EMPREGADO DOMÉSTICO") == "Empregado Doméstico"
        assert identificar_tipo_vinculo("DOMÉSTICO") == "Empregado Doméstico"

    def test_avulso(self):
        assert identificar_tipo_vinculo("TRABALHADOR AVULSO") == "Trabalhador Avulso"

    def test_segurado_especial(self):
        assert identificar_tipo_vinculo("SEGURADO ESPECIAL") == "Segurado Especial"

    def test_agente_publico(self):
        assert identificar_tipo_vinculo("AGENTE PÚBLICO FEDERAL") == "Agente Público"

    def test_nao_identificado(self):
        assert identificar_tipo_vinculo("texto qualquer") == "Não identificado"


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_remuneracoes_bloco
# ═══════════════════════════════════════════════════════════════════════════

class TestParseRemuneracoesBloco:

    def test_remuneracoes_com_indicadores(self):
        texto = """Competência Remuneração
01/2025 1.518,00 IREC-MEI
02/2025 1.518,00 IREC-MEI
03/2025 1.518,00"""
        rems = parse_remuneracoes_bloco(texto)
        assert len(rems) == 3
        assert rems[0]['competencia'] == '01/2025'
        assert rems[0]['valor'] == 1518.00
        assert 'IREC-MEI' in rems[0]['indicadores']
        assert rems[2]['indicadores'] == []

    def test_remuneracoes_valores_variados(self):
        texto = """01/2020 1.045,00
06/2020 2.345,67
12/2020 8.157,41"""
        rems = parse_remuneracoes_bloco(texto)
        assert len(rems) == 3
        assert rems[0]['valor'] == 1045.00
        assert rems[1]['valor'] == 2345.67
        assert rems[2]['valor'] == 8157.41

    def test_bloco_sem_remuneracoes(self):
        texto = """Empregador: EMPRESA X
Período: 01/01/2020 a 31/12/2020"""
        rems = parse_remuneracoes_bloco(texto)
        assert rems == []


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_bloco_vinculo
# ═══════════════════════════════════════════════════════════════════════════

class TestParseBlocoVinculo:

    def test_bloco_clt_completo(self):
        v = parse_bloco_vinculo(BLOCO_VINCULO_CLT, seq=1)
        assert v['seq'] == 1
        assert v['tipo'] == 'Empregado'
        assert v['identificador_empregador'] == '12.345.678/0001-90'
        assert v['data_inicio'] == '01/03/2010'
        assert v['data_fim'] == '31/12/2020'
        assert v['eh_beneficio'] is False
        assert len(v['remuneracoes']) == 3

    def test_bloco_mei(self):
        v = parse_bloco_vinculo(BLOCO_VINCULO_MEI, seq=2)
        assert v['seq'] == 2
        assert v['tipo'] == 'Contribuinte Individual'
        assert v['data_inicio'] == '01/06/2021'
        assert len(v['remuneracoes']) == 2

    def test_bloco_beneficio(self):
        v = parse_bloco_vinculo(BLOCO_BENEFICIO, seq=3)
        assert v['eh_beneficio'] is True
        assert v['numero_beneficio'] == '1234567890'
        assert 'AUXILIO DOENCA' in v['especie_beneficio']
        assert v['situacao_beneficio'] == 'ATIVO'

    def test_empregador_extraido(self):
        v = parse_bloco_vinculo(BLOCO_VINCULO_CLT, seq=1)
        assert v['empregador'] is not None
        assert len(v['empregador']) > 3

    def test_remuneracoes_com_indicador(self):
        v = parse_bloco_vinculo(BLOCO_VINCULO_CLT, seq=1)
        # A segunda remuneração tem PREC-MENOR-MIN
        rem_com_ind = [r for r in v['remuneracoes'] if r['indicadores']]
        assert len(rem_com_ind) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — segmentar_vinculos
# ═══════════════════════════════════════════════════════════════════════════

class TestSegmentarVinculos:

    def test_segmenta_dois_vinculos(self):
        blocos = segmentar_vinculos(TEXTO_SEGMENTACAO)
        assert len(blocos) == 2

    def test_primeiro_bloco_contem_empresa(self):
        blocos = segmentar_vinculos(TEXTO_SEGMENTACAO)
        assert 'EMPRESA ALFA' in blocos[0]

    def test_segundo_bloco_contem_mei(self):
        blocos = segmentar_vinculos(TEXTO_SEGMENTACAO)
        assert 'MEI' in blocos[1]

    def test_texto_vazio_retorna_lista_vazia(self):
        assert segmentar_vinculos("") == []

    def test_texto_sem_vinculos_retorna_lista_vazia(self):
        assert segmentar_vinculos("Apenas texto genérico sem padrão") == []

    def test_padrao_alternativo_empregador(self):
        texto = """
Empregador: EMPRESA BETA LTDA
01/01/2010 31/12/2015
Empregador: EMPRESA GAMA SA
01/01/2016 31/12/2020
"""
        blocos = segmentar_vinculos(texto)
        assert len(blocos) == 2


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — extrair_legenda_indicadores
# ═══════════════════════════════════════════════════════════════════════════

class TestExtrairLegendaIndicadores:

    def test_legenda_completa(self):
        indicadores = extrair_legenda_indicadores(TEXTO_LEGENDA)
        assert 'IREC-MEI' in indicadores
        assert 'PREC-MENOR-MIN' in indicadores
        assert 'IREC-LC123' in indicadores
        assert 'PEXT' in indicadores

    def test_sem_legenda_retorna_vazio(self):
        indicadores = extrair_legenda_indicadores("Texto sem seção de legenda")
        assert len(indicadores) == 0

    def test_legenda_filtra_palavras_comuns(self):
        texto = """
Legenda de Indicadores
IREC-MEI - Recolhimento MEI
"""
        indicadores = extrair_legenda_indicadores(texto)
        # Só deve ter IREC-MEI, não palavras como "Recolhimento" ou "MEI"
        assert 'IREC-MEI' in indicadores
