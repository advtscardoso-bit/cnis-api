"""
Testes unitários do cnis_analyzer.py.

Testa cada função de análise isoladamente, usando dados estruturados
que simulam a saída do cnis_parser.
"""

import sys
import os
from datetime import date
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from cnis_analyzer import (
    classificar_indicadores,
    calcular_lacunas,
    analisar_remuneracoes,
    avaliar_qualidade_segurado,
    estimar_tempo_contribuicao,
    verificar_sobreposicoes,
    verificar_vinculos_sem_fim,
    gerar_conclusao,
    obter_salario_minimo,
    parse_data_str,
    carregar_indicadores,
    carregar_salarios_minimos,
    detectar_avisos_beneficios,
    _classificar_especie,
)


# ═══════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def dicionario_indicadores():
    """Carrega dicionário real de indicadores (JSON)."""
    return carregar_indicadores()


@pytest.fixture(scope="module")
def tabela_sm():
    """Carrega tabela real de salários mínimos (JSON)."""
    return carregar_salarios_minimos()


def _vinculo(seq, empregador="EMPRESA X", data_inicio="01/01/2010",
             data_fim="31/12/2020", eh_beneficio=False, tipo="Empregado",
             remuneracoes=None, indicadores_vinculo=None):
    """Helper para criar dict de vínculo no formato do parser."""
    return {
        'seq': seq,
        'tipo': tipo,
        'empregador': empregador,
        'identificador_empregador': '12.345.678/0001-90',
        'data_inicio': data_inicio,
        'data_fim': data_fim,
        'ultima_remuneracao': None,
        'indicadores_vinculo': indicadores_vinculo or [],
        'remuneracoes': remuneracoes or [],
        'eh_beneficio': eh_beneficio,
        'numero_beneficio': None,
        'especie_beneficio': None,
        'situacao_beneficio': None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — parse_data_str (helper interno)
# ═══════════════════════════════════════════════════════════════════════════

class TestParseDataStr:

    def test_data_valida(self):
        assert parse_data_str("15/07/1970") == date(1970, 7, 15)

    def test_none_retorna_none(self):
        assert parse_data_str(None) is None

    def test_vazia_retorna_none(self):
        assert parse_data_str("") is None

    def test_invalida_retorna_none(self):
        assert parse_data_str("invalido") is None


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — obter_salario_minimo
# ═══════════════════════════════════════════════════════════════════════════

class TestObterSalarioMinimo:

    def test_competencia_2025(self, tabela_sm):
        sm = obter_salario_minimo("01/2025", tabela_sm)
        assert sm is not None
        assert sm >= 1400  # SM 2025 é 1518 ou similar

    def test_competencia_2020(self, tabela_sm):
        sm = obter_salario_minimo("06/2020", tabela_sm)
        assert sm is not None
        assert sm >= 1000

    def test_competencia_none(self, tabela_sm):
        assert obter_salario_minimo(None, tabela_sm) is None

    def test_competencia_invalida(self, tabela_sm):
        assert obter_salario_minimo("abc", tabela_sm) is None

    def test_competencia_muito_antiga(self, tabela_sm):
        # Pode retornar None se não tiver na tabela
        resultado = obter_salario_minimo("01/1950", tabela_sm)
        # Aceita None ou um valor (depende da tabela)
        assert resultado is None or resultado > 0


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — classificar_indicadores
# ═══════════════════════════════════════════════════════════════════════════

class TestClassificarIndicadores:

    def test_pendencia(self, dicionario_indicadores):
        resultado = classificar_indicadores(["PREC-MENOR-MIN"], dicionario_indicadores)
        assert len(resultado) == 1
        assert resultado[0]['tipo'] == 'PENDENCIA'
        assert resultado[0]['codigo'] == 'PREC-MENOR-MIN'
        assert 'nome' in resultado[0]
        assert 'descricao' in resultado[0]

    def test_alerta(self, dicionario_indicadores):
        resultado = classificar_indicadores(["IREC-MEI"], dicionario_indicadores)
        assert len(resultado) == 1
        assert resultado[0]['tipo'] == 'ALERTA'

    def test_acerto(self, dicionario_indicadores):
        resultado = classificar_indicadores(["ACNISVR"], dicionario_indicadores)
        assert len(resultado) == 1
        assert resultado[0]['tipo'] == 'ACERTO'

    def test_desconhecido(self, dicionario_indicadores):
        resultado = classificar_indicadores(["XYZW-999"], dicionario_indicadores)
        assert len(resultado) == 1
        assert resultado[0]['tipo'] == 'DESCONHECIDO'
        assert 'Portaria' in resultado[0]['descricao']

    def test_multiplos_tipos(self, dicionario_indicadores):
        resultado = classificar_indicadores(
            ["PREC-MENOR-MIN", "IREC-MEI", "XYZW-999"],
            dicionario_indicadores
        )
        tipos = {r['tipo'] for r in resultado}
        assert 'PENDENCIA' in tipos
        assert 'ALERTA' in tipos
        assert 'DESCONHECIDO' in tipos

    def test_lista_vazia(self, dicionario_indicadores):
        assert classificar_indicadores([], dicionario_indicadores) == []


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — calcular_lacunas
# ═══════════════════════════════════════════════════════════════════════════

class TestCalcularLacunas:

    def test_sem_lacunas(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="15/01/2016", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 0

    def test_lacuna_baixa(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/04/2016", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 1
        assert lacunas[0]['gravidade'] == 'BAIXA'

    def test_lacuna_media(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/07/2016", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 1
        assert lacunas[0]['gravidade'] == 'MEDIA'

    def test_lacuna_alta(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/07/2017", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 1
        assert lacunas[0]['gravidade'] == 'ALTA'

    def test_lacuna_critica(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/07/2018", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 1
        assert lacunas[0]['gravidade'] == 'CRITICA'

    def test_ignora_beneficios(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/01/2018", data_fim="31/12/2020", eh_beneficio=True),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 0  # Benefício é ignorado

    def test_vinculo_sem_data_fim_ignorado(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim=None),
            _vinculo(2, data_inicio="01/01/2015", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 0  # Sem data_fim, não computa lacuna

    def test_campos_lacuna(self):
        vinculos = [
            _vinculo(1, empregador="EMP A", data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, empregador="EMP B", data_inicio="01/01/2018", data_fim="31/12/2020"),
        ]
        lacunas = calcular_lacunas(vinculos)
        assert len(lacunas) == 1
        lac = lacunas[0]
        assert lac['empregador_anterior'] == 'EMP A'
        assert lac['empregador_posterior'] == 'EMP B'
        assert lac['dias'] > 0
        assert lac['meses'] > 0
        assert 'anos_meses' in lac


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — analisar_remuneracoes
# ═══════════════════════════════════════════════════════════════════════════

class TestAnalisarRemuneracoes:

    def test_remuneracao_normal(self, tabela_sm):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2025", data_fim="31/12/2025",
                     remuneracoes=[
                         {'competencia': '01/2025', 'valor': 2000.00, 'indicadores': []},
                         {'competencia': '02/2025', 'valor': 2000.00, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_competencias_analisadas'] == 2
        assert resultado['total_abaixo_minimo'] == 0

    def test_remuneracao_abaixo_minimo(self, tabela_sm):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2025", data_fim="31/12/2025",
                     remuneracoes=[
                         {'competencia': '06/2025', 'valor': 500.00, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_abaixo_minimo'] >= 1

    def test_moeda_antiga(self, tabela_sm):
        vinculos = [
            _vinculo(1, data_inicio="01/01/1990", data_fim="31/12/1993",
                     remuneracoes=[
                         {'competencia': '06/1993', 'valor': 100.00, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_moeda_antiga'] == 1
        assert resultado['moeda_antiga'][0]['competencia'] == '06/1993'

    def test_proporcional_admissao(self, tabela_sm):
        # Admissão em 15/06/2025 — competência 06/2025 é proporcional
        vinculos = [
            _vinculo(1, data_inicio="15/06/2025", data_fim="31/12/2025",
                     remuneracoes=[
                         {'competencia': '06/2025', 'valor': 800.00, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_proporcionais'] >= 1

    def test_ignora_beneficios(self, tabela_sm):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2025", data_fim="31/12/2025",
                     eh_beneficio=True,
                     remuneracoes=[
                         {'competencia': '01/2025', 'valor': 500.00, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_competencias_analisadas'] == 0

    def test_competencia_invalida_ignorada(self, tabela_sm):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2025", data_fim="31/12/2025",
                     remuneracoes=[
                         {'competencia': None, 'valor': 1500.00, 'indicadores': []},
                         {'competencia': '01/2025', 'valor': None, 'indicadores': []},
                     ]),
        ]
        resultado = analisar_remuneracoes(vinculos, tabela_sm)
        assert resultado['total_competencias_analisadas'] == 0


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — avaliar_qualidade_segurado
# ═══════════════════════════════════════════════════════════════════════════

class TestAvaliarQualidadeSegurado:

    def test_qualidade_mantida(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2025",
                     remuneracoes=[
                         {'competencia': '12/2025', 'valor': 1518.00, 'indicadores': []},
                     ]),
        ]
        resultado = avaliar_qualidade_segurado(vinculos, "10/04/2026")
        assert resultado['status'] == 'MANTIDA'
        assert resultado['ultima_contribuicao'] == '12/2025'

    def test_qualidade_perdida(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2020",
                     remuneracoes=[
                         {'competencia': '12/2020', 'valor': 1045.00, 'indicadores': []},
                     ]),
        ]
        resultado = avaliar_qualidade_segurado(vinculos, "10/04/2026")
        assert resultado['status'] == 'PERDIDA'

    def test_indeterminado_sem_contribuicoes(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2025",
                     remuneracoes=[]),
        ]
        resultado = avaliar_qualidade_segurado(vinculos, "10/04/2026")
        assert resultado['status'] == 'INDETERMINADO'

    def test_periodo_graca_120_contribuicoes(self):
        # 120+ contribuições → 24 meses de graça
        rems = [
            {'competencia': f'{m:02d}/{a}', 'valor': 1000.00, 'indicadores': []}
            for a in range(2015, 2026)
            for m in range(1, 13)
        ]  # 132 contribuições (11 anos * 12 meses)
        # Última contribuição: 12/2025
        vinculos = [
            _vinculo(1, data_inicio="01/01/2015", data_fim="31/12/2025",
                     remuneracoes=rems),
        ]
        resultado = avaliar_qualidade_segurado(vinculos, "10/04/2026")
        assert resultado['periodo_graca_meses'] == 24
        assert resultado['status'] == 'MANTIDA'

    def test_ignora_beneficios(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2025", data_fim="31/12/2025",
                     eh_beneficio=True,
                     remuneracoes=[
                         {'competencia': '12/2025', 'valor': 1518.00, 'indicadores': []},
                     ]),
        ]
        resultado = avaliar_qualidade_segurado(vinculos, "10/04/2026")
        assert resultado['status'] == 'INDETERMINADO'


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — estimar_tempo_contribuicao
# ═══════════════════════════════════════════════════════════════════════════

class TestEstimarTempoContribuicao:

    def test_vinculo_fechado(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2020"),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['total_dias'] > 3650  # ~11 anos
        assert resultado['anos'] >= 10
        assert 'descricao' in resultado

    def test_vinculo_ativo(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim=None),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['total_dias'] > 0
        assert any('Em aberto' in p['fim'] for p in resultado['periodos'])

    def test_ignora_beneficios(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2020",
                     eh_beneficio=True),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['total_dias'] == 0

    def test_multiplos_vinculos(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/01/2016", data_fim="31/12/2020"),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['anos'] >= 10
        assert len(resultado['periodos']) == 2

    def test_sem_data_inicio(self):
        vinculos = [
            _vinculo(1, data_inicio=None, data_fim="31/12/2020"),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['total_dias'] == 0


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — tempo LÍQUIDO (descontos por indicadores)
# ═══════════════════════════════════════════════════════════════════════════

class TestTempoLiquido:

    def test_sem_indicadores_liquido_igual_bruto(self):
        vinculos = [_vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2020")]
        resultado = estimar_tempo_contribuicao(vinculos)
        liq = resultado['liquido']
        assert liq['meses_descontados'] == 0
        assert liq['total_dias'] == resultado['total_dias']
        assert liq['diferenca_descricao'] == 'Sem descontos aplicados'

    def test_g1_desconta_competencias_bloqueadas(self):
        # 12 meses no total, 3 competências com PSC-MEN-SM-EC103 (G1)
        rems = [
            {'competencia': f'{m:02d}/2020', 'valor': 500.0,
             'indicadores': ['PSC-MEN-SM-EC103'] if m in (3, 4, 5) else []}
            for m in range(1, 13)
        ]
        vinculos = [_vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2020",
                             remuneracoes=rems)]
        resultado = estimar_tempo_contribuicao(vinculos)
        liq = resultado['liquido']
        assert liq['descontos_por_grupo']['G1']['meses'] == 3
        assert 'PSC-MEN-SM-EC103' in liq['descontos_por_grupo']['G1']['indicadores']
        assert liq['meses_descontados'] == 3

    def test_g2_mei_nao_conta_para_tempo(self):
        rems = [
            {'competencia': f'{m:02d}/2020', 'valor': 55.0,
             'indicadores': ['IREC-MEI']}
            for m in range(1, 13)
        ]
        vinculos = [_vinculo(1, tipo='Contribuinte Individual',
                             data_inicio="01/01/2020", data_fim="31/12/2020",
                             remuneracoes=rems)]
        resultado = estimar_tempo_contribuicao(vinculos)
        liq = resultado['liquido']
        assert liq['descontos_por_grupo']['G2']['meses'] == 12
        assert liq['meses_descontados'] == 12
        assert liq['total_dias'] < resultado['total_dias']

    def test_g3_vinculo_inteiro_bloqueado_por_ndet(self):
        vinculos = [_vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2020",
                             indicadores_vinculo=['NDET'])]
        resultado = estimar_tempo_contribuicao(vinculos)
        liq = resultado['liquido']
        assert liq['descontos_por_grupo']['G3']['meses'] == 12
        assert liq['meses_descontados'] == 12
        assert 'NDET' in liq['descontos_por_grupo']['G3']['indicadores']

    def test_cobertura_valida_em_outro_vinculo_nao_desconta(self):
        # Vínculo 1 bloqueado por NDET; vínculo 2 válido no mesmo período.
        # O mês NÃO deve ser descontado porque há cobertura válida.
        vinculos = [
            _vinculo(1, empregador="EMP A", data_inicio="01/01/2020",
                     data_fim="31/12/2020", indicadores_vinculo=['NDET']),
            _vinculo(2, empregador="EMP B", data_inicio="01/01/2020",
                     data_fim="31/12/2020"),
        ]
        resultado = estimar_tempo_contribuicao(vinculos)
        liq = resultado['liquido']
        assert liq['meses_descontados'] == 0

    def test_beneficio_nao_conta_para_liquido(self):
        vinculos = [_vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2020",
                             eh_beneficio=True)]
        resultado = estimar_tempo_contribuicao(vinculos)
        assert resultado['liquido']['meses_descontados'] == 0
        assert resultado['liquido']['total_dias'] == 0


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — _classificar_especie + detectar_avisos_beneficios
# ═══════════════════════════════════════════════════════════════════════════

class TestClassificarEspecie:
    def test_aposentadoria_idade_41(self):
        cat, nome = _classificar_especie('41 - APOSENTADORIA POR IDADE')
        assert cat == 'APOSENTADORIA'
        assert 'Idade' in nome

    def test_aposentadoria_tempo_42(self):
        cat, nome = _classificar_especie('42 - APOSENTADORIA POR TEMPO DE CONTRIBUICAO')
        assert cat == 'APOSENTADORIA'
        assert 'Tempo' in nome

    def test_aposentadoria_invalidez_32(self):
        cat, nome = _classificar_especie('32 - APOSENTADORIA POR INVALIDEZ')
        assert cat == 'APOSENTADORIA'

    def test_pensao_morte_21(self):
        cat, nome = _classificar_especie('21 - PENSAO POR MORTE')
        assert cat == 'PENSAO_MORTE'

    def test_auxilio_doenca_31(self):
        cat, nome = _classificar_especie('31 - AUXILIO DOENCA')
        assert cat == 'AUXILIO_INCAPACIDADE'

    def test_bpc_87(self):
        cat, nome = _classificar_especie('87 - BPC LOAS')
        assert cat == 'BPC_LOAS'

    def test_desconhecido(self):
        cat, nome = _classificar_especie('99 - INEXISTENTE')
        assert cat == 'OUTRO'


class TestDetectarAvisosBeneficios:
    def _beneficio(self, especie, situacao='ATIVO', nb='1234567890', dib='01/01/2020'):
        return {
            'seq': 1, 'tipo': 'Benefício', 'empregador': f'INSS - {especie}',
            'identificador_empregador': None, 'data_inicio': dib, 'data_fim': None,
            'ultima_remuneracao': None, 'indicadores_vinculo': [],
            'remuneracoes': [], 'eh_beneficio': True, 'numero_beneficio': nb,
            'especie_beneficio': especie, 'situacao_beneficio': situacao,
        }

    def test_aposentadoria_idade_ativa_gera_dois_avisos(self):
        # Bug do CNIS da Maria: espécie 41 não estava gerando aviso.
        # Aposentadoria ATIVA agora gera 2 avisos: o de status + o de
        # limite da análise (docs do pedido não vistos pelo relatório).
        avisos = detectar_avisos_beneficios([self._beneficio('41 - APOSENTADORIA POR IDADE')])
        tipos = [a['tipo'] for a in avisos]
        assert 'APOSENTADORIA_ATIVA' in tipos
        assert 'LIMITE_ANALISE_APOSENTADO' in tipos
        limite = next(a for a in avisos if a['tipo'] == 'LIMITE_ANALISE_APOSENTADO')
        assert 'documentos' in limite['mensagem'].lower()
        assert 'PPP' in limite['mensagem'] or 'LTCAT' in limite['mensagem']

    def test_aposentadoria_tempo_indeferida(self):
        avisos = detectar_avisos_beneficios([
            self._beneficio('42 - APOSENTADORIA POR TEMPO DE CONTRIBUICAO', situacao='INDEFERIDO')
        ])
        assert len(avisos) == 1
        assert avisos[0]['tipo'] == 'APOSENTADORIA_INDEFERIDA'

    def test_pensao_morte_sempre_gera_aviso(self):
        avisos = detectar_avisos_beneficios([self._beneficio('21 - PENSAO POR MORTE')])
        assert len(avisos) == 1
        assert avisos[0]['tipo'] == 'PENSAO_POR_MORTE'

    def test_ignora_vinculo_nao_beneficio(self):
        v = self._beneficio('41')
        v['eh_beneficio'] = False
        assert detectar_avisos_beneficios([v]) == []

    def test_bpc_gera_info(self):
        avisos = detectar_avisos_beneficios([self._beneficio('87 - BPC LOAS')])
        assert len(avisos) == 1
        assert avisos[0]['tipo'] == 'BPC_LOAS_PRESENTE'


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — verificar_sobreposicoes
# ═══════════════════════════════════════════════════════════════════════════

class TestVerificarSobreposicoes:

    def test_sem_sobreposicao(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/01/2016", data_fim="31/12/2020"),
        ]
        assert verificar_sobreposicoes(vinculos) == []

    def test_com_sobreposicao(self):
        vinculos = [
            _vinculo(1, empregador="EMP A", data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, empregador="EMP B", data_inicio="01/06/2014", data_fim="31/12/2020"),
        ]
        sobreposicoes = verificar_sobreposicoes(vinculos)
        assert len(sobreposicoes) == 1
        assert sobreposicoes[0]['empregador_a'] == 'EMP A'
        assert sobreposicoes[0]['empregador_b'] == 'EMP B'

    def test_ignora_beneficios(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2020"),
            _vinculo(2, data_inicio="01/06/2015", data_fim="31/12/2018", eh_beneficio=True),
        ]
        assert verificar_sobreposicoes(vinculos) == []

    def test_vinculo_ativo_sobreposto(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim=None),
            _vinculo(2, data_inicio="01/06/2022", data_fim=None),
        ]
        sobreposicoes = verificar_sobreposicoes(vinculos)
        assert len(sobreposicoes) == 1


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — verificar_vinculos_sem_fim
# ═══════════════════════════════════════════════════════════════════════════

class TestVerificarVinculosSemFim:

    def test_sem_anomalias(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim="31/12/2015"),
            _vinculo(2, data_inicio="01/01/2016", data_fim=None),  # Último pode não ter fim
        ]
        assert verificar_vinculos_sem_fim(vinculos) == []

    def test_vinculo_antigo_sem_fim(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2010", data_fim=None),  # Não é último!
            _vinculo(2, data_inicio="01/01/2016", data_fim=None),
        ]
        anomalias = verificar_vinculos_sem_fim(vinculos)
        assert len(anomalias) == 1
        assert anomalias[0]['vinculo_seq'] == 1

    def test_vinculo_unico_sem_fim_ok(self):
        vinculos = [
            _vinculo(1, data_inicio="01/01/2020", data_fim=None),
        ]
        assert verificar_vinculos_sem_fim(vinculos) == []


# ═══════════════════════════════════════════════════════════════════════════
# TESTES — gerar_conclusao
# ═══════════════════════════════════════════════════════════════════════════

class TestGerarConclusao:

    def _cabecalho(self, nome="MARIA DA SILVA"):
        return {'nome': nome, 'cpf': '529.982.247-25'}

    def _qualidade_mantida(self):
        return {'status': 'MANTIDA', 'ultima_contribuicao': '12/2025',
                'data_perda_estimada': '12/2026'}

    def _qualidade_perdida(self):
        return {'status': 'PERDIDA', 'ultima_contribuicao': '12/2020',
                'data_perda_estimada': '12/2021'}

    def _indicadores_limpos(self):
        return {'pendencias': [], 'alertas': [], 'acertos': [], 'desconhecidos': []}

    def _lacunas_zero(self):
        return {'total': 0, 'lista': [], 'gravidade_maxima': 'NENHUMA', 'maior_lacuna_meses': 0}

    def _remuneracoes_limpas(self):
        return {'abaixo_minimo': [], 'proporcionais': [], 'moeda_antiga': [],
                'total_abaixo_minimo': 0, 'total_proporcionais': 0, 'total_moeda_antiga': 0}

    def _verificacoes_limpas(self):
        return {'vinculos_sem_fim': []}

    def _tempo_info(self):
        return {'descricao': '10 ano(s), 0 mês(es) e 0 dia(s)'}

    def test_sem_problemas(self):
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            self._lacunas_zero(), self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] == 0
        assert 'não foram identificados' in resultado['paragrafo_abertura'].lower()
        assert len(resultado['paragrafos_fixos']) == 3

    def test_perda_qualidade(self):
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_perdida(), self._indicadores_limpos(),
            self._lacunas_zero(), self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] == 1
        assert 'perdeu a qualidade' in resultado['problemas'][0]['problema'].lower()

    def test_pendencias(self):
        indicadores = self._indicadores_limpos()
        indicadores['pendencias'] = [{
            'codigo': 'PREC-MENOR-MIN',
            'nome': 'Recolhimento abaixo do mínimo',
            'descricao': 'Valor abaixo do SM',
        }]
        vinculos = [_vinculo(1, indicadores_vinculo=['PREC-MENOR-MIN'])]
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), indicadores,
            self._lacunas_zero(), self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), vinculos,
        )
        assert resultado['total_problemas'] >= 1
        assert any('pendência' in p['problema'].lower() for p in resultado['problemas'])

    def test_abaixo_minimo(self):
        remuneracoes = self._remuneracoes_limpas()
        remuneracoes['abaixo_minimo'] = [{
            'competencia': '06/2025', 'valor': 500.00, 'salario_minimo': 1518.00,
            'empregador': 'EMPRESA X', 'vinculo_seq': 1, 'diferenca': 1018.00,
            'percentual': 32.9,
        }]
        remuneracoes['total_abaixo_minimo'] = 1
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            self._lacunas_zero(), remuneracoes, self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] >= 1
        assert any('abaixo do salário mínimo' in p['problema'].lower()
                    for p in resultado['problemas'])

    def test_lacunas(self):
        lacunas = {
            'total': 1,
            'lista': [{
                'data_fim': '31/12/2015', 'data_inicio': '01/01/2018',
                'empregador_anterior': 'EMP A', 'empregador_posterior': 'EMP B',
                'anos_meses': '2 ano(s) e 0 mês(es)', 'gravidade': 'CRITICA',
            }],
            'gravidade_maxima': 'CRITICA',
            'maior_lacuna_meses': 24,
        }
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            lacunas, self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] >= 1
        assert any('lacuna' in p['problema'].lower() for p in resultado['problemas'])

    def test_vinculos_sem_fim(self):
        verificacoes = {
            'vinculos_sem_fim': [{
                'vinculo_seq': 1, 'empregador': 'EMPRESA X', 'data_inicio': '01/01/2010',
            }],
        }
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            self._lacunas_zero(), self._remuneracoes_limpas(), verificacoes,
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] >= 1

    def test_moeda_antiga(self):
        remuneracoes = self._remuneracoes_limpas()
        remuneracoes['moeda_antiga'] = [{
            'competencia': '06/1993', 'valor': 100.00, 'vinculo_seq': 1,
            'empregador': 'EMPRESA X', 'nota': 'Moeda antiga',
        }]
        remuneracoes['total_moeda_antiga'] = 1
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            self._lacunas_zero(), remuneracoes, self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert resultado['total_problemas'] >= 1
        assert any('moeda antiga' in p['problema'].lower() for p in resultado['problemas'])

    def test_mei_simplificado(self):
        indicadores = self._indicadores_limpos()
        indicadores['alertas'] = [{
            'codigo': 'IREC-MEI',
            'nome': 'MEI',
            'descricao': 'Contribuição MEI',
        }]
        vinculos = [_vinculo(1, data_inicio="01/01/2020", data_fim="31/12/2025",
                             remuneracoes=[
                                 {'competencia': '01/2025', 'valor': 1518.00,
                                  'indicadores': ['IREC-MEI']},
                             ],
                             indicadores_vinculo=['IREC-MEI'])]
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), indicadores,
            self._lacunas_zero(), self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), vinculos,
        )
        assert resultado['total_problemas'] >= 1

    def test_paragrafo_abertura_com_problemas(self):
        resultado = gerar_conclusao(
            self._cabecalho(nome="JOAO FERREIRA"), self._qualidade_perdida(),
            self._indicadores_limpos(), self._lacunas_zero(),
            self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert 'JOAO FERREIRA' in resultado['paragrafo_abertura']
        assert 'problema(s)' in resultado['paragrafo_abertura']

    def test_paragrafos_fixos_sempre_presentes(self):
        resultado = gerar_conclusao(
            self._cabecalho(), self._qualidade_mantida(), self._indicadores_limpos(),
            self._lacunas_zero(), self._remuneracoes_limpas(), self._verificacoes_limpas(),
            self._tempo_info(), [],
        )
        assert len(resultado['paragrafos_fixos']) == 3
        assert 'legislação' in resultado['paragrafos_fixos'][0].lower()
