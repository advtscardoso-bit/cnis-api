"""
Constantes do sistema de Análise de CNIS.

Apenas constantes relevantes para análise diagnóstica do CNIS.
Constantes de regras de aposentadoria ficam no repo planejamento-previdenciario.
"""

from decimal import Decimal

# ══════════════════════════════════════════════════════════════════════════════
# LACUNAS CONTRIBUTIVAS
# ══════════════════════════════════════════════════════════════════════════════

LACUNA_LIMIAR_DIAS = 31               # Até 31 dias não é considerada lacuna
LACUNA_MESES_BAIXA = 3               # Até 3 meses: gravidade BAIXA
LACUNA_MESES_MEDIA = 12              # Até 12 meses: gravidade MÉDIA
LACUNA_MESES_ALTA = 24               # Até 24 meses: gravidade ALTA
                                      # Acima de 24 meses: CRÍTICA

# ══════════════════════════════════════════════════════════════════════════════
# REMUNERAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

MARGEM_PROPORCIONAL_SM = Decimal("0.95")  # 95% do SM (5% de margem)

# ══════════════════════════════════════════════════════════════════════════════
# PERÍODO DE GRAÇA (Art. 15 Lei 8.213/91)
# ══════════════════════════════════════════════════════════════════════════════

PERIODO_GRACA_GERAL = 12                    # meses
PERIODO_GRACA_120_CONTRIBUICOES = 24        # +12 se ≥120 contribuições ininterruptas
LIMIAR_CONTRIBUICOES_ININTERRUPTAS = 120    # para estender o período de graça

# ══════════════════════════════════════════════════════════════════════════════
# SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

VERSAO_SISTEMA = "1.0.0"
NOME_ESCRITORIO = "Tatiana Sampaio Advocacia e Consultoria Jurídica"
