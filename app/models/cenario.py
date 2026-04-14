"""
Modelo Pydantic para cenários de aposentadoria simulados.

Cada cenário representa uma regra de aposentadoria aplicável ao segurado,
com data de elegibilidade, RMI projetada, ROI e ranking comparativo.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.calculos.utils_decimal import ZERO


class RegraAposentadoria(str, Enum):
    """Todas as regras de aposentadoria simuláveis pelo sistema."""

    # Regras pré-reforma (direito adquirido antes de 13/11/2019)
    DIREITO_ADQUIRIDO_TC = "DIREITO_ADQUIRIDO_TC"
    DIREITO_ADQUIRIDO_IDADE = "DIREITO_ADQUIRIDO_IDADE"
    DIREITO_ADQUIRIDO_PONTOS = "DIREITO_ADQUIRIDO_PONTOS"

    # Regras de transição EC 103/2019
    PONTOS = "PONTOS"                       # Art. 15 EC 103
    IDADE_PROGRESSIVA = "IDADE_PROGRESSIVA" # Art. 16 EC 103
    PEDAGIO_50 = "PEDAGIO_50"               # Art. 17 EC 103
    PEDAGIO_100 = "PEDAGIO_100"             # Art. 20 EC 103
    IDADE = "IDADE"                         # Art. 18/19 EC 103

    # Regra definitiva (pós-2033)
    PROGRAMADA = "PROGRAMADA"

    # Regras especiais
    ESPECIAL_25 = "ESPECIAL_25"             # Aposentadoria especial base 25 anos
    ESPECIAL_20 = "ESPECIAL_20"             # Base 20 anos
    ESPECIAL_15 = "ESPECIAL_15"             # Base 15 anos

    # PcD (LC 142/2013)
    PCD_TEMPO_GRAVE = "PCD_TEMPO_GRAVE"
    PCD_TEMPO_MODERADA = "PCD_TEMPO_MODERADA"
    PCD_TEMPO_LEVE = "PCD_TEMPO_LEVE"
    PCD_IDADE = "PCD_IDADE"

    # Rural
    RURAL_IDADE = "RURAL_IDADE"             # 55M/60H, segurado especial
    RURAL_HIBRIDA = "RURAL_HIBRIDA"         # Tema 1.007 STJ

    # Professor
    PROFESSOR_PONTOS = "PROFESSOR_PONTOS"
    PROFESSOR_PEDAGIO_100 = "PROFESSOR_PEDAGIO_100"


class StatusElegibilidade(str, Enum):
    """Status do segurado em relação a uma regra."""
    ELEGIVEL_HOJE = "ELEGIVEL_HOJE"           # Já preenche todos os requisitos
    ELEGIVEL_FUTURO = "ELEGIVEL_FUTURO"       # Preencherá em data futura (projetada)
    INELEGIVEL = "INELEGIVEL"                 # Não atende e não atingirá (ex: MEI 5% para pedágio)
    REQUER_COMPLEMENTACAO = "REQUER_COMPLEMENTACAO"  # Atingível com complementação MEI
    REQUER_ANALISE = "REQUER_ANALISE"         # Depende de análise jurídica (ex: PcD, rural)


class RequisitoFaltante(BaseModel):
    """Um requisito que o segurado ainda não preenche para uma regra."""
    descricao: str = Field(..., description="Ex: 'Idade mínima de 62 anos'")
    valor_atual: str = Field(..., description="Ex: '59 anos, 3 meses'")
    valor_necessario: str = Field(..., description="Ex: '62 anos'")
    falta: str = Field(..., description="Ex: '2 anos, 9 meses'")
    data_prevista: Optional[date] = Field(None, description="Quando atingirá, se projetável")


class CenarioAposentadoria(BaseModel):
    """
    Um cenário completo de aposentadoria para uma regra específica.

    Contém todos os dados necessários para apresentar no relatório:
    elegibilidade, RMI, ROI, requisitos faltantes, e fundamentação legal.
    """

    # Identificação da regra
    regra: RegraAposentadoria = Field(...)
    nome_regra: str = Field(..., description="Nome legível da regra para o relatório")
    fundamentacao_legal: str = Field("", description="Ex: 'Art. 15 da EC 103/2019'")

    # Status
    status: StatusElegibilidade = Field(...)
    requisitos_faltantes: list[RequisitoFaltante] = Field(default_factory=list)

    # Datas
    data_elegibilidade: Optional[date] = Field(None, description="Data em que o segurado se torna elegível")
    data_calculo: date = Field(default_factory=date.today, description="Data de referência do cálculo")

    # Valores calculados (todos em Decimal — REGRA SYS-01)
    media_salarial: Decimal = Field(ZERO, description="Média dos SC usada no cálculo")
    media_com_descarte: Optional[Decimal] = Field(None, description="Média otimizada com descarte Art. 26")
    contribuicoes_descartadas: int = Field(0, description="Quantidade de SC descartadas")
    coeficiente: Decimal = Field(ZERO, description="Coeficiente de cálculo (ex: 0.76 = 76%)")
    fator_previdenciario: Optional[Decimal] = Field(None, description="Fator previdenciário (se aplicável)")
    rmi: Decimal = Field(ZERO, description="Renda Mensal Inicial estimada")
    rmi_com_descarte: Optional[Decimal] = Field(None, description="RMI com descarte otimizado")

    # Dados do segurado na data de elegibilidade
    idade_na_elegibilidade: Optional[str] = Field(None, description="Idade ao se aposentar")
    tempo_contribuicao_na_elegibilidade: Optional[str] = Field(None, description="TC ao se aposentar")
    pontos_na_elegibilidade: Optional[int] = Field(None, description="Pontos (idade+TC) se aplicável")
    carencia_na_elegibilidade: Optional[int] = Field(None, description="Meses de carência")

    # ROI e custo-benefício
    contribuicao_mensal: Decimal = Field(ZERO, description="Quanto paga por mês até aposentar")
    meses_ate_aposentadoria: int = Field(0, description="Meses de contribuição restantes")
    total_investido: Decimal = Field(ZERO, description="Custo total das contribuições até aposentar")
    valor_beneficio_vida: Decimal = Field(ZERO, description="Total recebido até expectativa IBGE (84 anos)")
    payback_meses: int = Field(0, description="Meses para recuperar o investimento")
    roi: Decimal = Field(ZERO, description="Retorno sobre investimento (vida - investido)")
    roi_percentual: Decimal = Field(ZERO, description="ROI em percentual")

    # Complementação MEI (se aplicável)
    requer_complementacao_mei: bool = Field(False)
    custo_complementacao_total: Decimal = Field(ZERO, description="Custo total da complementação MEI")
    meses_complementacao: int = Field(0)

    # Ranking
    ranking: int = Field(0, description="Posição no ranking (1 = melhor cenário)")
    e_recomendado: bool = Field(False, description="Cenário recomendado pelo sistema")
    motivo_recomendacao: str = Field("", description="Por que este cenário é ou não recomendado")

    @property
    def elegivel_hoje(self) -> bool:
        return self.status == StatusElegibilidade.ELEGIVEL_HOJE

    @property
    def rmi_efetiva(self) -> Decimal:
        """RMI efetiva considerando descarte se disponível e vantajoso."""
        if self.rmi_com_descarte is not None and self.rmi_com_descarte > self.rmi:
            return self.rmi_com_descarte
        return self.rmi

    @property
    def descarte_vantajoso(self) -> bool:
        """Verdadeiro se o descarte melhora a RMI."""
        return (
            self.rmi_com_descarte is not None
            and self.rmi_com_descarte > self.rmi
        )


class ResultadoSimulacao(BaseModel):
    """Resultado completo da simulação de todos os cenários para um segurado."""

    data_simulacao: date = Field(default_factory=date.today)
    cenarios: list[CenarioAposentadoria] = Field(default_factory=list)
    melhor_cenario: Optional[RegraAposentadoria] = Field(None)
    cenario_mais_rapido: Optional[RegraAposentadoria] = Field(None)
    cenario_maior_rmi: Optional[RegraAposentadoria] = Field(None)
    cenario_melhor_roi: Optional[RegraAposentadoria] = Field(None)

    # Alertas gerais da simulação
    alertas: list[str] = Field(default_factory=list)

    # Flags de perfil
    perfil_mei_puro: bool = Field(False)
    perfil_clt_puro: bool = Field(False)
    perfil_misto: bool = Field(False)
    tem_tempo_especial: bool = Field(False)
    candidato_pcd: bool = Field(False)
    tem_tempo_rural: bool = Field(False)
    tem_tempo_militar: bool = Field(False)

    @property
    def total_cenarios(self) -> int:
        return len(self.cenarios)

    @property
    def cenarios_elegiveis_hoje(self) -> list[CenarioAposentadoria]:
        return [c for c in self.cenarios if c.elegivel_hoje]

    @property
    def cenarios_futuros(self) -> list[CenarioAposentadoria]:
        return [c for c in self.cenarios if c.status == StatusElegibilidade.ELEGIVEL_FUTURO]

    @property
    def cenarios_com_complementacao(self) -> list[CenarioAposentadoria]:
        return [c for c in self.cenarios if c.requer_complementacao_mei]

    def cenario_por_regra(self, regra: RegraAposentadoria) -> Optional[CenarioAposentadoria]:
        for c in self.cenarios:
            if c.regra == regra:
                return c
        return None
