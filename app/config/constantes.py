"""
Constantes do sistema de planejamento previdenciário.

Valores centralizados e versionados. Atualizar anualmente.
REGRA SYS-04: Sempre usar SM e teto vigentes na competência histórica
para cálculos retroativos. Estas constantes são para o ANO CORRENTE.
"""

from datetime import date
from decimal import Decimal

# ══════════════════════════════════════════════════════════════════════════════
# VALORES VIGENTES 2026
# ══════════════════════════════════════════════════════════════════════════════

SALARIO_MINIMO_2026 = Decimal("1518.00")  # TODO: atualizar quando sair o valor oficial 2026 — usando valor de 2025 como referência
TETO_RGPS_2026 = Decimal("8157.41")       # TODO: atualizar quando sair o valor oficial 2026

# Alíquotas de contribuição
ALIQUOTA_MEI = Decimal("0.05")             # 5% sobre SM
ALIQUOTA_COMPLEMENTACAO_MEI = Decimal("0.15")  # 15% sobre SM (GPS 1910)
ALIQUOTA_CI_SIMPLIFICADO = Decimal("0.11")  # 11% sobre SM (plano simplificado)
ALIQUOTA_CI_NORMAL = Decimal("0.20")        # 20% sobre SC

# Valores derivados do MEI 2026
DAS_MEI_MENSAL = SALARIO_MINIMO_2026 * ALIQUOTA_MEI              # R$ 75,90 (com SM 1518)
COMPLEMENTACAO_MEI_MENSAL = SALARIO_MINIMO_2026 * ALIQUOTA_COMPLEMENTACAO_MEI  # R$ 227,70
TOTAL_MEI_COMPLEMENTADO = DAS_MEI_MENSAL + COMPLEMENTACAO_MEI_MENSAL  # R$ 303,60

# ══════════════════════════════════════════════════════════════════════════════
# DATAS MARCO
# ══════════════════════════════════════════════════════════════════════════════

DATA_REFORMA_EC103 = date(2019, 11, 13)    # EC 103/2019 — Reforma da Previdência
DATA_INICIO_REAL = date(1994, 7, 1)        # Plano Real — início do cálculo da média
DATA_LEI_9876 = date(1999, 11, 26)         # Lei 9.876 — mudou cálculo da média
DATA_VEDA_CONVERSAO_ESPECIAL = date(2019, 11, 13)  # Vedação de conversão especial→comum

# Marcos legislativos para enquadramento especial (PPP)
DATA_FIM_CATEGORIA_PROFISSIONAL = date(1995, 4, 28)   # Até aqui: por categoria
DATA_EXIGE_LAUDO = date(1997, 3, 6)                    # A partir daqui: exige laudo
DATA_EXIGE_PPP = date(2004, 1, 1)                      # A partir daqui: exige PPP
DATA_EPI_OBRIGATORIO = date(1998, 12, 3)               # Campo EPI eficaz obrigatório

# ══════════════════════════════════════════════════════════════════════════════
# REQUISITOS DE APOSENTADORIA — REGRAS DEFINITIVAS PÓS-TRANSIÇÃO
# ══════════════════════════════════════════════════════════════════════════════

# Aposentadoria por idade (Art. 19 EC 103/2019) — regra definitiva
IDADE_MINIMA_HOMEM = 65
IDADE_MINIMA_MULHER = 62
TC_MINIMO_IDADE_HOMEM = 15   # anos
TC_MINIMO_IDADE_MULHER = 15  # anos
CARENCIA_MINIMA = 180         # meses (todas as regras)

# Tempo de contribuição mínimo para regras de transição
TC_MINIMO_TRANSICAO_HOMEM = 35  # anos
TC_MINIMO_TRANSICAO_MULHER = 30  # anos

# Coeficiente pós-EC 103: 60% + 2% por ano excedente
COEFICIENTE_BASE = Decimal("0.60")        # 60%
COEFICIENTE_INCREMENTO = Decimal("0.02")  # 2% por ano
ANOS_EXCEDENTE_HOMEM = 20   # Acima de 20 anos TC
ANOS_EXCEDENTE_MULHER = 15  # Acima de 15 anos TC
COEFICIENTE_MAXIMO = Decimal("1.00")      # Teto de 100%

# Pedágio 50% (Art. 17 EC 103) — requisitos NA DATA DA REFORMA
PEDAGIO_50_TC_MINIMO_HOMEM_NA_REFORMA = 33  # anos em 13/11/2019
PEDAGIO_50_TC_MINIMO_MULHER_NA_REFORMA = 28  # anos em 13/11/2019

# Pedágio 100% (Art. 20 EC 103)
PEDAGIO_100_IDADE_HOMEM = 60
PEDAGIO_100_IDADE_MULHER = 57

# Professor (redução de 5 anos e 5 pontos)
REDUCAO_PROFESSOR_ANOS = 5
REDUCAO_PROFESSOR_PONTOS = 5

# ══════════════════════════════════════════════════════════════════════════════
# APOSENTADORIA PcD (LC 142/2013)
# ══════════════════════════════════════════════════════════════════════════════

PCD_IDADE_MINIMA = 55  # Igual para homem e mulher

