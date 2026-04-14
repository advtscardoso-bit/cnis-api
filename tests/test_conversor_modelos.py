"""
Testes do conversor_modelos.py — dict → Pydantic.

Cobre:
1. Conversão básica de tipos (datas, decimais, CPF)
2. Mapeamento de tipo de vínculo (parser string → enum)
3. Mapeamento de espécie de benefício
4. Classificação de indicadores (P/I/A/D)
5. Integração completa (converter() com dados reais)
6. Cenários de erro e fallback
7. Integração com DadosFormulario (sexo, PcD, etc.)
"""

from datetime import date
from decimal import Decimal

import pytest

from app.conversor_modelos import (
    converter,
    DadosConvertidos,
    _parse_data,
    _parse_decimal,
    _limpar_cpf,
    _mapear_tipo_vinculo,
    _mapear_especie_beneficio,
    _classificar_indicador,
    _inferir_severidade_pendencia,
    _obter_sm_competencia,
    _carregar_indicadores_json,
)
from app.models.pessoa import Sexo
from app.models.vinculo import TipoVinculo, SituacaoVinculo
from app.models.beneficio import EspecieBeneficio
from app.models.indicador import ClassificacaoIndicador, SeveridadeIndicador


# ══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def resultado_parser_minimo():
    """Resultado mínimo válido do parser — 1 vínculo CLT, 2 remunerações."""
    return {
        "sucesso": True,
        "erro": None,
        "dados": {
            "cabecalho": {
                "nit": "12345678901",
                "cpf": "529.982.247-25",
                "nome": "MARIA TESTE DA SILVA",
                "data_nascimento": "11/07/1966",
                "nome_mae": "ANA MARIA DA SILVA",
                "data_emissao": "14/04/2026",
            },
            "vinculos": [
                {
                    "seq": 1,
                    "tipo": "Empregado",
                    "empregador": "EMPRESA TESTE LTDA",
                    "identificador_empregador": "12.345.678/0001-90",
                    "data_inicio": "01/03/2010",
                    "data_fim": "15/06/2020",
                    "ultima_remuneracao": None,
                    "indicadores_vinculo": [],
                    "remuneracoes": [
                        {
                            "competencia": "03/2010",
                            "valor": 1200.00,
                            "indicadores": [],
                        },
                        {
                            "competencia": "04/2010",
                            "valor": 1200.00,
                            "indicadores": [],
                        },
                    ],
                    "eh_beneficio": False,
                    "numero_beneficio": None,
                    "especie_beneficio": None,
                    "situacao_beneficio": None,
                },
            ],
            "resumo": {
                "total_vinculos": 1,
                "total_vinculos_emprego": 1,
                "total_beneficios": 0,
                "total_remuneracoes": 2,
                "primeira_competencia": "03/2010",
                "ultima_competencia": "04/2010",
                "total_indicadores_unicos": 0,
                "indicadores_encontrados": [],
            },
        },
    }


