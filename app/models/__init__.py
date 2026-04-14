"""
Modelos Pydantic do sistema de Análise de CNIS.

Todos os modelos usam Decimal para valores monetários (REGRA SYS-01).
"""

from app.models.pessoa import Pessoa, Sexo, IdadeDetalhada
from app.models.vinculo import Vinculo, TipoVinculo, SituacaoVinculo, AliquotaContribuicao
from app.models.contribuicao import Contribuicao, TipoContribuicao, ResumoContribuicoes
from app.models.beneficio import Beneficio, EspecieBeneficio, BENEFICIOS_INCAPACIDADE
from app.models.indicador import IndicadorCNIS, ClassificacaoIndicador, SeveridadeIndicador, ResumoIndicadores

__all__ = [
    "Pessoa", "Sexo", "IdadeDetalhada",
    "Vinculo", "TipoVinculo", "SituacaoVinculo", "AliquotaContribuicao",
    "Contribuicao", "TipoContribuicao", "ResumoContribuicoes",
    "Beneficio", "EspecieBeneficio", "BENEFICIOS_INCAPACIDADE",
    "IndicadorCNIS", "ClassificacaoIndicador", "SeveridadeIndicador", "ResumoIndicadores",
]
