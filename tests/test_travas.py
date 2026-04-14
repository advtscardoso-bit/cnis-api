"""
Testes das travas anti-erro (24 regras de negócio críticas).
Cada trava deve ter pelo menos um teste positivo e um negativo.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.vinculo import Vinculo, TipoVinculo
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.pessoa import Sexo
from app.validacao.travas import (
    TravaVioladaError,
    AlertaTrava,
    trava_mei_01_contribuicao_sobre_sm,
    trava_mei_02_complementacao_sobre_sm,
    trava_mei_03_regras_acessiveis,
    trava_mei_04_das_em_atraso,
    trava_clt_01_nao_pode_ser_facultativo,
    trava_conc_01_mei_facultativo_proibido,
    trava_cal_01_teto_antes_de_atualizar,
    trava_cal_02_divisor_minimo,
    trava_cal_03_descarte_nao_reduz_tc,
    trava_esp_01_conversao_vedada_pos_reforma,
    trava_sys_02_indicador_desconhecido,
)


class TestTravaMei01:
    """MEI contribui SOMENTE sobre 1 SM."""

    def test_mei_no_sm_ok(self):
        contribuicoes = [
            Contribuicao(competencia="01/2025", valor_original=Decimal("1518.00"), tipo=TipoContribuicao.DAS_MEI),
        ]
        sm = {"01/2025": Decimal("1518.00")}
        alertas = trava_mei_01_contribuicao_sobre_sm(contribuicoes, sm)
        assert len(alertas) == 0

    def test_mei_acima_sm_bloqueia(self):
        contribuicoes = [
            Contribuicao(competencia="01/2025", valor_original=Decimal("3000.00"), tipo=TipoContribuicao.DAS_MEI),
        ]
        sm = {"01/2025": Decimal("1518.00")}
        with pytest.raises(TravaVioladaError, match="MEI-01"):
            trava_mei_01_contribuicao_sobre_sm(contribuicoes, sm)


class TestTravaMei02:
    """Complementação MEI é sobre SM."""

    def test_complementacao_correta_ok(self):
        # 15% de R$ 1518 = R$ 227,70
        trava_mei_02_complementacao_sobre_sm(Decimal("227.70"), Decimal("1518.00"))

    def test_complementacao_acima_sm_bloqueia(self):
        with pytest.raises(TravaVioladaError, match="MEI-02"):
            trava_mei_02_complementacao_sobre_sm(Decimal("500.00"), Decimal("1518.00"))


class TestTravaMei03:
    """MEI 5% só acessa aposentadoria por idade."""

    def test_mei_aposentadoria_idade_ok(self):
        resultado = trava_mei_03_regras_acessiveis(
            TipoVinculo.MEI, "IDADE", meses_complementados=0, total_meses_mei=240
        )
        assert resultado is None  # Não bloqueia

    def test_mei_pontos_sem_complementacao_bloqueia(self):
        with pytest.raises(TravaVioladaError, match="MEI-03"):
            trava_mei_03_regras_acessiveis(
                TipoVinculo.MEI, "PONTOS", meses_complementados=0, total_meses_mei=240
            )

    def test_mei_pontos_com_complementacao_total_ok(self):
        resultado = trava_mei_03_regras_acessiveis(
            TipoVinculo.MEI, "PONTOS", meses_complementados=240, total_meses_mei=240
        )
        assert resultado is None

    def test_clt_pontos_sempre_ok(self):
        resultado = trava_mei_03_regras_acessiveis(
            TipoVinculo.CLT, "PONTOS", meses_complementados=0, total_meses_mei=0
        )
        assert resultado is None


class TestTravaMei04:
    """DAS em atraso: conta tempo mas não carência."""

    def test_das_em_atraso_gera_alerta(self):
        c = Contribuicao(
            competencia="09/2023",
            valor_original=Decimal("1320.00"),
            tipo=TipoContribuicao.DAS_MEI,
            extemporanea=True,
        )
        alerta = trava_mei_04_das_em_atraso(c)
        assert alerta is not None
        assert alerta.codigo == "MEI-04"

    def test_das_em_dia_sem_alerta(self):
        c = Contribuicao(
            competencia="09/2023",
            valor_original=Decimal("1320.00"),
            tipo=TipoContribuicao.DAS_MEI,
            extemporanea=False,
        )
        alerta = trava_mei_04_das_em_atraso(c)
        assert alerta is None


class TestTravaClt01:
    """CLT não pode ser facultativo."""

    def test_clt_com_facultativo_bloqueia(self):
        vinculos = [
            Vinculo(tipo=TipoVinculo.CLT, data_inicio=date(2020, 1, 1)),
            Vinculo(tipo=TipoVinculo.FACULTATIVO, data_inicio=date(2020, 1, 1)),
        ]
        with pytest.raises(TravaVioladaError, match="CLT-01"):
            trava_clt_01_nao_pode_ser_facultativo(vinculos, "01/2020")

    def test_clt_com_mei_ok(self):
        vinculos = [
            Vinculo(tipo=TipoVinculo.CLT, data_inicio=date(2020, 1, 1)),
            Vinculo(tipo=TipoVinculo.MEI, data_inicio=date(2020, 1, 1)),
        ]
        trava_clt_01_nao_pode_ser_facultativo(vinculos, "01/2020")  # Não deve levantar exceção


class TestTravaConc01:
    """MEI + Facultativo proibido."""

    def test_mei_facultativo_bloqueia(self):
        vinculos = [
            Vinculo(tipo=TipoVinculo.MEI, data_inicio=date(2020, 1, 1)),
            Vinculo(tipo=TipoVinculo.FACULTATIVO, data_inicio=date(2020, 1, 1)),
        ]
        with pytest.raises(TravaVioladaError, match="CONC-01"):
            trava_conc_01_mei_facultativo_proibido(vinculos, "01/2020")


class TestTravaCal01:
    """Teto ANTES de atualizar monetariamente."""

    def test_teto_aplicado_antes(self):
        sc = Decimal("5000.00")
        teto = Decimal("3000.00")  # Teto da época
        fator = Decimal("3.5")     # Fator INPC acumulado
        resultado = trava_cal_01_teto_antes_de_atualizar(sc, teto, fator, "01/2005")
        # CORRETO: min(5000, 3000) * 3.5 = 10500
        assert resultado == Decimal("10500.0")
        # ERRADO seria: 5000 * 3.5 = 17500

    def test_sc_abaixo_teto_sem_corte(self):
        sc = Decimal("2000.00")
        teto = Decimal("3000.00")
        fator = Decimal("2.0")
        resultado = trava_cal_01_teto_antes_de_atualizar(sc, teto, fator, "01/2010")
        assert resultado == Decimal("4000.0")


class TestTravaCal02:
    """Divisor mínimo de 108 meses."""

    def test_acima_108_usa_real(self):
        media = trava_cal_02_divisor_minimo(200, Decimal("500000.00"))
        assert media == Decimal("500000.00") / Decimal("200")

    def test_abaixo_108_usa_108(self):
        media = trava_cal_02_divisor_minimo(80, Decimal("100000.00"))
        assert media == Decimal("100000.00") / Decimal("108")

    def test_exatamente_108(self):
        media = trava_cal_02_divisor_minimo(108, Decimal("108000.00"))
        assert media == Decimal("1000")


class TestTravaCal03:
    """Descarte não pode reduzir TC abaixo do mínimo."""

    def test_tc_suficiente_ok(self):
        trava_cal_03_descarte_nao_reduz_tc(
            tc_apos_descarte_meses=360,
            tc_minimo_regra_meses=300,
            regra="PONTOS"
        )  # Não deve levantar exceção

    def test_tc_insuficiente_bloqueia(self):
        with pytest.raises(TravaVioladaError, match="CAL-03"):
            trava_cal_03_descarte_nao_reduz_tc(
                tc_apos_descarte_meses=290,
                tc_minimo_regra_meses=300,
                regra="PONTOS"
            )


class TestTravaEsp01:
    """Conversão especial vedada pós 13/11/2019."""

    def test_periodo_pre_reforma_ok(self):
        trava_esp_01_conversao_vedada_pos_reforma(date(2019, 11, 13))  # No limite

    def test_periodo_pos_reforma_bloqueia(self):
        with pytest.raises(TravaVioladaError, match="ESP-01"):
            trava_esp_01_conversao_vedada_pos_reforma(date(2020, 1, 1))


class TestTravaSys02:
    """Indicador desconhecido nunca inventar."""

    def test_indicador_conhecido_ok(self):
        alerta = trava_sys_02_indicador_desconhecido("PEXT", {"PEXT", "IEAN", "IREC-MEI"})
        assert alerta is None

    def test_indicador_desconhecido_alerta(self):
        alerta = trava_sys_02_indicador_desconhecido("XYZABC", {"PEXT", "IEAN"})
        assert alerta is not None
        assert alerta.codigo == "SYS-02"
        assert "NÃO reconhecido" in alerta.mensagem