@pytest.fixture
def resultado_parser_completo():
    """Resultado mais completo — CLT + MEI + Benefício + Indicadores."""
    return {
        "sucesso": True,
        "erro": None,
        "dados": {
            "cabecalho": {
                "nit": "12345678901",
                "cpf": "899.763.475-53",
                "nome": "RONALDO PEREIRA COSTA",
                "data_nascimento": "20/04/1976",
                "nome_mae": "MARIA COSTA",
                "data_emissao": "14/04/2026",
            },
            "vinculos": [
                {
                    "seq": 1,
                    "tipo": "Empregado",
                    "empregador": "TRANSPORTES RODOVIARIOS LTDA",
                    "identificador_empregador": "11.222.333/0001-44",
                    "data_inicio": "01/02/2000",
                    "data_fim": "30/11/2004",
                    "ultima_remuneracao": None,
                    "indicadores_vinculo": ["PEXT"],
                    "remuneracoes": [
                        {
                            "competencia": "02/2000",
                            "valor": 450.00,
                            "indicadores": [],
                        },
                        {
                            "competencia": "03/2000",
                            "valor": 450.00,
                            "indicadores": ["PREM-EXT"],
                        },
                    ],
                    "eh_beneficio": False,
                    "numero_beneficio": None,
                    "especie_beneficio": None,
                    "situacao_beneficio": None,
                },
                {
                    "seq": 2,
                    "tipo": "Microempreendedor Individual",
                    "empregador": "RONALDO PEREIRA COSTA",
                    "identificador_empregador": "33.444.555/0001-66",
                    "data_inicio": "01/01/2011",
                    "data_fim": None,
                    "ultima_remuneracao": None,
                    "indicadores_vinculo": ["IREC-MEI"],
                    "remuneracoes": [
                        {
                            "competencia": "01/2011",
                            "valor": 27.25,
                            "indicadores": ["PREC-MENOR-MIN"],
                        },
                        {
                            "competencia": "02/2011",
                            "valor": 27.25,
                            "indicadores": [],
                        },
                    ],
                    "eh_beneficio": False,
                    "numero_beneficio": None,
                    "especie_beneficio": None,
                    "situacao_beneficio": None,
                },
                {
                    "seq": 3,
                    "tipo": "Empregado",
                    "empregador": "PREV SOCIAL",
                    "identificador_empregador": None,
                    "data_inicio": "15/12/2004",
                    "data_fim": "14/06/2005",
                    "ultima_remuneracao": None,
                    "indicadores_vinculo": [],
                    "remuneracoes": [
                        {
                            "competencia": "12/2004",
                            "valor": 260.00,
                            "indicadores": [],
                        },
                    ],
                    "eh_beneficio": True,
                    "numero_beneficio": "1234567890",
                    "especie_beneficio": "31 - Auxílio-doença previdenciário",
                    "situacao_beneficio": "CESSADO",
                },
            ],
            "resumo": {
                "total_vinculos": 3,
                "total_vinculos_emprego": 2,
                "total_beneficios": 1,
                "total_remuneracoes": 5,
                "primeira_competencia": "02/2000",
                "ultima_competencia": "02/2011",
                "total_indicadores_unicos": 4,
                "indicadores_encontrados": ["IREC-MEI", "PEXT", "PREC-MENOR-MIN", "PREM-EXT"],
            },
        },
    }


@pytest.fixture
def dados_formulario_masculino():
    """Dados do formulário — cliente masculino (Ronaldo)."""
    return {
        "nome_completo": "Ronaldo Pereira Costa",
        "sexo": "M",
        "data_nascimento": date(1976, 4, 20),
        "cpf": "89976347553",
        "celular": "77981003955",
        "profissao": "No momento artesão (na CLT motorista)",
        "estado_civil": "CASADO",
        "tem_dependentes": True,
        "motivacao_principal": "PCD",
        "interesse_regularizacao_cnis": True,
        "trabalhando_atualmente": True,
        "e_pcd": True,
        "descricao_pcd": "Fratura na perna esquerda com pinos e placa. Mês de Dezembro de 2004",
        "sofreu_acidente": True,
        "sequela_acidente": True,
        "cirurgia_acidente": True,
        "ja_foi_mei": True,
        "ja_solicitou_beneficio": True,
        "beneficio_solicitado": "Auxílio doença",
        "processo_trabalhista": "Sim - Houve acordo",
    }


@pytest.fixture
def dados_formulario_feminino():
    """Dados do formulário — cliente feminina (Tatiana)."""
    return {
        "nome_completo": "Tatiana Sampaio",
        "sexo": "F",
        "data_nascimento": date(1981, 6, 13),
        "cpf": "05580767773",
        "celular": "27999185544",
        "profissao": "Advogada",
        "estado_civil": "CASADO",
        "tem_dependentes": True,
        "motivacao_principal": "Atingir a idade mínima para aposentadoria",
        "interesse_regularizacao_cnis": True,
        "trabalhando_atualmente": True,
        "ja_recebeu_salario_maternidade": True,
    }


