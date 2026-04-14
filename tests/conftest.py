"""
Fixtures compartilhadas para toda a suite de testes.

Fornece dados de teste realistas para os cenários mais comuns:
- Pessoa (homem, mulher)
- Vínculos (MEI puro, CLT puro, misto)
- Contribuições
- Benefícios
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.pessoa import Pessoa, Sexo
from app.models.vinculo import Vinculo, TipoVinculo, AliquotaContribuicao
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.beneficio import Beneficio, EspecieBeneficio


# ══════════════════════════════════════════════════════════════════════════════
# PESSOAS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def pessoa_mulher_mei():
    """Sra. Isabel — MEI pura, 59 anos, corretora de imóveis."""
    return Pessoa(
        cpf="52998224725",  # CPF válido fictício
        nome="ISABEL MARIA GULIAS MONTANHA",
        data_nascimento=date(1966, 7, 11),
        sexo=Sexo.FEMININO,
        nit="12345678901",
    )


@pytest.fixture
def pessoa_mulher_mista():
    """Sra. Andréa — CLT + MEI, 52 anos."""
    return Pessoa(
        cpf="71428793860",  # CPF válido fictício
        nome="ANDREA CRISTINA SILVA SANTOS",
        data_nascimento=date(1973, 4, 22),
        sexo=Sexo.FEMININO,
        nit="98765432100",
    )


@pytest.fixture
def pessoa_homem_clt():
    """Sr. Carlos — CLT puro, 58 anos, operário."""
    return Pessoa(
        cpf="45632178905",  # CPF válido fictício
        nome="CARLOS EDUARDO FERREIRA LIMA",
        data_nascimento=date(1967, 11, 3),
        sexo=Sexo.MASCULINO,
        nit="11122233344",
    )


# ══════════════════════════════════════════════════════════════════════════════
# VÍNCULOS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def vinculos_mei_puro():
    """20 anos de contribuição como MEI (2005-2025)."""
    return [
        Vinculo(
            sequencia=1,
            tipo=TipoVinculo.MEI,
            empregador="MEI - ISABEL MARIA GULIAS MONTANHA",
            data_inicio=date(2005, 3, 1),
            data_fim=None,  # em aberto
            aliquota=AliquotaContribuicao.CINCO_PORCENTO,
            indicadores=["IREC-MEI"],
        ),
    ]


@pytest.fixture
def vinculos_clt_puro():
    """35 anos de CLT (1990-2025)."""
    return [
        Vinculo(
            sequencia=1,
            tipo=TipoVinculo.CLT,
            empregador="SIDERURGICA VALE DO ACO LTDA",
            cnpj_cei="12345678000190",
            data_inicio=date(1990, 2, 1),
            data_fim=date(2010, 6, 30),
            aliquota=AliquotaContribuicao.VARIAVEL_CLT,
            ultimo_salario=Decimal("3500.00"),
        ),
        Vinculo(
            sequencia=2,
            tipo=TipoVinculo.CLT,
            empregador="METALURGICA SERRA LTDA",
            cnpj_cei="98765432000110",
            data_inicio=date(2010, 8, 1),
            data_fim=None,  # em aberto
            aliquota=AliquotaContribuicao.VARIAVEL_CLT,
            ultimo_salario=Decimal("4200.00"),
        ),
    ]


@pytest.fixture
def vinculos_misto_clt_mei():
    """CLT de 2000-2015 + MEI de 2012 em diante (concomitância 2012-2015)."""
    return [
        Vinculo(
            sequencia=1,
            tipo=TipoVinculo.CLT,
            empregador="COMERCIO VAREJISTA SERRA LTDA",
            cnpj_cei="11223344000155",
            data_inicio=date(2000, 1, 1),
            data_fim=date(2015, 12, 31),
            aliquota=AliquotaContribuicao.VARIAVEL_CLT,
            ultimo_salario=Decimal("2800.00"),
        ),
        Vinculo(
            sequencia=2,
            tipo=TipoVinculo.MEI,
            empregador="MEI - ANDREA CRISTINA SILVA SANTOS",
            data_inicio=date(2012, 6, 1),
            data_fim=None,
            aliquota=AliquotaContribuicao.CINCO_PORCENTO,
            indicadores=["IREC-MEI"],
        ),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# CONTRIBUIÇÕES
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def contribuicoes_mei_12_meses():
    """12 meses de contribuição MEI (01/2025 a 12/2025) a R$ 1.518,00."""
    return [
        Contribuicao(
            competencia=f"{m:02d}/2025",
            vinculo_sequencia=1,
            valor_original=Decimal("1518.00"),
            tipo=TipoContribuicao.DAS_MEI,
            sm_competencia=Decimal("1518.00"),
        )
        for m in range(1, 13)
    ]


@pytest.fixture
def contribuicoes_clt_12_meses():
    """12 meses de CLT (01/2025 a 12/2025) a R$ 4.200,00."""
    return [
        Contribuicao(
            competencia=f"{m:02d}/2025",
            vinculo_sequencia=2,
            valor_original=Decimal("4200.00"),
            tipo=TipoContribuicao.EMPREGADOR,
            sm_competencia=Decimal("1518.00"),
            teto_competencia=Decimal("8157.41"),
        )
        for m in range(1, 13)
    ]


@pytest.fixture
def contribuicao_abaixo_minimo():
    """Contribuição com valor abaixo do SM — não conta para nada."""
    return Contribuicao(
        competencia="06/2024",
        vinculo_sequencia=1,
        valor_original=Decimal("500.00"),
        tipo=TipoContribuicao.GPS_CI,
        sm_competencia=Decimal("1412.00"),
        abaixo_minimo=True,
        indicadores=["PREC-MENOR-MIN"],
    )


@pytest.fixture
def contribuicao_bloqueada():
    """Contribuição bloqueada pela EC 103."""
    return Contribuicao(
        competencia="03/2024",
        vinculo_sequencia=1,
        valor_original=Decimal("1412.00"),
        tipo=TipoContribuicao.DAS_MEI,
        sm_competencia=Decimal("1412.00"),
        bloqueada=True,
        indicadores=["PREM-BLOQ-EC103"],
    )


@pytest.fixture
def contribuicao_extemporanea():
    """DAS MEI pago em atraso — conta tempo mas não carência."""
    return Contribuicao(
        competencia="09/2023",
        vinculo_sequencia=1,
        valor_original=Decimal("1320.00"),
        tipo=TipoContribuicao.DAS_MEI,
        sm_competencia=Decimal("1320.00"),
        extemporanea=True,
        indicadores=["PREM-EXT"],
    )


# ══════════════════════════════════════════════════════════════════════════════
# BENEFÍCIOS
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def beneficio_auxilio_doenca():
    """Auxílio-doença de 6 meses — conta tempo mas não carência."""
    return Beneficio(
        especie=EspecieBeneficio.B31,
        nb="1234567890",
        dib=date(2020, 3, 15),
        dcb=date(2020, 9, 14),
        valor=Decimal("1500.00"),
        cid="M54.5",  # Lombalgia
    )


@pytest.fixture
def beneficio_auxilio_acidentario():
    """Auxílio-doença acidentário — gatilho para módulo PcD."""
    return Beneficio(
        especie=EspecieBeneficio.B91,
        nb="9876543210",
        dib=date(2018, 1, 10),
        dcb=date(2019, 6, 30),
        valor=Decimal("2000.00"),
        cid="S62.0",  # Fratura de navicular
    )
