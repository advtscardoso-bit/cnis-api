"""
Modelo Pydantic para contribuições previdenciárias (remunerações do CNIS).
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.calculos.utils_decimal import ZERO


class TipoContribuicao(str, Enum):
    """Origem da contribuição."""
    EMPREGADOR = "EMPREGADOR"           # Descontada pelo empregador (CLT)
    DAS_MEI = "DAS_MEI"                 # Guia DAS do MEI (5% SM)
    GPS_CI = "GPS_CI"                   # GPS do contribuinte individual (20%)
    GPS_CI_PJ = "GPS_CI_PJ"            # Retida pela PJ (11%)
    GPS_FACULTATIVO = "GPS_FAC"         # GPS do facultativo
    GPS_COMPLEMENTACAO = "GPS_COMPL"    # Complementação MEI 5%→20% (código 1910)
    RURAL_SEGURADO_ESPECIAL = "RURAL"   # Segurado especial (sem recolhimento)
    BENEFICIO = "BENEFICIO"             # Período em gozo de benefício (B31/B91)
    SALARIO_MATERNIDADE = "SAL_MAT"     # Salário-maternidade (conta na média)
    MILITAR = "MILITAR"                 # Serviço militar (sem recolhimento)
    DESCONHECIDO = "DESCONHECIDO"


class Contribuicao(BaseModel):
    """
    Uma contribuição previdenciária mensal.

    Cada registro representa um mês de contribuição com seu valor (salário de
    contribuição), tipo, e flags que afetam se ela conta para tempo/carência/média.
    """

    # Identificação
    competencia: str = Field(
        ...,
        pattern=r"^\d{2}/\d{4}$",
        description="Competência no formato MM/AAAA"
    )
    vinculo_sequencia: Optional[int] = Field(None, description="Referência ao vínculo de origem")

    # Valores
    valor_original: Decimal = Field(..., ge=0, description="Valor original do SC na competência")
    valor_atualizado: Optional[Decimal] = Field(None, ge=0, description="Valor atualizado pelo INPC")

    # Classificação
    tipo: TipoContribuicao = Field(TipoContribuicao.DESCONHECIDO)

    # Indicadores do CNIS nesta competência
    indicadores: list[str] = Field(default_factory=list)

    # Flags calculados pelo sistema
    abaixo_minimo: bool = Field(False, description="SC < salário mínimo da competência")
    bloqueada: bool = Field(False, description="Contribuição bloqueada (PREM-BLOQ-EC103)")
    extemporanea: bool = Field(False, description="Paga em atraso (PREM-EXT)")
    complementada: bool = Field(False, description="MEI já complementou para 20%")

    # Teto e piso aplicados
    teto_competencia: Optional[Decimal] = Field(None, ge=0, description="Teto RGPS vigente na competência")
    sm_competencia: Optional[Decimal] = Field(None, ge=0, description="SM vigente na competência")

    @field_validator("competencia")
    @classmethod
    def validar_competencia(cls, v: str) -> str:
        """Valida formato MM/AAAA e verifica se mês é válido."""
        mes, ano = v.split("/")
        mes_int = int(mes)
        ano_int = int(ano)
        if mes_int < 1 or mes_int > 12:
            raise ValueError(f"Mês inválido: {mes_int}")
        if ano_int < 1900 or ano_int > 2100:
            raise ValueError(f"Ano fora do range válido: {ano_int}")
        return v

    @property
    def mes(self) -> int:
        """Retorna o mês da competência."""
        return int(self.competencia.split("/")[0])

    @property
    def ano(self) -> int:
        """Retorna o ano da competência."""
        return int(self.competencia.split("/")[1])

    @property
    def data_competencia(self) -> date:
        """Retorna o primeiro dia do mês da competência como date."""
        return date(self.ano, self.mes, 1)

    @property
    def competencia_chave(self) -> tuple[int, int]:
        """Retorna (ano, mes) como chave para dicionários e comparações."""
        return (self.ano, self.mes)

    @property
    def valor_para_media(self) -> Decimal:
        """
        Valor que entra no cálculo da média salarial.
        Usa o valor atualizado se disponível, senão o original.
        Retorna ZERO se bloqueada ou abaixo do mínimo sem complementação.
        """
        if self.bloqueada:
            return ZERO
        if self.abaixo_minimo and not self.complementada:
            return ZERO
        return self.valor_atualizado if self.valor_atualizado is not None else self.valor_original

    @property
    def conta_tempo(self) -> bool:
        """
        REGRA CONTRIB-01: Contribuição abaixo do SM NÃO conta para tempo.
        Bloqueada também não conta.
        """
        if self.bloqueada:
            return False
        if self.abaixo_minimo and not self.complementada:
            return False
        return True

    @property
    def conta_carencia(self) -> bool:
        """
        Conta para carência? Exclui:
        - Abaixo do mínimo (REGRA CONTRIB-01)
        - Bloqueada
        - Extemporânea/em atraso (REGRA MEI-04)
        - Benefício por incapacidade (REGRA CONTRIB-02)
        """
        if not self.conta_tempo:
            return False
        if self.extemporanea:
            return False
        if self.tipo == TipoContribuicao.BENEFICIO:
            return False
        return True

    @property
    def e_pos_real(self) -> bool:
        """Competência a partir de 07/1994 (Plano Real — início do cálculo da média)."""
        return (self.ano > 1994) or (self.ano == 1994 and self.mes >= 7)

    @property
    def e_mei(self) -> bool:
        return self.tipo == TipoContribuicao.DAS_MEI

    @property
    def e_salario_maternidade(self) -> bool:
        """REGRA CONTRIB-03: Salário-maternidade entra na média."""
        return self.tipo == TipoContribuicao.SALARIO_MATERNIDADE

    def tem_indicador(self, codigo: str) -> bool:
        return codigo in self.indicadores


class ResumoContribuicoes(BaseModel):
    """Resumo estatístico das contribuições de um segurado."""
    total_contribuicoes: int = 0
    contribuicoes_validas_tempo: int = 0
    contribuicoes_validas_carencia: int = 0
    contribuicoes_pos_real: int = 0       # A partir de 07/1994
    contribuicoes_abaixo_minimo: int = 0
    contribuicoes_bloqueadas: int = 0
    contribuicoes_extemporaneas: int = 0
    meses_mei: int = 0
    meses_clt: int = 0
    meses_beneficio: int = 0
    primeiro_mes: Optional[str] = None     # MM/AAAA mais antigo
    ultimo_mes: Optional[str] = None       # MM/AAAA mais recente