# TC mínimo PcD por tempo (homem / mulher)
PCD_TC_GRAVE_HOMEM = 25
PCD_TC_GRAVE_MULHER = 20
PCD_TC_MODERADA_HOMEM = 29
PCD_TC_MODERADA_MULHER = 24
PCD_TC_LEVE_HOMEM = 33
PCD_TC_LEVE_MULHER = 28

# PcD por idade
PCD_TC_IDADE = 15  # 15 anos na condição de PcD

# ══════════════════════════════════════════════════════════════════════════════
# APOSENTADORIA RURAL
# ══════════════════════════════════════════════════════════════════════════════

RURAL_IDADE_HOMEM = 60
RURAL_IDADE_MULHER = 55
RURAL_CARENCIA = 180  # meses de atividade rural comprovada

# Idade mínima do trabalhador rural para cômputo (jurisprudência)
RURAL_IDADE_MINIMA_COMPUTO = 12

# ══════════════════════════════════════════════════════════════════════════════
# APOSENTADORIA ESPECIAL
# ══════════════════════════════════════════════════════════════════════════════

# Pontos para aposentadoria especial pós-EC 103 (Art. 21)
ESPECIAL_PONTOS_BASE_25 = 86
ESPECIAL_PONTOS_BASE_20 = 76
ESPECIAL_PONTOS_BASE_15 = 66

# ══════════════════════════════════════════════════════════════════════════════
# FATORES DE CONVERSÃO DE TEMPO ESPECIAL
# ══════════════════════════════════════════════════════════════════════════════

FATOR_CONVERSAO_ESPECIAL = {
    # (base_especial, sexo): fator multiplicador para tempo comum
    (15, "M"): Decimal("2.33"),
    (15, "F"): Decimal("2.00"),
    (20, "M"): Decimal("1.75"),
    (20, "F"): Decimal("1.50"),
    (25, "M"): Decimal("1.40"),
    (25, "F"): Decimal("1.20"),
}

# ══════════════════════════════════════════════════════════════════════════════
# PENSÃO POR MORTE (EC 103/2019)
# ══════════════════════════════════════════════════════════════════════════════

PENSAO_COTA_FAMILIAR = Decimal("0.50")        # 50% base
PENSAO_COTA_POR_DEPENDENTE = Decimal("0.10")  # +10% por dependente

# Duração da pensão por idade do cônjuge na data do óbito
PENSAO_DURACAO_POR_IDADE = [
    # (idade_maxima, duracao_anos)
    (21, 3),
    (27, 6),
    (30, 10),
    (41, 15),
    (44, 20),
    (999, None),  # 45+ → vitalícia (None = sem limite)
]

# ══════════════════════════════════════════════════════════════════════════════
# PERÍODO DE GRAÇA (Art. 15 Lei 8.213/91)
# ══════════════════════════════════════════════════════════════════════════════

PERIODO_GRACA_GERAL = 12                    # meses
PERIODO_GRACA_120_CONTRIBUICOES = 24        # +12 se ≥120 contribuições ininterruptas
PERIODO_GRACA_DESEMPREGO = 36               # +12 se comprovar desemprego
PERIODO_GRACA_FACULTATIVO = 6               # meses
PERIODO_GRACA_MILITAR = 3                   # meses após licenciamento
LIMIAR_CONTRIBUICOES_ININTERRUPTAS = 120    # para estender o período de graça

# ══════════════════════════════════════════════════════════════════════════════
# ANÁLISE CNIS — LIMIARES E GRAVIDADES
# ══════════════════════════════════════════════════════════════════════════════

# Lacunas contributivas
LACUNA_LIMIAR_DIAS = 31               # Até 31 dias não é considerada lacuna
LACUNA_MESES_BAIXA = 3               # Até 3 meses: gravidade BAIXA
LACUNA_MESES_MEDIA = 12              # Até 12 meses: gravidade MÉDIA
LACUNA_MESES_ALTA = 24               # Até 24 meses: gravidade ALTA
                                      # Acima de 24 meses: CRÍTICA

# Margem para remuneração proporcional
MARGEM_PROPORCIONAL_SM = Decimal("0.95")  # 95% do SM (5% de margem)

# ══════════════════════════════════════════════════════════════════════════════
# DIVISOR MÍNIMO (Art. 26 EC 103/2019)
# ══════════════════════════════════════════════════════════════════════════════

DIVISOR_MINIMO = 108  # meses — REGRA CAL-02

# ══════════════════════════════════════════════════════════════════════════════
# EXPECTATIVA DE SOBREVIDA PADRÃO (referência IBGE)
# ══════════════════════════════════════════════════════════════════════════════

EXPECTATIVA_VIDA_REFERENCIA = 84  # anos — usado para cálculo de ROI

# ══════════════════════════════════════════════════════════════════════════════
# FATOR PREVIDENCIÁRIO
# ══════════════════════════════════════════════════════════════════════════════

FATOR_ALIQUOTA = Decimal("0.31")  # Alíquota de contribuição (constante na fórmula)

# ══════════════════════════════════════════════════════════════════════════════
# SISTEMA
# ══════════════════════════════════════════════════════════════════════════════

VERSAO_SISTEMA = "1.0.0"
NOME_ESCRITORIO = "Tatiana Sampaio Advocacia e Consultoria Jurídica"
OAB_ADVOGADA = "OAB/ES 12.297"
NOME_ADVOGADA = "Dra. Tatiana Sampaio"
