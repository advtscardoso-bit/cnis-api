"""
Modelo Pydantic para benefícios previdenciários encontrados no CNIS.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


class EspecieBeneficio(str, Enum):
    """Espécies de benefícios previdenciários do INSS."""
    # Aposentadorias
    B41 = "B41"   # Aposentadoria por idade
    B42 = "B42"   # Aposentadoria por tempo de contribuição
    B46 = "B46"   # Aposentadoria especial
    B57 = "B57"   # Aposentadoria de professor
    B92_APOS = "B92_APOS"  # Aposentadoria por invalidez acidentária

    # Incapacidade
    B31 = "B31"   # Auxílio-doença previdenciário
    B32 = "B32"   # Aposentadoria por invalidez previdenciária
    B91 = "B91"   # Auxílio-doença acidentário
    B92 = "B92"   # Aposentadoria por invalidez acidentária
    B94 = "B94"   # Auxílio-acidente previdenciário
    B87 = "B87"   # Auxílio-acidente por acidente de trabalho
    B36 = "B36"   # Auxílio-acidente (novo código)

    # Pensão
    B21 = "B21"   # Pensão por morte previdenciária
    B93 = "B93"   # Pensão por morte acidentária

    # Outros
    B80 = "B80"   # Salário-maternidade
    B25 = "B25"   # Auxílio-reclusão
    B88 = "B88"   # BPC/LOAS idoso
    B87_LOAS = "B87_LOAS"  # BPC/LOAS deficiente

    OUTRO = "OUTRO"


# Benefícios que indicam incapacidade (gatilho para módulo PcD)
BENEFICIOS_INCAPACIDADE = {
    EspecieBeneficio.B31,
    EspecieBeneficio.B32,
    EspecieBeneficio.B91,
    EspecieBeneficio.B92,
    EspecieBeneficio.B94,
    EspecieBeneficio.B87,
}

# Benefícios que contam como tempo de contribuição (intercalados)
BENEFICIOS_CONTAM_TEMPO = {
    EspecieBeneficio.B31,
    EspecieBeneficio.B91,
}


class Beneficio(BaseModel):
    """
    Um benefício previdenciário registrado no CNIS.

    Pode ser aposentadoria, auxílio-doença, pensão por morte, etc.
    Benefícios por incapacidade (B31, B91) são gatilho para o módulo PcD.
    """

    especie: EspecieBeneficio = Field(..., description="Espécie do benefício")
    nb: Optional[str] = Field(None, description="Número do benefício")
    dib: date = Field(..., description="Data de Início do Benefício")
    dcb: Optional[date] = Field(None, description="Data de Cessação do Benefício (None = ativo)")
    valor: Optional[Decimal] = Field(None, ge=0, description="Valor mensal do benefício")
    cid: Optional[str] = Field(None, description="CID da doença/condição (se incapacidade)")
    indicadores: list[str] = Field(default_factory=list)
    observacoes: Optional[str] = Field(None)

    @model_validator(mode="after")
    def validar_datas_beneficio(self):
        if self.dcb is not None and self.dcb < self.dib:
            raise ValueError(
                f"DCB ({self.dcb}) anterior à DIB ({self.dib}) "
                f"no benefício {self.especie.value} NB {self.nb or '?'}"
            )
        return self

    @property
    def ativo(self) -> bool:
        return self.dcb is None

    @property
    def duracao_meses(self) -> int:
        """Duração do benefício em meses (aproximado)."""
        fim = self.dcb or date.today()
        return (fim.year - self.dib.year) * 12 + (fim.month - self.dib.month)

    @property
    def e_incapacidade(self) -> bool:
        """Benefício por incapacidade (gatilho para módulo PcD)."""
        return self.especie in BENEFICIOS_INCAPACIDADE

    @property
    def conta_tempo_contribuicao(self) -> bool:
        """
        REGRA CONTRIB-02: Auxílio-doença intercalado entre períodos de
        atividade conta como TEMPO, mas NÃO como carência.
        """
        return self.especie in BENEFICIOS_CONTAM_TEMPO

    @property
    def e_aposentadoria(self) -> bool:
        return self.especie in (
            EspecieBeneficio.B41,
            EspecieBeneficio.B42,
            EspecieBeneficio.B46,
            EspecieBeneficio.B57,
            EspecieBeneficio.B32,
            EspecieBeneficio.B92,
        )

    @property
    def e_auxilio_doenca(self) -> bool:
        return self.especie in (EspecieBeneficio.B31, EspecieBeneficio.B91)

    @property
    def e_acidentario(self) -> bool:
        return self.especie in (
            EspecieBeneficio.B91,
            EspecieBeneficio.B92,
            EspecieBeneficio.B87,
            EspecieBeneficio.B93,
        )
