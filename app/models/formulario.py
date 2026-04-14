"""
Modelo Pydantic para dados do formulário de entrevista do cliente.

Captura todas as informações do Google Forms "Planejamento Previdenciário -
Formulário de Entrevista com o Cliente" que NÃO constam no CNIS mas são
essenciais para o planejamento (ex: sexo, estado civil, PcD, atividade rural).
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EstadoCivil(str, Enum):
    SOLTEIRO = "SOLTEIRO"
    CASADO = "CASADO"
    UNIAO_ESTAVEL = "UNIAO_ESTAVEL"
    DIVORCIADO = "DIVORCIADO"
    VIUVO = "VIUVO"


class FaixaRenda(str, Enum):
    ATE_1SM = "ATE_1SM"
    DE_1_A_2SM = "DE_1_A_2SM"
    DE_2_A_3SM = "DE_2_A_3SM"
    DE_3_A_TETO = "DE_3_A_TETO"
    ACIMA_TETO = "ACIMA_TETO"


class ExpectativaIdade(str, Enum):
    ATE_55 = "ATE_55"
    ENTRE_56_60 = "ENTRE_56_60"
    ENTRE_61_65 = "ENTRE_61_65"
    MAIS_65 = "MAIS_65"
    ASSIM_QUE_POSSIVEL = "ASSIM_QUE_POSSIVEL"


class ValorContribuicaoDesejado(str, Enum):
    UM_SM = "UM_SM"
    TRES_SM = "TRES_SM"
    TETO_INSS = "TETO_INSS"
    CLT_SALARIO = "CLT_SALARIO"


class RegimeTributario(str, Enum):
    SIMPLES_NACIONAL = "SIMPLES_NACIONAL"
    LUCRO_PRESUMIDO = "LUCRO_PRESUMIDO"
    LUCRO_REAL = "LUCRO_REAL"
    MEI = "MEI"
    NAO_APLICA = "NAO_APLICA"


class ImportanciaFator(str, Enum):
    NADA = "NADA"
    POUCO = "POUCO"
    MODERADO = "MODERADO"
    MUITO = "MUITO"


class OrigemConhecimento(str, Enum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    TIKTOK = "TIKTOK"
    GOOGLE = "GOOGLE"
    INDICACAO = "INDICACAO"
    OUTRO = "OUTRO"


class DadosFormulario(BaseModel):
    """
    Dados extraídos do formulário de entrevista do cliente.

    Campos marcados com * são obrigatórios no formulário Google.
    Campos Optional foram condicionais ou opcionais.
    """

    # ── Identificação (sobrepõe/complementa CNIS) ──
    nome_completo: str = Field(..., min_length=2, max_length=200)
    sexo: str = Field(..., pattern=r"^(M|F)$", description="M ou F")
    data_nascimento: date = Field(...)
    cpf: str = Field(..., description="CPF do cliente")
    celular: str = Field(..., description="Número com DDD")
    profissao: str = Field(...)
    origem_conhecimento: Optional[OrigemConhecimento] = None
    origem_outro: Optional[str] = None

    # ── Situação Pessoal ──
    estado_civil: EstadoCivil = Field(...)
    uniao_estavel_regularizada: Optional[bool] = None
    tem_dependentes: bool = Field(...)

    # ── Motivação e Objetivos ──
    motivacao_principal: str = Field(...)
    motivacao_outro: Optional[str] = None
    interesse_regularizacao_cnis: bool = Field(...)

    # ── Situação Laboral ──
    trabalhando_atualmente: bool = Field(...)
    carteira_assinada: Optional[bool] = None
    faixa_renda: Optional[FaixaRenda] = None
    expectativa_idade_aposentadoria: Optional[ExpectativaIdade] = None

    # ── Contribuição ──
    pretende_aumentar_contribuicao: Optional[str] = None
    pretende_retomar_contribuicao: Optional[str] = None
    valor_contribuicao_desejado: Optional[ValorContribuicaoDesejado] = None
    regime_tributario: Optional[RegimeTributario] = None

    # ── Condições Especiais dos Vínculos ──
    tem_atividade_especial: bool = Field(False)
    tem_trabalho_rural: bool = Field(False)
    tem_mei: bool = Field(False)
    tem_periodos_sem_recolhimento: bool = Field(False)

    # ── Documentos ──
    documentos_digitalizados: list[str] = Field(default_factory=list)

    # ── Histórico Previdenciário ──
    ja_solicitou_beneficio: bool = Field(False)
    beneficio_solicitado: Optional[str] = None
    recebe_pensao_morte: bool = Field(False)
    ja_recebeu_salario_maternidade: bool = Field(False)
    ultima_contribuicao: Optional[str] = None

    # ── Histórico Militar / Escola Técnica ──
    serviu_exercito: Optional[bool] = None
    fez_escola_tecnica: bool = Field(False)

    # ── Serviço Público ──
    trabalhou_servico_publico: Optional[str] = None
    servico_publico_quando_onde: Optional[str] = None

    # ── Processo Trabalhista ──
    processo_trabalhista: Optional[str] = None
    processo_trabalhista_copia: Optional[bool] = None
    processo_trabalhista_vinculo_registrado: Optional[bool] = None

    # ── Trabalho no Exterior ──
    trabalhou_exterior: bool = Field(False)
    pais_exterior: Optional[str] = None
    contribuiu_exterior: bool = Field(False)
    periodo_contribuicao_exterior: Optional[str] = None
    dupla_cidadania: Optional[str] = None

    # ── Atividade Especial/Insalubre ──
    trabalhou_insalubre: bool = Field(False)
    empresa_insalubre: Optional[str] = None
    conhece_aposentadoria_especial: Optional[bool] = None
    doenca_trabalho: bool = Field(False)

    # ── Parcelamento / MEI / Rural ──
    parcelamento_divida_previdenciaria: bool = Field(False)
    ja_foi_mei: bool = Field(False)
    trabalhou_meio_rural: bool = Field(False)
    periodo_rural: Optional[str] = None

    # ── PcD e Acidentes ──
    e_pcd: bool = Field(False)
    descricao_pcd: Optional[str] = None
    sofreu_acidente: bool = Field(False)
    sequela_acidente: bool = Field(False)
    cirurgia_acidente: bool = Field(False)

    # ── Objetivos Financeiros ──
    importancia_maximo_valor: Optional[ImportanciaFator] = None
    importancia_idade_jovem: Optional[ImportanciaFator] = None
    importancia_baixo_custo: Optional[ImportanciaFator] = None

    # ── Processos Judiciais ──
    processo_previdenciario_andamento: Optional[str] = None
    informacoes_adicionais: Optional[str] = None

    @field_validator("cpf")
    @classmethod
    def limpar_cpf(cls, v: str) -> str:
        """Remove formatação do CPF, mantém apenas dígitos."""
        return "".join(c for c in v if c.isdigit())

    @field_validator("celular")
    @classmethod
    def limpar_celular(cls, v: str) -> str:
        """Remove formatação do celular."""
        return "".join(c for c in v if c.isdigit())
