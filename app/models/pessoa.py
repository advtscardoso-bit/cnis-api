"""
Modelo Pydantic para dados pessoais do segurado.
"""

from datetime import date
from enum import Enum
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator
import pendulum


class Sexo(str, Enum):
    MASCULINO = "M"
    FEMININO = "F"


class Pessoa(BaseModel):
    """Dados pessoais do segurado extraídos do CNIS."""

    cpf: str = Field(..., description="CPF do segurado (apenas dígitos, 11 caracteres)")
    nome: str = Field(..., min_length=2, max_length=200, description="Nome completo")
    data_nascimento: date = Field(..., description="Data de nascimento")
    sexo: Sexo = Field(..., description="Sexo biológico (M/F) — determina todas as regras")
    nit: Optional[str] = Field(None, description="NIT/PIS/PASEP principal")
    nits_adicionais: list[str] = Field(default_factory=list, description="NITs adicionais encontrados (duplicados)")
    nome_mae: Optional[str] = Field(None, description="Nome da mãe (para conferência)")
    data_emissao_cnis: Optional[date] = Field(None, description="Data de emissão do extrato CNIS")

    @field_validator("cpf")
    @classmethod
    def validar_cpf(cls, v: str) -> str:
        """Valida CPF brasileiro (11 dígitos + dígitos verificadores)."""
        # Limpar caracteres não numéricos
        cpf_limpo = "".join(c for c in v if c.isdigit())

        if len(cpf_limpo) != 11:
            raise ValueError(f"CPF deve ter 11 dígitos, recebeu {len(cpf_limpo)}")

        # Rejeitar CPFs com todos os dígitos iguais
        if len(set(cpf_limpo)) == 1:
            raise ValueError("CPF inválido (todos os dígitos iguais)")

        # Validar dígitos verificadores
        for i in range(9, 11):
            soma = sum(int(cpf_limpo[j]) * ((i + 1) - j) for j in range(i))
            resto = (soma * 10) % 11
            if resto == 10:
                resto = 0
            if resto != int(cpf_limpo[i]):
                raise ValueError("CPF inválido (dígito verificador incorreto)")

        return cpf_limpo

    @field_validator("data_nascimento")
    @classmethod
    def validar_data_nascimento(cls, v: date) -> date:
        """Data de nascimento deve ser no passado e razoável."""
        hoje = date.today()
        if v >= hoje:
            raise ValueError("Data de nascimento deve ser anterior a hoje")
        idade = (hoje - v).days / 365.25
        if idade > 120:
            raise ValueError("Data de nascimento resultaria em idade > 120 anos")
        if idade < 14:
            raise ValueError("Segurado deve ter pelo menos 14 anos (idade mínima para filiação)")
        return v

    @field_validator("nit")
    @classmethod
    def validar_nit(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        nit_limpo = "".join(c for c in v if c.isdigit())
        if len(nit_limpo) != 11:
            raise ValueError(f"NIT deve ter 11 dígitos, recebeu {len(nit_limpo)}")
        return nit_limpo

    def idade_em(self, data_referencia: date) -> "IdadeDetalhada":
        """Calcula idade detalhada em uma data de referência."""
        dt_nasc = pendulum.instance(
            pendulum.datetime(self.data_nascimento.year, self.data_nascimento.month, self.data_nascimento.day)
        )
        dt_ref = pendulum.instance(
            pendulum.datetime(data_referencia.year, data_referencia.month, data_referencia.day)
        )
        diff = dt_ref.diff(dt_nasc)
        return IdadeDetalhada(anos=diff.years, meses=diff.months, dias=diff.remaining_days)

    def idade_atual(self) -> "IdadeDetalhada":
        """Calcula idade atual."""
        return self.idade_em(date.today())

    @property
    def tem_nits_duplicados(self) -> bool:
        """Verifica se há NITs duplicados (necessidade de unificação)."""
        return len(self.nits_adicionais) > 0

    @property
    def primeiro_nome(self) -> str:
        """Retorna o primeiro nome do segurado."""
        return self.nome.split()[0].title()

    @property
    def pronome_tratamento(self) -> str:
        """Retorna Sr. ou Sra. conforme o sexo."""
        return "Sra." if self.sexo == Sexo.FEMININO else "Sr."


class IdadeDetalhada(BaseModel):
    """Idade em anos, meses e dias."""
    anos: int = Field(..., ge=0)
    meses: int = Field(..., ge=0, lt=12)
    dias: int = Field(..., ge=0, lt=31)

    def __str__(self) -> str:
        partes = []
        if self.anos > 0:
            partes.append(f"{self.anos} ano{'s' if self.anos != 1 else ''}")
        if self.meses > 0:
            partes.append(f"{self.meses} {'meses' if self.meses != 1 else 'mês'}")
        if self.dias > 0:
            partes.append(f"{self.dias} dia{'s' if self.dias != 1 else ''}")
        return ", ".join(partes) if partes else "0 dias"

    @property
    def total_dias(self) -> int:
        """Estimativa em dias totais (para comparações)."""
        return self.anos * 365 + self.meses * 30 + self.dias