@pytest.fixture
def dicionario_indicadores():
    return _carregar_indicadores_json()


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: Conversão de tipos básicos
# ══════════════════════════════════════════════════════════════════════════════


class TestParseData:
    def test_data_valida(self):
        assert _parse_data("11/07/1966") == date(1966, 7, 11)

    def test_data_valida_com_espacos(self):
        assert _parse_data("  11/07/1966  ") == date(1966, 7, 11)

    def test_data_none(self):
        assert _parse_data(None) is None

    def test_data_vazia(self):
        assert _parse_data("") is None

    def test_data_invalida(self):
        assert _parse_data("31/13/2020") is None

    def test_data_formato_errado(self):
        assert _parse_data("1966-07-11") is None


class TestParseDecimal:
    def test_float(self):
        assert _parse_decimal(1200.00) == Decimal("1200")

    def test_int(self):
        assert _parse_decimal(1200) == Decimal("1200")

    def test_string_br(self):
        assert _parse_decimal("1.200,50") == Decimal("1200.50")

    def test_string_simples(self):
        assert _parse_decimal("450.00") == Decimal("450.00")

    def test_none(self):
        assert _parse_decimal(None) == Decimal("0")

    def test_string_invalida(self):
        assert _parse_decimal("abc") == Decimal("0")

    def test_decimal_passthrough(self):
        d = Decimal("123.45")
        assert _parse_decimal(d) == d


class TestLimparCpf:
    def test_cpf_formatado(self):
        assert _limpar_cpf("529.982.247-25") == "52998224725"

    def test_cpf_limpo(self):
        assert _limpar_cpf("52998224725") == "52998224725"

    def test_cpf_none(self):
        assert _limpar_cpf(None) == ""


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: Mapeamento de tipos
# ══════════════════════════════════════════════════════════════════════════════


class TestMapearTipoVinculo:
    def test_empregado(self):
        assert _mapear_tipo_vinculo("Empregado") == TipoVinculo.CLT

    def test_mei(self):
        assert _mapear_tipo_vinculo("Microempreendedor Individual") == TipoVinculo.MEI

    def test_domestico(self):
        assert _mapear_tipo_vinculo("Empregado Doméstico") == TipoVinculo.EMPREGADO_DOMESTICO

    def test_ci(self):
        assert _mapear_tipo_vinculo("Contribuinte Individual") == TipoVinculo.CONTRIBUINTE_INDIVIDUAL

    def test_segurado_especial(self):
        assert _mapear_tipo_vinculo("Segurado Especial") == TipoVinculo.RURAL_SEGURADO_ESPECIAL

    def test_agente_publico(self):
        assert _mapear_tipo_vinculo("Agente Público") == TipoVinculo.SERVIDOR_PUBLICO

    def test_facultativo(self):
        assert _mapear_tipo_vinculo("Facultativo") == TipoVinculo.FACULTATIVO

    def test_nao_identificado(self):
        assert _mapear_tipo_vinculo("Não identificado") == TipoVinculo.DESCONHECIDO

    def test_tipo_desconhecido(self):
        assert _mapear_tipo_vinculo("Algo Estranho") == TipoVinculo.DESCONHECIDO


class TestMapearEspecieBeneficio:
    def test_auxilio_doenca(self):
        assert _mapear_especie_beneficio("31 - Auxílio-doença previdenciário") == EspecieBeneficio.B31

    def test_aposentadoria_idade(self):
        assert _mapear_especie_beneficio("41 - Aposentadoria por idade") == EspecieBeneficio.B41

    def test_aposentadoria_invalidez(self):
        assert _mapear_especie_beneficio("32 - Aposentadoria por invalidez") == EspecieBeneficio.B32

    def test_especie_desconhecida(self):
        assert _mapear_especie_beneficio("99 - Benefício desconhecido") == EspecieBeneficio.OUTRO

    def test_especie_none(self):
        assert _mapear_especie_beneficio(None) == EspecieBeneficio.OUTRO

    def test_especie_vazia(self):
        assert _mapear_especie_beneficio("") == EspecieBeneficio.OUTRO


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: Classificação de indicadores
# ══════════════════════════════════════════════════════════════════════════════


