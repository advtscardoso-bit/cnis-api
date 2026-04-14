"""
Testes do formulario_parser.py — extração de dados do Google Forms PDF.

Cobre:
1. Funções auxiliares de extração (data, CPF, seção)
2. Detecção de sexo, estado civil, sim/não
3. Parse completo com os 2 PDFs de teste (Teste1=Feminino, Teste2=Masculino)
"""

import os
from datetime import date

import pytest

from app.formulario_parser import (
    parse_formulario,
    _parse_data_nascimento,
    _extrair_secao,
    _normalizar_texto,
    _detectar_estado_civil,
    _detectar_sexo,
    _detectar_sim_nao,
    _detectar_faixa_renda,
    _detectar_expectativa_idade,
    _detectar_regime_tributario,
)


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES
# ══════════════════════════════════════════════════════════════════════════════


class TestParsDataNascimento:
    def test_formato_dd_mm_aaaa(self):
        assert _parse_data_nascimento("20/04/1976") == date(1976, 4, 20)

    def test_formato_sem_barras(self):
        assert _parse_data_nascimento("13061981") == date(1981, 6, 13)

    def test_texto_com_data(self):
        assert _parse_data_nascimento("algo 13/06/1981 mais") == date(1981, 6, 13)

    def test_texto_invalido(self):
        assert _parse_data_nascimento("sem data aqui") is None


class TestExtrairSecao:
    def test_secao_basica(self):
        texto = "Sexo:\nMasculino\nFeminino\nQual é o seu número"
        secao = _extrair_secao(texto, "Sexo", "Qual")
        assert secao is not None
        assert "Masculino" in secao

    def test_secao_nao_encontrada(self):
        assert _extrair_secao("texto qualquer", "ABC", "DEF") is None

    def test_secao_sem_fim(self):
        texto = "Sexo:\nMasculino\nFeminino"
        secao = _extrair_secao(texto, "Sexo", "NAOEXISTE")
        assert secao is not None
        assert "Masculino" in secao


class TestNormalizarTexto:
    def test_remove_espacos_multiplos(self):
        assert _normalizar_texto("a   b   c") == "a b c"

    def test_remove_nbsp(self):
        assert _normalizar_texto("a\u00a0b") == "a b"


class TestDetectarEstadoCivil:
    def test_casado(self):
        # No PDF, opções aparecem em linhas separadas — primeira opção = selecionada
        texto = "Estado Civil *\nCasado (a)\nSolteiro (a)\nUnião Estável"
        assert _detectar_estado_civil(texto) == "CASADO"

    def test_solteiro(self):
        texto = "Estado Civil *\nSolteiro (a)\nOutro"
        assert _detectar_estado_civil(texto) == "SOLTEIRO"

    def test_uniao_estavel(self):
        texto = "Estado Civil *\nUnião Estável\nCasado (a)"
        assert _detectar_estado_civil(texto) == "UNIAO_ESTAVEL"


class TestDetectarSexo:
    def test_retorna_none(self):
        """Detecção de sexo por texto é impossível — retorna None."""
        texto = "Sexo: *\nFeminino\nMasculino\nQual é o seu número"
        resultado = _detectar_sexo(texto)
        assert resultado is None

    def test_retorna_none_isolado(self):
        texto = "Sexo: *\nFeminino\nMasculino"
        resultado = _detectar_sexo(texto)
        assert resultado is None


class TestDetectarSimNao:
    def test_sim(self):
        texto = "Já solicitou algum benefício?\nSim\nNão"
        assert _detectar_sim_nao(texto, "solicitou") is True

    def test_nao(self):
        texto = "Recebe pensão?\nNão\nSim"
        assert _detectar_sim_nao(texto, "pensão") is False


class TestDetectarFaixaRenda:
    def test_acima_teto(self):
        assert _detectar_faixa_renda("Acima do Teto R$ 8.475,00") == "ACIMA_TETO"

    def test_faixa_media(self):
        assert _detectar_faixa_renda("R$ 3.242,00 a R$ 4.863,00") == "DE_2_A_3SM"


class TestDetectarExpectativaIdade:
    def test_assim_que_possivel(self):
        assert _detectar_expectativa_idade(
            "Assim que possível, independentemente da idade"
        ) == "ASSIM_QUE_POSSIVEL"

    def test_ate_55(self):
        assert _detectar_expectativa_idade("Até 55 anos") == "ATE_55"


class TestDetectarRegimeTributario:
    def test_mei(self):
        assert _detectar_regime_tributario("MEI\nSimples Nacional") == "SIMPLES_NACIONAL"

    def test_simples(self):
        assert _detectar_regime_tributario("Simples Nacional") == "SIMPLES_NACIONAL"


# ══════════════════════════════════════════════════════════════════════════════
# TESTES DE INTEGRAÇÃO COM PDFs REAIS
# ══════════════════════════════════════════════════════════════════════════════

# Caminhos dos PDFs de teste
PDF_TESTE1 = os.path.join(
    os.path.expanduser("~"), "Downloads",
    "Planejamento Previdenciário - Teste 1.pdf"
)
PDF_TESTE2 = os.path.join(
    os.path.expanduser("~"), "Downloads",
    "Planejamento Previdenciário - Teste2.pdf"
)


@pytest.mark.skipif(
    not os.path.exists(PDF_TESTE1),
    reason="PDF Teste 1 não encontrado em Downloads"
)
class TestParseFormularioTeste1:
    """Teste 1: Tatiana Sampaio — Feminino, Advogada, Casada."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.resultado = parse_formulario(PDF_TESTE1)

    def test_nome(self):
        assert "Tatiana" in self.resultado["nome_completo"] or \
               "TATIANA" in self.resultado["nome_completo"].upper()

    def test_sexo_feminino(self):
        # Feminino é detectável por curvas (teal no 1º radio button)
        assert self.resultado["sexo"] == "F"

    def test_cpf(self):
        cpf = self.resultado["cpf"].replace(".", "").replace("-", "")
        assert cpf == "05580767773"

    def test_data_nascimento(self):
        # Data vem como "13061981" (DDMMAAAA) no PDF
        assert self.resultado["data_nascimento"] == date(1981, 6, 13)

    def test_profissao(self):
        assert "advogada" in self.resultado["profissao"].lower()


@pytest.mark.skipif(
    not os.path.exists(PDF_TESTE2),
    reason="PDF Teste 2 não encontrado em Downloads"
)
class TestParseFormularioTeste2:
    """Teste 2: Ronaldo Pereira Costa — Masculino, Artesão/Motorista, PcD."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.resultado = parse_formulario(PDF_TESTE2)

    def test_nome(self):
        assert "Ronaldo" in self.resultado["nome_completo"] or \
               "RONALDO" in self.resultado["nome_completo"].upper()

    def test_sexo_masculino(self):
        # Masculino (2ª opção) → sem indicador teal no PDF → fallback para "M"
        assert self.resultado["sexo"] == "M"

    def test_cpf(self):
        cpf = self.resultado["cpf"].replace(".", "").replace("-", "")
        assert cpf == "89976347553"

    def test_data_nascimento(self):
        assert self.resultado["data_nascimento"] == date(1976, 4, 20)

    def test_pcd(self):
        assert self.resultado["e_pcd"] is True

    def test_acidente(self):
        assert self.resultado["sofreu_acidente"] is True

    def test_mei(self):
        assert self.resultado["ja_foi_mei"] is True
