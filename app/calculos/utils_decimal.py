"""
Utilitários para cálculos monetários com precisão financeira.

REGRA SYS-01 (TRAVA ABSOLUTA): Nunca usar float para valores monetários.
Todos os valores monetários devem usar Decimal com precisão 10 e ROUND_HALF_UP.
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP, InvalidOperation
from typing import Union

# Configuração global do contexto Decimal
getcontext().prec = 10
getcontext().rounding = ROUND_HALF_UP

# Constantes Decimal reutilizáveis
ZERO = Decimal("0")
UM = Decimal("1")
CEM = Decimal("100")
DOIS = Decimal("2")
DOZE = Decimal("12")

# Precisão para valores em reais (2 casas decimais)
PRECISAO_BRL = Decimal("0.01")

# Precisão para percentuais (4 casas decimais)
PRECISAO_PERCENTUAL = Decimal("0.0001")

# Precisão para fator previdenciário (6 casas decimais)
PRECISAO_FATOR = Decimal("0.000001")


def to_decimal(valor: Union[str, int, float, Decimal, None]) -> Decimal:
    """
    Converte qualquer valor numérico para Decimal de forma segura.

    Aceita str, int, float e Decimal. Para float, converte via str
    para evitar imprecisão de ponto flutuante.

    Raises:
        ValueError: Se o valor não puder ser convertido.
        TypeError: Se o tipo não for suportado.
    """
    if valor is None:
        return ZERO

    if isinstance(valor, Decimal):
        return valor

    if isinstance(valor, int):
        return Decimal(valor)

    if isinstance(valor, float):
        # Converter float via string para evitar imprecisão
        # Ex: Decimal(0.1) = 0.10000000000000000555... mas Decimal("0.1") = 0.1
        return Decimal(str(valor))

    if isinstance(valor, str):
        # Tratar formato brasileiro (1.234,56 → 1234.56)
        valor_limpo = valor.strip()
        valor_limpo = valor_limpo.replace("R$", "").strip()
        valor_limpo = valor_limpo.replace(" ", "")

        # Detectar formato brasileiro: ponto como milhar, vírgula como decimal
        if "," in valor_limpo:
            # Remover pontos de milhar e trocar vírgula por ponto
            valor_limpo = valor_limpo.replace(".", "").replace(",", ".")

        try:
            return Decimal(valor_limpo)
        except InvalidOperation:
            raise ValueError(f"Não foi possível converter '{valor}' para Decimal")

    raise TypeError(f"Tipo {type(valor).__name__} não suportado para conversão Decimal")


def formatar_brl(valor: Decimal) -> str:
    """
    Formata um Decimal como valor monetário brasileiro.
    Ex: Decimal("1518.00") → "R$ 1.518,00"
    """
    valor_arredondado = valor.quantize(PRECISAO_BRL)
    sinal = "-" if valor_arredondado < ZERO else ""
    valor_abs = abs(valor_arredondado)

    parte_inteira = int(valor_abs)
    parte_decimal = int((valor_abs - parte_inteira) * CEM)

    # Formatar com ponto como separador de milhar
    inteiro_str = f"{parte_inteira:,}".replace(",", ".")

    return f"{sinal}R$ {inteiro_str},{parte_decimal:02d}"


def arredondar_brl(valor: Decimal) -> Decimal:
    """Arredonda para 2 casas decimais (padrão INSS)."""
    return valor.quantize(PRECISAO_BRL)


def arredondar_percentual(valor: Decimal) -> Decimal:
    """Arredonda para 4 casas decimais (coeficientes e percentuais)."""
    return valor.quantize(PRECISAO_PERCENTUAL)


def arredondar_fator(valor: Decimal) -> Decimal:
    """Arredonda para 6 casas decimais (fator previdenciário)."""
    return valor.quantize(PRECISAO_FATOR)


def percentual(valor: Decimal, pct: Decimal) -> Decimal:
    """
    Calcula percentual de um valor.
    Ex: percentual(Decimal("1518"), Decimal("60")) → Decimal("910.80")
    """
    return arredondar_brl(valor * pct / CEM)


def max_decimal(*valores: Decimal) -> Decimal:
    """Retorna o maior entre os valores Decimal fornecidos."""
    return max(valores)


def min_decimal(*valores: Decimal) -> Decimal:
    """Retorna o menor entre os valores Decimal fornecidos."""
    return min(valores)


def soma_decimais(valores: list[Decimal]) -> Decimal:
    """Soma uma lista de Decimais com precisão."""
    resultado = ZERO
    for v in valores:
        resultado += v
    return resultado


def media_decimais(valores: list[Decimal]) -> Decimal:
    """
    Calcula a média aritmética simples de uma lista de Decimais.
    Retorna ZERO se a lista estiver vazia.
    """
    if not valores:
        return ZERO
    return soma_decimais(valores) / Decimal(len(valores))