class TestClassificarIndicador:
    def test_pendencia_conhecida(self, dicionario_indicadores):
        ind = _classificar_indicador("PEXT", dicionario_indicadores)
        assert ind.classificacao == ClassificacaoIndicador.PENDENCIA
        assert ind.nome != ""
        assert ind.descricao != ""

    def test_pendencia_bloqueio(self, dicionario_indicadores):
        ind = _classificar_indicador("PREM-BLOQ-EC103", dicionario_indicadores)
        assert ind.classificacao == ClassificacaoIndicador.PENDENCIA
        assert ind.severidade == SeveridadeIndicador.CRITICA

    def test_indicador_desconhecido(self, dicionario_indicadores):
        """REGRA SYS-02: Indicador não catalogado → DESCONHECIDO, nunca inventar."""
        ind = _classificar_indicador("XINDICADOR-FAKE", dicionario_indicadores)
        assert ind.classificacao == ClassificacaoIndicador.DESCONHECIDO
        assert ind.severidade == SeveridadeIndicador.MEDIA

    def test_abaixo_minimo_critico(self, dicionario_indicadores):
        ind = _classificar_indicador("PREC-MENOR-MIN", dicionario_indicadores)
        assert ind.severidade == SeveridadeIndicador.CRITICA

    def test_extemporanea_alta(self, dicionario_indicadores):
        ind = _classificar_indicador("PREM-EXT", dicionario_indicadores)
        assert ind.severidade == SeveridadeIndicador.ALTA


class TestInferirSeveridade:
    def test_criticos(self):
        assert _inferir_severidade_pendencia("PREM-BLOQ-EC103") == SeveridadeIndicador.CRITICA
        assert _inferir_severidade_pendencia("PREC-MENOR-MIN") == SeveridadeIndicador.CRITICA

    def test_altos(self):
        assert _inferir_severidade_pendencia("PEXT") == SeveridadeIndicador.ALTA
        assert _inferir_severidade_pendencia("PREM-EXT") == SeveridadeIndicador.ALTA

    def test_padrao_media(self):
        assert _inferir_severidade_pendencia("ALGO-NOVO") == SeveridadeIndicador.MEDIA


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: Conversão completa — converter()
# ══════════════════════════════════════════════════════════════════════════════


class TestConverterMinimo:
    """Testa conversão com dados mínimos (sem formulário)."""

    def test_converte_pessoa(self, resultado_parser_minimo):
        resultado = converter(resultado_parser_minimo)
        assert resultado.pessoa.nome == "MARIA TESTE DA SILVA"
        assert resultado.pessoa.cpf == "52998224725"
        assert resultado.pessoa.data_nascimento == date(1966, 7, 11)
        # Sem formulário → fallback MASCULINO + aviso
        assert resultado.pessoa.sexo == Sexo.MASCULINO
        assert any("Sexo" in a for a in resultado.avisos)

    def test_converte_vinculos(self, resultado_parser_minimo):
        resultado = converter(resultado_parser_minimo)
        assert len(resultado.vinculos) == 1
        v = resultado.vinculos[0]
        assert v.tipo == TipoVinculo.CLT
        assert v.empregador == "EMPRESA TESTE LTDA"
        assert v.data_inicio == date(2010, 3, 1)
        assert v.data_fim == date(2020, 6, 15)
        assert v.situacao == SituacaoVinculo.ENCERRADO

    def test_converte_contribuicoes(self, resultado_parser_minimo):
        resultado = converter(resultado_parser_minimo)
        assert len(resultado.contribuicoes) == 2
        c = resultado.contribuicoes[0]
        assert c.competencia == "03/2010"
        assert c.valor_original == Decimal("1200")
        assert c.vinculo_sequencia == 1
        # SM de 03/2010 = R$ 510,00
        assert c.sm_competencia == Decimal("510")

    def test_sem_beneficios(self, resultado_parser_minimo):
        resultado = converter(resultado_parser_minimo)
        assert len(resultado.beneficios) == 0

    def test_sem_indicadores(self, resultado_parser_minimo):
        resultado = converter(resultado_parser_minimo)
        assert len(resultado.indicadores) == 0


