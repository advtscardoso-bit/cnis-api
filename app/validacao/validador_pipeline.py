"""
Orquestrador de validações — roda TODAS as travas antes de permitir cálculos.

O ValidadorPipeline é o guardião do sistema. Ele executa as travas
bloqueantes e coleta alertas antes que qualquer cálculo seja realizado.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.pessoa import Pessoa
from app.models.vinculo import Vinculo, TipoVinculo
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.beneficio import Beneficio
from app.models.indicador import IndicadorCNIS
from app.validacao.travas import (
    TravaVioladaError, AlertaTrava,
    trava_clt_01_nao_pode_ser_facultativo,
    trava_conc_01_mei_facultativo_proibido,
    trava_contrib_01_abaixo_minimo,
    trava_mei_04_das_em_atraso,
    trava_sys_02_indicador_desconhecido,
)
from app.calculos.utils_decimal import ZERO


class ResultadoValidacao:
    """Resultado da execução de todas as travas."""

    def __init__(self):
        self.erros_bloqueantes: list[TravaVioladaError] = []
        self.alertas: list[AlertaTrava] = []
        self.indicadores_desconhecidos: list[str] = []
        self.competencias_abaixo_minimo: list[str] = []
        self.concomitancias_invalidas: list[str] = []

    @property
    def passou(self) -> bool:
        """True se nenhuma trava bloqueante foi violada."""
        return len(self.erros_bloqueantes) == 0

    @property
    def tem_alertas(self) -> bool:
        return len(self.alertas) > 0

    @property
    def total_problemas(self) -> int:
        return len(self.erros_bloqueantes) + len(self.alertas)

    def adicionar_erro(self, erro: TravaVioladaError) -> None:
        self.erros_bloqueantes.append(erro)

    def adicionar_alerta(self, alerta: AlertaTrava) -> None:
        if alerta is not None:
            self.alertas.append(alerta)

    def resumo(self) -> str:
        linhas = []
        if self.erros_bloqueantes:
            linhas.append(f"ERROS BLOQUEANTES ({len(self.erros_bloqueantes)}):")
            for e in self.erros_bloqueantes:
                linhas.append(f"  [{e.codigo}] {e.mensagem}")
        if self.alertas:
            linhas.append(f"ALERTAS ({len(self.alertas)}):")
            for a in self.alertas:
                linhas.append(f"  [{a.codigo}] {a.mensagem}")
        if not linhas:
            linhas.append("Validação OK — nenhum problema encontrado.")
        return "\n".join(linhas)


class ValidadorPipeline:
    """
    Executa todas as travas de validação antes dos cálculos.

    Uso:
        validador = ValidadorPipeline(pessoa, vinculos, contribuicoes, ...)
        resultado = validador.executar()
        if not resultado.passou:
            # Bloquear cálculos — erros críticos encontrados
            raise resultado.erros_bloqueantes[0]
    """

    def __init__(
        self,
        pessoa: Pessoa,
        vinculos: list[Vinculo],
        contribuicoes: list[Contribuicao],
        beneficios: list[Beneficio],
        indicadores: list[IndicadorCNIS],
        tabela_sm: dict[str, Decimal],
        tabela_tetos: dict[str, Decimal],
        indicadores_conhecidos: set[str],
    ):
        self.pessoa = pessoa
        self.vinculos = vinculos
        self.contribuicoes = contribuicoes
        self.beneficios = beneficios
        self.indicadores = indicadores
        self.tabela_sm = tabela_sm
        self.tabela_tetos = tabela_tetos
        self.indicadores_conhecidos = indicadores_conhecidos

    def executar(self) -> ResultadoValidacao:
        """Executa todas as validações e retorna o resultado consolidado."""
        resultado = ResultadoValidacao()

        self._validar_concomitancias(resultado)
        self._validar_contribuicoes(resultado)
        self._validar_indicadores(resultado)

        return resultado

    def _validar_concomitancias(self, resultado: ResultadoValidacao) -> None:
        """Verifica concomitâncias proibidas por competência."""
        # Agrupar vínculos por competência (mês/ano)
        vinculos_por_competencia: dict[str, list[Vinculo]] = {}
        for c in self.contribuicoes:
            if c.competencia not in vinculos_por_competencia:
                vinculos_por_competencia[c.competencia] = []
            # Encontrar o vínculo associado a esta contribuição
            for v in self.vinculos:
                fim = v.data_fim or date.today()
                if v.data_inicio <= c.data_competencia <= fim:
                    if v not in vinculos_por_competencia[c.competencia]:
                        vinculos_por_competencia[c.competencia].append(v)

        for competencia, vinculos in vinculos_por_competencia.items():
            if len(vinculos) < 2:
                continue

            # CONC-01: MEI + Facultativo proibido
            try:
                trava_conc_01_mei_facultativo_proibido(vinculos, competencia)
            except TravaVioladaError as e:
                resultado.adicionar_erro(e)
                resultado.concomitancias_invalidas.append(competencia)

            # CLT-01: CLT + Facultativo proibido
            try:
                trava_clt_01_nao_pode_ser_facultativo(vinculos, competencia)
            except TravaVioladaError as e:
                resultado.adicionar_erro(e)
                resultado.concomitancias_invalidas.append(competencia)

    def _validar_contribuicoes(self, resultado: ResultadoValidacao) -> None:
        """Verifica contribuições com problemas."""
        for c in self.contribuicoes:
            # CONTRIB-01: Abaixo do mínimo
            sm = self.tabela_sm.get(c.competencia)
            if sm is not None:
                alerta = trava_contrib_01_abaixo_minimo(c, sm)
                resultado.adicionar_alerta(alerta)
                if alerta and alerta.severidade == "BLOQUEANTE":
                    resultado.competencias_abaixo_minimo.append(c.competencia)

            # MEI-04: DAS em atraso
            alerta = trava_mei_04_das_em_atraso(c)
            resultado.adicionar_alerta(alerta)

    def _validar_indicadores(self, resultado: ResultadoValidacao) -> None:
        """Verifica indicadores desconhecidos (REGRA SYS-02)."""
        codigos_vistos = set()
        for ind in self.indicadores:
            if ind.codigo in codigos_vistos:
                continue
            codigos_vistos.add(ind.codigo)

            alerta = trava_sys_02_indicador_desconhecido(
                ind.codigo, self.indicadores_conhecidos
            )
            if alerta is not None:
                resultado.adicionar_alerta(alerta)
                resultado.indicadores_desconhecidos.append(ind.codigo)
