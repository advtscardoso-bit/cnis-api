"""
Modelo Pydantic para vínculos empregatícios/contributivos do CNIS.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class TipoVinculo(str, Enum):
    """Classificação do tipo de vínculo/contribuição."""
    CLT = "CLT"                         # Empregado com carteira
    MEI = "MEI"                         # Microempreendedor Individual (DAS 5%)
    CONTRIBUINTE_INDIVIDUAL = "CI"      # Contribuinte Individual (20%)
    CI_PRESTADOR_PJ = "CI_PJ"           # CI que presta serviço a PJ (11% retido)
    FACULTATIVO = "FACULTATIVO"         # Segurado facultativo (sem atividade)
    FACULTATIVO_BAIXA_RENDA = "FAC_BR"  # Facultativo baixa renda (5%)
    EMPREGADO_DOMESTICO = "DOMESTICO"   # Empregado doméstico
    RURAL_SEGURADO_ESPECIAL = "RURAL_SE"  # Segurado especial (economia familiar)
    RURAL_EMPREGADO = "RURAL_EMP"       # Empregado rural (CTPS)
    RURAL_CI = "RURAL_CI"               # Contribuinte individual rural
    RURAL_AVULSO = "RURAL_AVULSO"       # Trabalhador avulso rural
    SERVIDOR_PUBLICO = "SERVIDOR"       # Servidor público (RPPS)
    MILITAR = "MILITAR"                 # Serviço militar
    BENEFICIO = "BENEFICIO"             # Período em gozo de benefício
    DESCONHECIDO = "DESCONHECIDO"       # Tipo não identificado


class SituacaoVinculo(str, Enum):
    """Situação atual do vínculo."""
    ATIVO = "ATIVO"
    ENCERRADO = "ENCERRADO"
    PENDENTE = "PENDENTE"         # Sem data fim e sem indicação de ativo
    SUSPENSO = "SUSPENSO"         # Em gozo de benefício


class AliquotaContribuicao(str, Enum):
    """Alíquota de contribuição do segurado."""
    CINCO_PORCENTO = "5%"          # MEI, facultativo baixa renda
    ONZE_PORCENTO = "11%"          # Plano simplificado CI, CI prestador PJ
    VINTE_PORCENTO = "20%"         # Plano normal CI, facultativo
    VARIAVEL_CLT = "VARIAVEL_CLT"  # 7,5% a 14% (tabela progressiva CLT)
    ZERO = "0%"                    # Segurado especial rural (sem contribuição)
    DESCONHECIDA = "DESCONHECIDA"


class Vinculo(BaseModel):
    """
    Um vínculo empregatício ou período contributivo do CNIS.

    Pode representar emprego CLT, contribuição MEI, período como CI,
    serviço militar, atividade rural, ou período de benefício.
    """

    # Identificação
    sequencia: Optional[int] = Field(None, description="Número sequencial no CNIS")
    tipo: TipoVinculo = Field(..., description="Tipo do vínculo classificado")
    situacao: SituacaoVinculo = Field(SituacaoVinculo.ENCERRADO)

    # Empregador
    empregador: Optional[str] = Field(None, description="Nome do empregador/fonte pagadora")
    cnpj_cei: Optional[str] = Field(None, description="CNPJ ou CEI do empregador")
    cnae: Optional[str] = Field(None, description="Código CNAE da atividade do empregador")

    # Período
    data_inicio: date = Field(..., description="Data de início do vínculo")
    data_fim: Optional[date] = Field(None, description="Data de fim (None = em aberto)")

    # Cargo e CBO
    cargo: Optional[str] = Field(None, description="Cargo/função exercida")
    cbo: Optional[str] = Field(None, description="Código CBO da ocupação")

    # Contribuição
    aliquota: AliquotaContribuicao = Field(AliquotaContribuicao.DESCONHECIDA)
    ultimo_salario: Optional[Decimal] = Field(None, description="Último salário registrado", ge=0)

    # Classificação especial
    e_especial: bool = Field(False, description="Período exposto a agente nocivo (PPP)")
    base_especial: Optional[int] = Field(None, description="Base especial em anos (15, 20 ou 25)")

    # Indicadores CNIS encontrados neste vínculo
    indicadores: list[str] = Field(default_factory=list, description="Códigos de indicadores CNIS")

    # Observações
    observacoes: Optional[str] = Field(None)
    origem: str = Field("CNIS", description="Fonte do dado: CNIS, CTPS, PPP, CTC, etc.")

    @model_validator(mode="after")
    def validar_datas(self):
        """Data fim deve ser posterior à data início (se informada)."""
        if self.data_fim is not None and self.data_fim < self.data_inicio:
            raise ValueError(
                f"Data fim ({self.data_fim}) anterior à data início ({self.data_inicio}) "
                f"no vínculo {self.empregador or 'sem empregador'}"
            )
        return self

    @property
    def em_aberto(self) -> bool:
        """Vínculo sem data de encerramento."""
        return self.data_fim is None

    @property
    def duracao_dias(self) -> int:
        """Duração do vínculo em dias."""
        fim = self.data_fim or date.today()
        return (fim - self.data_inicio).days

    @property
    def e_mei(self) -> bool:
        return self.tipo == TipoVinculo.MEI

    @property
    def e_clt(self) -> bool:
        return self.tipo == TipoVinculo.CLT

    @property
    def e_rural(self) -> bool:
        return self.tipo in (
            TipoVinculo.RURAL_SEGURADO_ESPECIAL,
            TipoVinculo.RURAL_EMPREGADO,
            TipoVinculo.RURAL_CI,
            TipoVinculo.RURAL_AVULSO,
        )

    @property
    def e_servidor_publico(self) -> bool:
        return self.tipo == TipoVinculo.SERVIDOR_PUBLICO

    @property
    def e_beneficio(self) -> bool:
        return self.tipo == TipoVinculo.BENEFICIO

    @property
    def e_militar(self) -> bool:
        return self.tipo == TipoVinculo.MILITAR

    @property
    def e_facultativo(self) -> bool:
        return self.tipo in (TipoVinculo.FACULTATIVO, TipoVinculo.FACULTATIVO_BAIXA_RENDA)

    @property
    def contribuicao_sobre_sm_apenas(self) -> bool:
        """Verdadeiro se a contribuição é limitada a 1 SM (MEI 5%, facultativo baixa renda)."""
        return self.tipo in (TipoVinculo.MEI, TipoVinculo.FACULTATIVO_BAIXA_RENDA)

    @property
    def acessa_todas_regras(self) -> bool:
        """
        Verdadeiro se o vínculo dá acesso a todas as regras de aposentadoria.
        REGRA MEI-03: MEI 5% SÓ acessa aposentadoria por idade.
        """
        return self.tipo not in (TipoVinculo.MEI, TipoVinculo.FACULTATIVO_BAIXA_RENDA)

    def tem_indicador(self, codigo: str) -> bool:
        """Verifica se o vínculo tem um indicador específico."""
        return codigo in self.indicadores

    def sobrepoe(self, outro: "Vinculo") -> bool:
        """Verifica se dois vínculos têm sobreposição de períodos."""
        fim_self = self.data_fim or date.today()
        fim_outro = outro.data_fim or date.today()
        return self.data_inicio <= fim_outro and outro.data_inicio <= fim_self