class TestConverterCompleto:
    """Testa conversão com dados complexos (CLT + MEI + Benefício + Indicadores)."""

    def test_converte_com_formulario_masculino(
        self, resultado_parser_completo, dados_formulario_masculino
    ):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        assert resultado.pessoa.sexo == Sexo.MASCULINO
        assert resultado.pessoa.nome == "RONALDO PEREIRA COSTA"
        # CPF do CNIS prevalece
        assert resultado.pessoa.cpf == "89976347553"
        assert resultado.formulario is not None
        assert resultado.formulario.e_pcd is True

    def test_quantidade_vinculos(self, resultado_parser_completo, dados_formulario_masculino):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        # 2 vínculos de emprego (seq 1 CLT + seq 2 MEI), seq 3 é benefício
        assert len(resultado.vinculos) == 2

    def test_vinculo_clt(self, resultado_parser_completo, dados_formulario_masculino):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        v_clt = resultado.vinculos[0]
        assert v_clt.tipo == TipoVinculo.CLT
        assert v_clt.empregador == "TRANSPORTES RODOVIARIOS LTDA"
        assert v_clt.situacao == SituacaoVinculo.ENCERRADO
        assert "PEXT" in v_clt.indicadores

    def test_vinculo_mei(self, resultado_parser_completo, dados_formulario_masculino):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        v_mei = resultado.vinculos[1]
        assert v_mei.tipo == TipoVinculo.MEI
        assert v_mei.situacao == SituacaoVinculo.ATIVO  # sem data_fim
        assert "IREC-MEI" in v_mei.indicadores

    def test_beneficio(self, resultado_parser_completo, dados_formulario_masculino):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        assert len(resultado.beneficios) == 1
        b = resultado.beneficios[0]
        assert b.especie == EspecieBeneficio.B31
        assert b.nb == "1234567890"
        assert b.dib == date(2004, 12, 15)
        assert b.dcb == date(2005, 6, 14)

    def test_indicadores(self, resultado_parser_completo, dados_formulario_masculino):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        codigos = {i.codigo for i in resultado.indicadores}
        assert "PEXT" in codigos
        assert "PREM-EXT" in codigos
        assert "PREC-MENOR-MIN" in codigos
        assert "IREC-MEI" in codigos

    def test_contribuicao_extemporanea(
        self, resultado_parser_completo, dados_formulario_masculino
    ):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        # 03/2000 tem indicador PREM-EXT
        contrib_ext = [c for c in resultado.contribuicoes if c.competencia == "03/2000"]
        assert len(contrib_ext) == 1
        assert contrib_ext[0].extemporanea is True

    def test_contribuicao_abaixo_minimo(
        self, resultado_parser_completo, dados_formulario_masculino
    ):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        # 01/2011 tem indicador PREC-MENOR-MIN
        contrib_min = [c for c in resultado.contribuicoes if c.competencia == "01/2011"]
        assert len(contrib_min) == 1
        assert contrib_min[0].abaixo_minimo is True

    def test_total_contribuicoes(
        self, resultado_parser_completo, dados_formulario_masculino
    ):
        resultado = converter(resultado_parser_completo, dados_formulario_masculino)
        # 2 do CLT + 2 do MEI + 1 do benefício = 5
        assert len(resultado.contribuicoes) == 5


