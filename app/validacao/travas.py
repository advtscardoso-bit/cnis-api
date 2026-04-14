"""
Travas anti-erro do sistema de planejamento previdenciário.

24 regras de negócio (16 BLOQUEANTES + 7 ALTA + 1 MÉDIA).
As travas BLOQUEANTES impedem o cálculo se violadas.
As travas ALTA emitem alerta com destaque mas não bloqueiam.

Referência: Seção 31 da especificação técnica.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.vinculo import Vinculo, TipoVinculo
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.pessoa import Sexo
from app.calculos.utils_decimal import ZERO


class TravaVioladaError(Exception):
    """Exceção para travas BLOQUEANTES violadas. Impede o cálculo."""

    def __init__(self, codigo: str, mensagem: str, severidade: str = "BLOQUEANTE"):
        self.codigo = codigo
        self.mensagem = mensagem
        self.severidade = severidade
        super().__init__(f"[{codigo}] {mensagem}")


class AlertaTrava:
    """Alerta para travas de severidade ALTA (não bloqueiam mas destacam)."""

    def __init__(self, codigo: str, mensagem: str, severidade: str = "ALTA"):
        self.codigo = codigo
        self.mensagem = mensagem
        self.severidade = severidade

    def __repr__(self) -> str:
        return f"AlertaTrava({self.codigo}: {self.mensagem})"


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DO MEI
# ══════════════════════════════════════════════════════════════════════════════


def trava_mei_01_contribuicao_sobre_sm(
    contribuicoes_mei: list[Contribuicao],
    salarios_minimos: dict[str, Decimal],
) -> list[AlertaTrava]:
    """
    REGRA MEI-01 (BLOQUEANTE): MEI contribui SEMPRE e SOMENTE sobre 1 SM.
    Se qualquer contribuição MEI tem valor > SM da competência, é erro.
    """
    alertas = []
    for c in contribuicoes_mei:
        if c.tipo != TipoContribuicao.DAS_MEI:
            continue
        sm = salarios_minimos.get(c.competencia)
        if sm is None:
            continue
        # Tolerância de R$ 1,00 para arredondamentos
        if c.valor_original > sm + Decimal("1.00"):
            raise TravaVioladaError(
                "MEI-01",
                f"Contribuição MEI na competência {c.competencia} tem valor "
                f"R$ {c.valor_original} acima do SM vigente R$ {sm}. "
                f"MEI só contribui sobre 1 salário mínimo."
            )
    return alertas


def trava_mei_02_complementacao_sobre_sm(
    valor_complementacao: Decimal,
    salario_minimo: Decimal,
) -> None:
    """
    REGRA MEI-02 (BLOQUEANTE): Complementação MEI é sobre SM, obrigatoriamente.
    O sistema não pode calcular complementação sobre valor > SM.
    """
    esperado = salario_minimo * Decimal("0.15")
    # Tolerância de R$ 1,00
    if valor_complementacao > esperado + Decimal("1.00"):
        raise TravaVioladaError(
            "MEI-02",
            f"Complementação MEI calculada em R$ {valor_complementacao}, "
            f"mas o máximo é 15% do SM = R$ {esperado}. "
            f"MEI NÃO pode complementar sobre valor superior ao SM."
        )


def trava_mei_03_regras_acessiveis(
    tipo_vinculo: TipoVinculo,
    regra_simulada: str,
    meses_complementados: int,
    total_meses_mei: int,
) -> Optional[AlertaTrava]:
    """
    REGRA MEI-03 (BLOQUEANTE): MEI 5% SÓ acessa aposentadoria por idade.
    Para acessar outras regras, TODOS os meses MEI usados devem ser complementados.
    """
    if tipo_vinculo != TipoVinculo.MEI:
        return None

    regras_bloqueadas = {
        "PONTOS", "IDADE_PROGRESSIVA", "PEDAGIO_50", "PEDAGIO_100",
        "DIREITO_ADQUIRIDO_TC", "PROGRAMADA",
    }

    if regra_simulada in regras_bloqueadas:
        if meses_complementados < total_meses_mei:
            raise TravaVioladaError(
                "MEI-03",
                f"MEI com alíquota de 5% NÃO pode acessar a regra {regra_simulada}. "
                f"Necessário complementar {total_meses_mei - meses_complementados} meses "
                f"(de {total_meses_mei} meses MEI, apenas {meses_complementados} complementados). "
                f"Art. 21, §2º da Lei 8.212/91."
            )
    return None


def trava_mei_04_das_em_atraso(contribuicao: Contribuicao) -> Optional[AlertaTrava]:
    """
    REGRA MEI-04 (ALTA): DAS MEI pago em atraso conta para tempo mas NÃO para carência.
    """
    if contribuicao.tipo == TipoContribuicao.DAS_MEI and contribuicao.extemporanea:
        return AlertaTrava(
            "MEI-04",
            f"DAS MEI da competência {contribuicao.competencia} pago em atraso (PREM-EXT). "
            f"Conta para tempo de contribuição mas NÃO para carência."
        )
    return None


def trava_mei_05_concomitancia_clt(
    salario_clt: Decimal,
    salario_minimo: Decimal,
    competencia: str,
) -> Optional[AlertaTrava]:
    """
    REGRA MEI-05 (ALTA): MEI + CLT concomitante — MEI não soma na média se CLT >= SM.
    """
    if salario_clt >= salario_minimo:
        return AlertaTrava(
            "MEI-05",
            f"Na competência {competencia}, o salário CLT (R$ {salario_clt}) "
            f"já é >= SM (R$ {salario_minimo}). "
            f"A contribuição MEI concomitante tem impacto limitado na média."
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DO CLT
# ══════════════════════════════════════════════════════════════════════════════


def trava_clt_01_nao_pode_ser_facultativo(
    vinculos_ativos_na_competencia: list[Vinculo],
    competencia: str,
) -> None:
    """
    REGRA CLT-01 (BLOQUEANTE): CLT não pode contribuir como facultativo.
    """
    tem_clt = any(v.e_clt for v in vinculos_ativos_na_competencia)
    tem_facultativo = any(v.e_facultativo for v in vinculos_ativos_na_competencia)

    if tem_clt and tem_facultativo:
        raise TravaVioladaError(
            "CLT-01",
            f"Na competência {competencia}, há vínculo CLT e contribuição facultativa "
            f"simultâneos. CLT é segurado OBRIGATÓRIO e NÃO pode ser facultativo ao "
            f"mesmo tempo. A contribuição facultativa é indevida."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE CONTRIBUIÇÃO E CARÊNCIA
# ══════════════════════════════════════════════════════════════════════════════


def trava_contrib_01_abaixo_minimo(
    contribuicao: Contribuicao,
    salario_minimo_competencia: Decimal,
) -> Optional[AlertaTrava]:
    """
    REGRA CONTRIB-01 (BLOQUEANTE no cômputo): Contribuição abaixo do SM
    NÃO conta para carência NEM tempo, até ser complementada/agrupada.
    """
    if contribuicao.valor_original < salario_minimo_competencia and contribuicao.valor_original > ZERO:
        if not contribuicao.complementada:
            return AlertaTrava(
                "CONTRIB-01",
                f"Competência {contribuicao.competencia}: SC de R$ {contribuicao.valor_original} "
                f"está abaixo do SM vigente R$ {salario_minimo_competencia}. "
                f"NÃO conta para tempo nem carência até complementação.",
                severidade="BLOQUEANTE"
            )
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE CÁLCULO DA MÉDIA
# ══════════════════════════════════════════════════════════════════════════════


def trava_cal_01_teto_antes_de_atualizar(
    sc_original: Decimal,
    teto_competencia: Decimal,
    fator_inpc: Decimal,
    competencia: str,
) -> Decimal:
    """
    REGRA CAL-01 (BLOQUEANTE): Limitar ao teto ANTES de atualizar monetariamente.
    CORRETO:  MIN(SC, teto_competência) × fator_INPC
    ERRADO:   SC × fator_INPC, depois limitar ao teto atual.
    Retorna o SC atualizado corretamente.
    """
    sc_limitado = min(sc_original, teto_competencia)
    sc_atualizado = sc_limitado * fator_inpc
    return sc_atualizado


def trava_cal_02_divisor_minimo(
    num_contribuicoes: int,
    soma_sc: Decimal,
) -> Decimal:
    """
    REGRA CAL-02 (BLOQUEANTE): Divisor mínimo de 108 meses.
    Média = soma / MAX(num_contribuições, 108).
    """
    from app.config.constantes import DIVISOR_MINIMO
    divisor = max(num_contribuicoes, DIVISOR_MINIMO)
    if divisor == 0:
        return ZERO
    return soma_sc / Decimal(divisor)


def trava_cal_03_descarte_nao_reduz_tc(
    tc_apos_descarte_meses: int,
    tc_minimo_regra_meses: int,
    regra: str,
) -> None:
    """
    REGRA CAL-03 (BLOQUEANTE): Descarte não pode reduzir TC abaixo do mínimo da regra.
    """
    if tc_apos_descarte_meses < tc_minimo_regra_meses:
        raise TravaVioladaError(
            "CAL-03",
            f"Descarte de contribuições reduziria o TC para {tc_apos_descarte_meses} meses, "
            f"abaixo do mínimo exigido pela regra {regra} ({tc_minimo_regra_meses} meses). "
            f"Descarte INVÁLIDO para esta regra."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE CONCOMITÂNCIA
# ══════════════════════════════════════════════════════════════════════════════


def trava_conc_01_mei_facultativo_proibido(
    vinculos_na_competencia: list[Vinculo],
    competencia: str,
) -> None:
    """
    REGRA CONC-01 (BLOQUEANTE): MEI + Facultativo simultâneo é PROIBIDO.
    """
    tem_mei = any(v.e_mei for v in vinculos_na_competencia)
    tem_facultativo = any(v.e_facultativo for v in vinculos_na_competencia)

    if tem_mei and tem_facultativo:
        raise TravaVioladaError(
            "CONC-01",
            f"Na competência {competencia}, há contribuição MEI e facultativa simultâneas. "
            f"MEI é segurado OBRIGATÓRIO e NÃO pode ser facultativo ao mesmo tempo. "
            f"Uma das contribuições é indevida."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE SEXO E CATEGORIA
# ══════════════════════════════════════════════════════════════════════════════


def trava_sexo_01_parametros_consistentes(
    sexo: Sexo,
    tc_minimo_usado: int,
    idade_minima_usada: int,
    regra: str,
) -> None:
    """
    REGRA SEXO-01 (BLOQUEANTE): Sexo determina TODOS os parâmetros.
    Verificar que os parâmetros usados são consistentes com o sexo.
    """
    from app.config.constantes import (
        TC_MINIMO_TRANSICAO_HOMEM, TC_MINIMO_TRANSICAO_MULHER,
        IDADE_MINIMA_HOMEM, IDADE_MINIMA_MULHER,
    )

    if sexo == Sexo.MASCULINO:
        if tc_minimo_usado == TC_MINIMO_TRANSICAO_MULHER and regra != "IDADE":
            raise TravaVioladaError(
                "SEXO-01",
                f"Parâmetro feminino (TC mínimo {tc_minimo_usado} anos) usado "
                f"para segurado MASCULINO na regra {regra}."
            )
    elif sexo == Sexo.FEMININO:
        if tc_minimo_usado == TC_MINIMO_TRANSICAO_HOMEM and regra != "IDADE":
            raise TravaVioladaError(
                "SEXO-01",
                f"Parâmetro masculino (TC mínimo {tc_minimo_usado} anos) usado "
                f"para segurada FEMININA na regra {regra}."
            )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE TEMPO ESPECIAL
# ══════════════════════════════════════════════════════════════════════════════


def trava_esp_01_conversao_vedada_pos_reforma(
    data_periodo_especial_fim: date,
) -> None:
    """
    REGRA ESP-01 (BLOQUEANTE): Conversão de tempo especial em comum
    VEDADA para períodos APÓS 13/11/2019.
    """
    from app.config.constantes import DATA_VEDA_CONVERSAO_ESPECIAL
    if data_periodo_especial_fim > DATA_VEDA_CONVERSAO_ESPECIAL:
        raise TravaVioladaError(
            "ESP-01",
            f"Tentativa de converter tempo especial em comum para período "
            f"posterior a {DATA_VEDA_CONVERSAO_ESPECIAL.strftime('%d/%m/%Y')}. "
            f"EC 103/2019 veda a conversão após a reforma."
        )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DE CTC E RPPS
# ══════════════════════════════════════════════════════════════════════════════


def trava_ctc_01_exige_exoneracao(
    vinculo_rpps: Vinculo,
    confirmacao_exoneracao: bool,
) -> None:
    """
    REGRA CTC-01 (BLOQUEANTE): CTC SÓ pode ser solicitada APÓS exoneração.
    Servidor ativo NÃO pode emitir CTC em hipótese nenhuma.
    """
    if vinculo_rpps.e_servidor_publico and vinculo_rpps.em_aberto:
        if not confirmacao_exoneracao:
            raise TravaVioladaError(
                "CTC-01",
                f"Vínculo com servidor público ({vinculo_rpps.empregador}) está em aberto. "
                f"CTC só pode ser solicitada APÓS exoneração do cargo público. "
                f"O sistema NÃO pode sugerir CTC para servidor ativo."
            )


# ══════════════════════════════════════════════════════════════════════════════
# TRAVAS DO SISTEMA
# ══════════════════════════════════════════════════════════════════════════════


def trava_sys_02_indicador_desconhecido(
    codigo_indicador: str,
    indicadores_conhecidos: set[str],
) -> Optional[AlertaTrava]:
    """
    REGRA SYS-02 (BLOQUEANTE): Indicador CNIS desconhecido — NUNCA inventar.
    Emitir WARNING e bloquear cômputo do período até revisão humana.
    """
    if codigo_indicador not in indicadores_conhecidos:
        return AlertaTrava(
            "SYS-02",
            f"Indicador '{codigo_indicador}' NÃO reconhecido pelo sistema. "
            f"Encaminhar para análise manual. O sistema NÃO pode inventar "
            f"significado nem ignorar silenciosamente.",
            severidade="BLOQUEANTE"
        )
    return None


def trava_sys_04_sm_teto_por_competencia(
    competencia: str,
    sm_usado: Decimal,
    teto_usado: Decimal,
    tabela_sm: dict[str, Decimal],
    tabela_tetos: dict[str, Decimal],
) -> None:
    """
    REGRA SYS-04 (BLOQUEANTE): SM e teto devem ser os vigentes na competência,
    NÃO os valores atuais.
    """
    sm_correto = tabela_sm.get(competencia)
    teto_correto = tabela_tetos.get(competencia)

    if sm_correto is not None and sm_usado != sm_correto:
        raise TravaVioladaError(
            "SYS-04",
            f"SM usado na competência {competencia} é R$ {sm_usado}, "
            f"mas o SM vigente na época era R$ {sm_correto}. "
            f"Usar SEMPRE o valor vigente na competência."
        )
