"""
Modelo Pydantic para indicadores do CNIS.

Indicadores são códigos que o INSS coloca no CNIS para sinalizar
pendências (P), informações (I) ou acertos (A) nos registros.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ClassificacaoIndicador(str, Enum):
    """Classificação do indicador conforme impacto."""
    PENDENCIA = "P"       # Requer ação — pode impedir cômputo do período
    ALERTA = "I"          # Informativo — pode afetar benefício
    ACERTO = "A"          # Positivo — registro correto/validado
    DESCONHECIDO = "D"    # Indicador não reconhecido (REGRA SYS-02: nunca inventar)


class SeveridadeIndicador(str, Enum):
    """Severidade para priorização no relatório."""
    CRITICA = "CRITICA"       # Bloqueia cômputo do período
    ALTA = "ALTA"             # Afeta benefício/carência
    MEDIA = "MEDIA"           # Requer atenção mas não bloqueia
    INFORMATIVA = "INFORMATIVA"  # Apenas informação


class IndicadorCNIS(BaseModel):
    """
    Um indicador encontrado no CNIS de um segurado.

    REGRA SYS-02 (TRAVA ABSOLUTA): Se o indicador não é reconhecido,
    classificar como DESCONHECIDO e emitir WARNING. NUNCA inventar significado.
    """

    codigo: str = Field(..., min_length=1, max_length=30, description="Código do indicador (ex: PEXT, IEAN)")
    classificacao: ClassificacaoIndicador = Field(..., description="P/I/A/D")
    severidade: SeveridadeIndicador = Field(SeveridadeIndicador.INFORMATIVA)

    nome: str = Field("", description="Nome legível do indicador")
    descricao: str = Field("", description="Descrição detalhada do significado")
    impacto: str = Field("", description="Como afeta o benefício/contribuição")
    acao: str = Field("", description="Ação recomendada para correção")

    # Contexto onde foi encontrado
    competencias_afetadas: list[str] = Field(default_factory=list, description="Competências (MM/AAAA) onde aparece")
    vinculo_sequencia: Optional[int] = Field(None, description="Vínculo associado")

    @property
    def e_pendencia(self) -> bool:
        return self.classificacao == ClassificacaoIndicador.PENDENCIA

    @property
    def e_desconhecido(self) -> bool:
        """
        REGRA SYS-02: Indicador desconhecido requer análise manual.
        O sistema NÃO pode inventar significado nem ignorar silenciosamente.
        """
        return self.classificacao == ClassificacaoIndicador.DESCONHECIDO

    @property
    def requer_acao(self) -> bool:
        return self.classificacao in (
            ClassificacaoIndicador.PENDENCIA,
            ClassificacaoIndicador.DESCONHECIDO,
        )

    @property
    def bloqueia_computo(self) -> bool:
        """Indicadores que impedem o cômputo do período para tempo/carência."""
        return self.codigo in (
            "PREM-BLOQ-EC103",  # Contribuição bloqueada pela EC 103
            "PREC-MENOR-MIN",   # Recolhimento abaixo do mínimo
            "PREC-MENORMIN",    # Variação do código anterior
        )


class ResumoIndicadores(BaseModel):
    """Resumo dos indicadores encontrados no CNIS."""
    total: int = 0
    pendencias: int = 0
    alertas: int = 0
    acertos: int = 0
    desconhecidos: int = 0
    indicadores_criticos: list[str] = Field(default_factory=list)
    indicadores_desconhecidos: list[str] = Field(default_factory=list)