class TestConverterComFormularioFeminino:
    """Testa conversão com formulário feminino."""

    def test_sexo_feminino(self, resultado_parser_minimo, dados_formulario_feminino):
        resultado = converter(resultado_parser_minimo, dados_formulario_feminino)
        assert resultado.pessoa.sexo == Sexo.FEMININO
        # Sem aviso de sexo faltando
        assert not any("Sexo" in a for a in resultado.avisos)

    def test_formulario_preservado(self, resultado_parser_minimo, dados_formulario_feminino):
        resultado = converter(resultado_parser_minimo, dados_formulario_feminino)
        assert resultado.formulario is not None
        assert resultado.formulario.ja_recebeu_salario_maternidade is True
        assert resultado.formulario.profissao == "Advogada"


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: Cenários de erro
# ══════════════════════════════════════════════════════════════════════════════


class TestConverterErros:
    def test_parser_com_erro(self):
        with pytest.raises(ValueError, match="Parser retornou erro"):
            converter({"sucesso": False, "erro": "PDF corrompido"})

    def test_sem_cpf(self):
        resultado_sem_cpf = {
            "sucesso": True,
            "erro": None,
            "dados": {
                "cabecalho": {
                    "nit": None, "cpf": None, "nome": "TESTE",
                    "data_nascimento": "01/01/1980", "nome_mae": None,
                    "data_emissao": None,
                },
                "vinculos": [],
                "resumo": {},
            },
        }
        with pytest.raises(ValueError, match="CPF"):
            converter(resultado_sem_cpf)

    def test_sem_data_nascimento(self):
        resultado_sem_data = {
            "sucesso": True,
            "erro": None,
            "dados": {
                "cabecalho": {
                    "nit": None, "cpf": "529.982.247-25", "nome": "TESTE",
                    "data_nascimento": None, "nome_mae": None,
                    "data_emissao": None,
                },
                "vinculos": [],
                "resumo": {},
            },
        }
        with pytest.raises(ValueError, match="nascimento"):
            converter(resultado_sem_data)

    def test_vinculo_sem_data_inicio_gera_aviso(self, resultado_parser_minimo):
        """Vínculo sem data de início → ignorado com aviso."""
        resultado_parser_minimo["dados"]["vinculos"][0]["data_inicio"] = None
        resultado = converter(resultado_parser_minimo)
        assert len(resultado.vinculos) == 0
        assert any("sem data" in a.lower() for a in resultado.avisos)

    def test_formulario_invalido_gera_aviso(self, resultado_parser_minimo):
        """Formulário com dados inválidos → aviso, mas conversão continua."""
        dados_invalidos = {"nome_completo": "X"}  # Falta campos obrigatórios
        resultado = converter(resultado_parser_minimo, dados_invalidos)
        assert any("formulário" in a.lower() or "Erro" in a for a in resultado.avisos)
        assert resultado.formulario is None  # Não conseguiu criar


# ══════════════════════════════════════════════════════════════════════════════
# TESTES: SM por competência
# ══════════════════════════════════════════════════════════════════════════════


class TestObterSmCompetencia:
    @pytest.fixture
    def tabela_sm(self):
        return [
            {"vigencia": "2026-01-01", "valor": 1518.00},
            {"vigencia": "2025-01-01", "valor": 1518.00},
            {"vigencia": "2024-01-01", "valor": 1412.00},
            {"vigencia": "2010-01-01", "valor": 510.00},
            {"vigencia": "2000-04-01", "valor": 151.00},
            {"vigencia": "2000-01-01", "valor": 136.00},
        ]

    def test_sm_2026(self, tabela_sm):
        assert _obter_sm_competencia("01/2026", tabela_sm) == Decimal("1518")

    def test_sm_2010(self, tabela_sm):
        assert _obter_sm_competencia("03/2010", tabela_sm) == Decimal("510")

    def test_sm_2000_antes_reajuste(self, tabela_sm):
        assert _obter_sm_competencia("02/2000", tabela_sm) == Decimal("136")

    def test_sm_2000_apos_reajuste(self, tabela_sm):
        assert _obter_sm_competencia("05/2000", tabela_sm) == Decimal("151")

    def test_competencia_invalida(self, tabela_sm):
        assert _obter_sm_competencia("13/2020", tabela_sm) is None

    def test_competencia_vazia(self, tabela_sm):
        assert _obter_sm_competencia("", tabela_sm) is None
