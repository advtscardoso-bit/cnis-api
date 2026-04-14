"""
Modelo Pydantic para o relatório de planejamento previdenciário.

Agrega todos os dados necessários para gerar o PDF de 25-45 páginas,
incluindo dados pessoais, cálculos, cenários e configurações condicionais.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.calculos.utils_decimal import ZERO
from app.models.pessoa import Pessoa, IdadeDetalhada
from app.models.vinculo import Vinculo
from app.models.contribuicao import Contribuicao, ResumoContribuicoes
from app.models.beneficio import Beneficio
from app.models.indicador import IndicadorCNIS, ResumoIndicadores
from app.models.cenario import CenarioAposentadoria, ResultadoSimulacao


class PerfilContributivo(str, Enum):
    """Perfil do segurado — determina quais páginas incluir no relatório."""
    MEI_PURO = "MEI_PURO"
    CLT_PURO = "CLT_PURO"
    MISTO_CLT_MEI = "MISTO_CLT_MEI"
    CONTRIBUINTE_INDIVIDUAL = "CI"
    RURAL = "RURAL"
    SERVIDOR_PUBLICO = "SERVIDOR"
    MISTO_COMPLEXO = "MISTO_COMPLEXO"  # 3+ tipos de vínculo


class TipoRelatorio(str, Enum):
    """Tipo de documento a gerar."""
    DIAGNOSTICO = "DIAGNOSTICO"          # Análise do CNIS (sistema existente)
    PLANEJAMENTO = "PLANEJAMENTO"        # Planejamento previdenciário completo


class DadosTempoContribuicao(BaseModel):
    """Dados consolidados de tempo de contribuição."""
    total: str = Field("", description="Ex: '30 anos, 10 meses e 24 dias'")
    total_dias: int = 0
    total_anos: int = 0
    total_meses_residual: int = 0
    total_dias_residual: int = 0

    # Tempo por tipo de vínculo
    tempo_clt: Optional[str] = None
    tempo_mei: Optional[str] = None
    tempo_rural: Optional[str] = None
    tempo_especial: Optional[str] = None
    tempo_especial_convertido: Optional[str] = None
    tempo_militar: Optional[str] = None
    tempo_beneficio: Optional[str] = None  # Auxílio-doença intercalado

    # Tempo que conta vs. que não conta
    tempo_valido_todas_regras: Optional[str] = None  # Exclui MEI 5% para regras de transição
    tempo_valido_so_idade: Optional[str] = None       # Inclui MEI 5%


class DadosQualidadeSegurado(BaseModel):
    """Resultado da análise de qualidade de segurado."""
    qualidade_ativa: bool = False
    data_perda_qualidade: Optional[date] = None
    periodo_graca_meses: int = 12
    motivo_periodo_graca: str = ""
    meses_restantes: Optional[int] = None
    alerta_urgente: bool = False  # < 3 meses para perder
    contribuicoes_ininterruptas: int = 0


class DadosIndicadoresAuditoria(BaseModel):
    """Dados para a página condicional de auditoria de indicadores."""

    class LinhaAuditoria(BaseModel):
        indicador: str
        periodo_afetado: str
        significado_juridico: str
        acao_documentacao: str

    linhas: list[LinhaAuditoria] = Field(default_factory=list)
    tem_pendencias_criticas: bool = False


class DadosOrientacaoContributiva(BaseModel):
    """Dados para a página 'O que fazer a partir de agora'."""

    class EstrategiaContributiva(BaseModel):
        nome: str                          # Ex: "Manter contribuição atual"
        contribuicao_mensal: Decimal = ZERO
        codigo_recolhimento: str = ""      # Ex: "DAS MEI", "GPS 1007", "GPS 1910"
        meses_restantes: int = 0
        custo_total: Decimal = ZERO
        rmi_projetada: Decimal = ZERO
        data_aposentadoria: Optional[date] = None
        roi: Decimal = ZERO
        e_recomendada: bool = False
        justificativa: str = ""

    estrategias: list[EstrategiaContributiva] = Field(default_factory=list)
    estrategia_recomendada: Optional[str] = None


class DadosPensaoMorte(BaseModel):
    """Estimativa de pensão por morte."""
    valor_estimado: Decimal = ZERO
    aposentadoria_hipotetica: Decimal = ZERO
    coeficiente_pensao: str = ""           # Ex: "70% (50% + 10% × 2 dependentes)"
    dependentes: int = 0
    duracao_conjuge: str = ""              # Ex: "Vitalícia" ou "20 anos"
    tem_qualidade: bool = False            # Se não tem, dependentes não receberiam


class DadosSalarioMaternidade(BaseModel):
    """Estimativa de salário-maternidade."""
    valor_mensal: Decimal = ZERO
    valor_total_120_dias: Decimal = ZERO
    carencia_ok: bool = False
    carencia_faltam: int = 0
    categoria_calculo: str = ""            # Ex: "MEI: 1 salário mínimo"


class ConfigRelatorio(BaseModel):
    """Configurações de quais páginas incluir no relatório."""

    # Páginas condicionais
    incluir_pedagio_100: bool = False       # Só no perfil misto
    incluir_unificacao_nits: bool = False   # Se há NITs duplicados
    incluir_auditoria_indicadores: bool = False  # Se há indicadores com pendência
    incluir_analise_especial: bool = False  # Se há PPP
    incluir_cenario_pcd: bool = False       # Se é candidato PcD
    incluir_analise_rural: bool = False     # Se há tempo rural
    incluir_averbacao_militar: bool = False # Se há tempo militar
    incluir_salario_maternidade: bool = False  # Se mulher ≤ 50 anos

    # Número estimado de páginas de cenários detalhados
    num_paginas_cenarios: int = 1           # Mínimo 1, máximo ~4

    @property
    def total_paginas_estimado(self) -> int:
        """Estima o número total de páginas do relatório."""
        base = 13  # Páginas fixas
        condicionais = sum([
            self.incluir_pedagio_100,
            self.incluir_unificacao_nits,
            self.incluir_auditoria_indicadores,
            self.incluir_analise_especial,
            self.incluir_cenario_pcd,
            self.incluir_analise_rural,
            self.incluir_averbacao_militar,
            self.incluir_salario_maternidade,
        ])
        variaveis = 8  # Carta, objetivo, TC, cenários, conclusão, etc.
        return base + condicionais + variaveis + self.num_paginas_cenarios


class DadosRelatorio(BaseModel):
    """
    Modelo principal que agrega TODOS os dados necessários para gerar
    o relatório de planejamento previdenciário.

    Este é o "contrato" entre o motor de cálculos e o gerador de relatórios.
    """

    # Metadados
    tipo: TipoRelatorio = Field(TipoRelatorio.PLANEJAMENTO)
    data_referencia: date = Field(default_factory=date.today)
    data_geracao: date = Field(default_factory=date.today)
    versao_sistema: str = Field("1.0.0")

    # Dados pessoais
    pessoa: Pessoa
    perfil: PerfilContributivo

    # Dados extraídos do CNIS
    vinculos: list[Vinculo] = Field(default_factory=list)
    contribuicoes: list[Contribuicao] = Field(default_factory=list)
    beneficios: list[Beneficio] = Field(default_factory=list)
    indicadores: list[IndicadorCNIS] = Field(default_factory=list)

    # Resumos calculados
    resumo_contribuicoes: ResumoContribuicoes = Field(default_factory=ResumoContribuicoes)
    resumo_indicadores: ResumoIndicadores = Field(default_factory=ResumoIndicadores)

    # Cálculos principais
    tempo_contribuicao: DadosTempoContribuicao = Field(default_factory=DadosTempoContribuicao)
    qualidade_segurado: DadosQualidadeSegurado = Field(default_factory=DadosQualidadeSegurado)
    carencia_meses: int = 0
    idade: Optional[IdadeDetalhada] = None

    # Simulação de cenários
    simulacao: ResultadoSimulacao = Field(default_factory=ResultadoSimulacao)

    # Módulos complementares
    orientacao_contributiva: DadosOrientacaoContributiva = Field(
        default_factory=DadosOrientacaoContributiva
    )
    pensao_morte: Optional[DadosPensaoMorte] = None
    salario_maternidade: Optional[DadosSalarioMaternidade] = None

    # Páginas condicionais
    auditoria_indicadores: Optional[DadosIndicadoresAuditoria] = None

    # Configuração do relatório
    config: ConfigRelatorio = Field(default_factory=ConfigRelatorio)

    # Textos gerados por IA (Claude API)
    texto_carta: str = Field("", description="Carta personalizada ao cliente")
    texto_objetivo: str = Field("", description="Objetivo do plano personalizado")
    texto_cenarios: str = Field("", description="Análise dos cenários")
    texto_conclusao: str = Field("", description="Conclusão e recomendação final")

    # Constantes usadas no relatório
    salario_minimo_vigente: Decimal = ZERO
    teto_inss_vigente: Decimal = ZERO

    # Flag de revisão humana (REGRA SYS-03)
    aprovado_por: Optional[str] = Field(None, description="Nome do advogado que revisou")
    data_aprovacao: Optional[date] = Field(None)
    e_rascunho: bool = Field(True, description="True até ser aprovado pela advogada")
