"""
Testes dos modelos Pydantic — validação de tipos, CPF, datas, enums.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.pessoa import Pessoa, Sexo, IdadeDetalhada
from app.models.vinculo import Vinculo, TipoVinculo
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.beneficio import Beneficio, EspecieBeneficio


class TestPessoa:

    def test_pessoa_valida(self):
        p = Pessoa(
            cpf="52998224725",
            nome="Maria Silva",
            data_nascimento=date(1970, 5, 15),
            sexo=Sexo.FEMININO,
        )
        assert p.cpf == "52998224725"
        assert p.sexo == Sexo.FEMININO
        assert p.primeiro_nome == "Maria"
        assert p.pronome_tratamento == "Sra."

    def test_cpf_invalido_rejeita(self):
        with pytest.raises(ValueError, match="CPF"):
            Pessoa(
                cpf="11111111111",  # Todos iguais
                nome="Teste",
                data_nascimento=date(1980, 1, 1),
                sexo=Sexo.MASCULINO,
            )

    def test_cpf_digito_errado_rejeita(self):
        with pytest.raises(ValueError, match="dígito verificador"):
            Pessoa(
                cpf="52998224720",  # Último dígito errado
                nome="Teste",
                data_nascimento=date(1980, 1, 1),
                sexo=Sexo.MASCULINO,
            )

    def test_cpf_com_pontuacao_aceita(self):
        p = Pessoa(
            cpf="529.982.247-25",
            nome="Maria Silva",
            data_nascimento=date(1970, 5, 15),
            sexo=Sexo.FEMININO,
        )
        assert p.cpf == "52998224725"

    def test_data_nascimento_futura_rejeita(self):
        with pytest.raises(ValueError, match="anterior a hoje"):
            Pessoa(
                cpf="52998224725",
                nome="Teste",
                data_nascimento=date(2030, 1, 1),
                sexo=Sexo.MASCULINO,
            )

    def test_idade_detalhada(self, pessoa_mulher_mei):
        idade = pessoa_mulher_mei.idade_em(date(2025, 12, 17))
        assert idade.anos == 59
        assert str(idade)  # Não deve dar erro

    def test_pronome_masculino(self, pessoa_homem_clt):
        assert pessoa_homem_clt.pronome_tratamento == "Sr."

    def test_nits_duplicados(self):
        p = Pessoa(
            cpf="52998224725",
            nome="Teste",
            data_nascimento=date(1970, 1, 1),
            sexo=Sexo.FEMININO,
            nit="12345678901",
            nits_adicionais=["98765432100"],
        )
        assert p.tem_nits_duplicados is True


class TestVinculo:

    def test_vinculo_clt_valido(self):
        v = Vinculo(
            tipo=TipoVinculo.CLT,
            empregador="Empresa XYZ",
            data_inicio=date(2010, 1, 1),
            data_fim=date(2020, 12, 31),
        )
        assert v.e_clt is True
        assert v.e_mei is False
        assert v.em_aberto is False
        assert v.acessa_todas_regras is True

    def test_vinculo_mei_nao_acessa_todas_regras(self):
        v = Vinculo(
            tipo=TipoVinculo.MEI,
            data_inicio=date(2015, 1, 1),
        )
        assert v.e_mei is True
        assert v.acessa_todas_regras is False
        assert v.contribuicao_sobre_sm_apenas is True

    def test_data_fim_antes_inicio_rejeita(self):
        with pytest.raises(ValueError, match="anterior"):
            Vinculo(
                tipo=TipoVinculo.CLT,
                data_inicio=date(2020, 1, 1),
                data_fim=date(2019, 1, 1),
            )

    def test_sobreposicao_vinculos(self):
        v1 = Vinculo(tipo=TipoVinculo.CLT, data_inicio=date(2010, 1, 1), data_fim=date(2015, 12, 31))
        v2 = Vinculo(tipo=TipoVinculo.MEI, data_inicio=date(2013, 6, 1), data_fim=date(2020, 12, 31))
        assert v1.sobrepoe(v2) is True
        assert v2.sobrepoe(v1) is True

    def test_sem_sobreposicao(self):
        v1 = Vinculo(tipo=TipoVinculo.CLT, data_inicio=date(2010, 1, 1), data_fim=date(2012, 12, 31))
        v2 = Vinculo(tipo=TipoVinculo.MEI, data_inicio=date(2013, 6, 1), data_fim=date(2020, 12, 31))
        assert v1.sobrepoe(v2) is False


class TestContribuicao:

    def test_contribuicao_valida(self):
        c = Contribuicao(
            competencia="01/2025",
            valor_original=Decimal("1518.00"),
            tipo=TipoContribuicao.DAS_MEI,
            sm_competencia=Decimal("1518.00"),
        )
        assert c.mes == 1
        assert c.ano == 2025
        assert c.conta_tempo is True
        assert c.conta_carencia is True
        assert c.e_pos_real is True

    def test_competencia_formato_invalido_rejeita(self):
        with pytest.raises(ValueError):
            Contribuicao(
                competencia="2025-01",  # Formato errado
                valor_original=Decimal("1000.00"),
            )

    def test_abaixo_minimo_nao_conta(self):
        c = Contribuicao(
            competencia="06/2024",
            valor_original=Decimal("500.00"),
            tipo=TipoContribuicao.GPS_CI,
            abaixo_minimo=True,
        )
        assert c.conta_tempo is False
        assert c.conta_carencia is False
        assert c.valor_para_media == Decimal("0")

    def test_bloqueada_nao_conta(self):
        c = Contribuicao(
            competencia="03/2024",
            valor_original=Decimal("1412.00"),
            bloqueada=True,
        )
        assert c.conta_tempo is False
        assert c.conta_carencia is False

    def test_extemporanea_conta_tempo_nao_carencia(self):
        c = Contribuicao(
            competencia="09/2023",
            valor_original=Decimal("1320.00"),
            tipo=TipoContribuicao.DAS_MEI,
            extemporanea=True,
        )
        assert c.conta_tempo is True
        assert c.conta_carencia is False  # REGRA MEI-04

    def test_beneficio_conta_tempo_nao_carencia(self):
        c = Contribuicao(
            competencia="05/2020",
            valor_original=Decimal("1500.00"),
            tipo=TipoContribuicao.BENEFICIO,
        )
        assert c.conta_tempo is True
        assert c.conta_carencia is False  # REGRA CONTRIB-02

    def test_pre_real(self):
        c = Contribuicao(
            competencia="06/1994",
            valor_original=Decimal("100.00"),
        )
        assert c.e_pos_real is False

    def test_pos_real_julho_1994(self):
        c = Contribuicao(
            competencia="07/1994",
            valor_original=Decimal("64.79"),
        )
        assert c.e_pos_real is True


class TestBeneficio:

    def test_beneficio_incapacidade(self):
        b = Beneficio(
            especie=EspecieBeneficio.B31,
            dib=date(2020, 3, 15),
            dcb=date(2020, 9, 14),
        )
        assert b.e_incapacidade is True
        assert b.e_auxilio_doenca is True
        assert b.conta_tempo_contribuicao is True
        assert b.ativo is False

    def test_beneficio_ativo(self):
        b = Beneficio(
            especie=EspecieBeneficio.B32,
            dib=date(2022, 1, 1),
        )
        assert b.ativo is True

    def test_dcb_antes_dib_rejeita(self):
        with pytest.raises(ValueError, match="anterior"):
            Beneficio(
                especie=EspecieBeneficio.B31,
                dib=date(2020, 6, 1),
                dcb=date(2020, 3, 1),
            )
