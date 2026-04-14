"""
Classificador de vínculos — classifica cada período do CNIS como
MEI, CLT, Autônomo, Facultativo, Rural, Especial, Servidor ou Militar.

Este é o PONTO MAIS CRÍTICO DO SISTEMA para evitar erros.
A classificação errada de um vínculo (ex: MEI como CLT) invalida
todo o planejamento previdenciário.

Referência: Seção 5.4, Módulo 7 da especificação técnica.
"""

from datetime import date
from typing import Optional

from app.models.vinculo import Vinculo, TipoVinculo, AliquotaContribuicao
from app.models.contribuicao import Contribuicao, TipoContribuicao
from app.models.pessoa import Pessoa, Sexo
from app.models.relatorio import PerfilContributivo


# Indicadores CNIS que identificam tipo de vínculo
INDICADORES_MEI = {"IREC-MEI", "MEI"}
INDICADORES_RURAL = {"IREC-LC123", "IREC-INDPEND", "RURAL", "IREC-FBR"}
INDICADORES_RPPS = {"PRPPS"}
INDICADORES_DEFICIENCIA = {"ADEF", "AVRC-DEF"}
INDICADORES_BLOQUEIO_EC103 = {"PREM-BLOQ-EC103"}
INDICADORES_EXTEMPORANEA = {"PREM-EXT"}
INDICADORES_ABAIXO_MINIMO = {"PREC-MENOR-MIN", "PREC-MENORMIN"}

# Palavras-chave no nome do empregador que sugerem tipo
PALAVRAS_RURAL = {"fazenda", "sitio", "sítio", "agropecuaria", "agropecuária", "rural"}
PALAVRAS_DOMESTICO = {"empregador domestico", "empregador doméstico"}
PALAVRAS_ORGAO_PUBLICO = {
    "prefeitura", "governo", "estado de", "municipio de", "município de",
    "secretaria", "ministerio", "ministério", "tribunal", "camara", "câmara",
    "senado", "assembleia", "assembléia",
}


def classificar_vinculo(vinculo: Vinculo) -> Vinculo:
    """
    Classifica o tipo de um vínculo baseado em indicadores, empregador e tipo.
    Retorna o vínculo com o campo `tipo` atualizado.

    Ordem de prioridade:
    1. Indicadores CNIS (mais confiável)
    2. Tipo declarado no CNIS
    3. Nome do empregador (heurística)
    4. Se nenhum match → DESCONHECIDO (requer análise manual)
    """
    # Verificar indicadores primeiro (mais confiável)
    tipo_por_indicador = _classificar_por_indicadores(vinculo)
    if tipo_por_indicador is not None:
        vinculo.tipo = tipo_por_indicador
        vinculo.aliquota = _inferir_aliquota(vinculo.tipo)
        return vinculo

    # Verificar se é benefício
    if vinculo.e_beneficio:
        vinculo.aliquota = AliquotaContribuicao.ZERO
        return vinculo

    # Verificar pelo nome do empregador
    tipo_por_empregador = _classificar_por_empregador(vinculo)
    if tipo_por_empregador is not None:
        vinculo.tipo = tipo_por_empregador
        vinculo.aliquota = _inferir_aliquota(vinculo.tipo)
        return vinculo

    # Se tipo já veio preenchido do parser e não é DESCONHECIDO, manter
    if vinculo.tipo != TipoVinculo.DESCONHECIDO:
        vinculo.aliquota = _inferir_aliquota(vinculo.tipo)
        return vinculo

    return vinculo


def _classificar_por_indicadores(vinculo: Vinculo) -> Optional[TipoVinculo]:
    """Classifica vínculo pelos indicadores CNIS encontrados."""
    indicadores = set(vinculo.indicadores)

    if indicadores & INDICADORES_MEI:
        return TipoVinculo.MEI

    if indicadores & INDICADORES_RPPS:
        return TipoVinculo.SERVIDOR_PUBLICO

    if indicadores & INDICADORES_RURAL:
        return TipoVinculo.RURAL_SEGURADO_ESPECIAL

    return None


def _classificar_por_empregador(vinculo: Vinculo) -> Optional[TipoVinculo]:
    """Classifica vínculo pelo nome do empregador (heurística)."""
    if not vinculo.empregador:
        return None

    empregador_lower = vinculo.empregador.lower()

    # Empregador doméstico
    for palavra in PALAVRAS_DOMESTICO:
        if palavra in empregador_lower:
            return TipoVinculo.EMPREGADO_DOMESTICO

    # Órgão público
    for palavra in PALAVRAS_ORGAO_PUBLICO:
        if palavra in empregador_lower:
            return TipoVinculo.SERVIDOR_PUBLICO

    # Rural
    for palavra in PALAVRAS_RURAL:
        if palavra in empregador_lower:
            return TipoVinculo.RURAL_EMPREGADO

    return None


def _inferir_aliquota(tipo: TipoVinculo) -> AliquotaContribuicao:
    """Infere a alíquota de contribuição pelo tipo de vínculo."""
    mapa = {
        TipoVinculo.MEI: AliquotaContribuicao.CINCO_PORCENTO,
        TipoVinculo.CLT: AliquotaContribuicao.VARIAVEL_CLT,
        TipoVinculo.CONTRIBUINTE_INDIVIDUAL: AliquotaContribuicao.VINTE_PORCENTO,
        TipoVinculo.CI_PRESTADOR_PJ: AliquotaContribuicao.ONZE_PORCENTO,
        TipoVinculo.FACULTATIVO: AliquotaContribuicao.VINTE_PORCENTO,
        TipoVinculo.FACULTATIVO_BAIXA_RENDA: AliquotaContribuicao.CINCO_PORCENTO,
        TipoVinculo.EMPREGADO_DOMESTICO: AliquotaContribuicao.VARIAVEL_CLT,
        TipoVinculo.RURAL_SEGURADO_ESPECIAL: AliquotaContribuicao.ZERO,
        TipoVinculo.RURAL_EMPREGADO: AliquotaContribuicao.VARIAVEL_CLT,
        TipoVinculo.SERVIDOR_PUBLICO: AliquotaContribuicao.DESCONHECIDA,
        TipoVinculo.MILITAR: AliquotaContribuicao.ZERO,
        TipoVinculo.BENEFICIO: AliquotaContribuicao.ZERO,
    }
    return mapa.get(tipo, AliquotaContribuicao.DESCONHECIDA)


def classificar_contribuicao(
    contribuicao: Contribuicao,
    vinculo_associado: Optional[Vinculo],
) -> Contribuicao:
    """
    Classifica o tipo de uma contribuição com base no vínculo associado.
    Também detecta flags: abaixo_minimo, bloqueada, extemporanea.
    """
    if vinculo_associado is not None:
        tipo_mapa = {
            TipoVinculo.CLT: TipoContribuicao.EMPREGADOR,
            TipoVinculo.MEI: TipoContribuicao.DAS_MEI,
            TipoVinculo.CONTRIBUINTE_INDIVIDUAL: TipoContribuicao.GPS_CI,
            TipoVinculo.CI_PRESTADOR_PJ: TipoContribuicao.GPS_CI_PJ,
            TipoVinculo.FACULTATIVO: TipoContribuicao.GPS_FACULTATIVO,
            TipoVinculo.FACULTATIVO_BAIXA_RENDA: TipoContribuicao.GPS_FACULTATIVO,
            TipoVinculo.EMPREGADO_DOMESTICO: TipoContribuicao.EMPREGADOR,
            TipoVinculo.RURAL_SEGURADO_ESPECIAL: TipoContribuicao.RURAL_SEGURADO_ESPECIAL,
            TipoVinculo.RURAL_EMPREGADO: TipoContribuicao.EMPREGADOR,
            TipoVinculo.MILITAR: TipoContribuicao.MILITAR,
            TipoVinculo.BENEFICIO: TipoContribuicao.BENEFICIO,
        }
        contribuicao.tipo = tipo_mapa.get(vinculo_associado.tipo, TipoContribuicao.DESCONHECIDO)

    # Detectar flags por indicadores
    indicadores = set(contribuicao.indicadores)

    if indicadores & INDICADORES_BLOQUEIO_EC103:
        contribuicao.bloqueada = True

    if indicadores & INDICADORES_EXTEMPORANEA:
        contribuicao.extemporanea = True

    if indicadores & INDICADORES_ABAIXO_MINIMO:
        contribuicao.abaixo_minimo = True

    return contribuicao


def detectar_concomitancias(
    vinculos: list[Vinculo],
    contribuicoes: list[Contribuicao],
) -> dict[str, list[Vinculo]]:
    """
    Detecta meses com contribuições concomitantes (2+ vínculos ativos).
    Retorna dicionário: competência → lista de vínculos ativos naquele mês.

    Usado para:
    - Somar SC até o teto (Tema 1.070 STJ)
    - Detectar concomitâncias proibidas (MEI+Facultativo, CLT+Facultativo)
    - Evitar contar o mesmo mês 2x no tempo de contribuição
    """
    concomitancias: dict[str, list[Vinculo]] = {}

    for contrib in contribuicoes:
        vinculos_ativos = []
        for v in vinculos:
            fim = v.data_fim or date.today()
            if v.data_inicio <= contrib.data_competencia <= fim:
                vinculos_ativos.append(v)

        if len(vinculos_ativos) >= 2:
            concomitancias[contrib.competencia] = vinculos_ativos

    return concomitancias


def determinar_perfil(vinculos: list[Vinculo]) -> PerfilContributivo:
    """
    Determina o perfil contributivo do segurado para definir
    quais páginas incluir no relatório.
    """
    tipos = {v.tipo for v in vinculos if v.tipo != TipoVinculo.BENEFICIO}

    tem_mei = TipoVinculo.MEI in tipos
    tem_clt = TipoVinculo.CLT in tipos or TipoVinculo.EMPREGADO_DOMESTICO in tipos
    tem_ci = TipoVinculo.CONTRIBUINTE_INDIVIDUAL in tipos or TipoVinculo.CI_PRESTADOR_PJ in tipos
    tem_rural = any(t.value.startswith("RURAL") for t in tipos)
    tem_servidor = TipoVinculo.SERVIDOR_PUBLICO in tipos

    # Contar tipos distintos (excluindo benefício e militar)
    tipos_relevantes = tipos - {TipoVinculo.BENEFICIO, TipoVinculo.MILITAR, TipoVinculo.DESCONHECIDO}
    num_tipos = len(tipos_relevantes)

    if num_tipos == 0:
        return PerfilContributivo.MEI_PURO  # fallback

    if num_tipos == 1:
        if tem_mei:
            return PerfilContributivo.MEI_PURO
        if tem_clt:
            return PerfilContributivo.CLT_PURO
        if tem_ci:
            return PerfilContributivo.CONTRIBUINTE_INDIVIDUAL
        if tem_rural:
            return PerfilContributivo.RURAL
        if tem_servidor:
            return PerfilContributivo.SERVIDOR_PUBLICO

    if num_tipos == 2 and tem_clt and tem_mei:
        return PerfilContributivo.MISTO_CLT_MEI

    return PerfilContributivo.MISTO_COMPLEXO


def detectar_gatilhos_condicionais(
    vinculos: list[Vinculo],
    contribuicoes: list[Contribuicao],
    beneficios: list["Beneficio"],
    pessoa: Pessoa,
) -> dict[str, bool]:
    """
    Detecta quais módulos condicionais devem ser ativados.
    Retorna flags para cada módulo.
    """
    from app.models.beneficio import BENEFICIOS_INCAPACIDADE

    flags = {
        "modulo_ppp_especial": False,
        "modulo_pcd": False,
        "modulo_rural": False,
        "modulo_militar": False,
    }

    # PPP / Tempo Especial: ativa se algum vínculo tem e_especial
    flags["modulo_ppp_especial"] = any(v.e_especial for v in vinculos)

    # PcD: ativa se há benefício por incapacidade ou indicadores de deficiência
    tem_beneficio_incapacidade = any(b.e_incapacidade for b in beneficios)
    tem_indicador_deficiencia = any(
        set(v.indicadores) & INDICADORES_DEFICIENCIA for v in vinculos
    )
    flags["modulo_pcd"] = tem_beneficio_incapacidade or tem_indicador_deficiencia

    # Rural: ativa se há vínculo rural ou indicadores rurais
    flags["modulo_rural"] = any(v.e_rural for v in vinculos) or any(
        set(v.indicadores) & INDICADORES_RURAL for v in vinculos
    )

    # Militar: ativa se há vínculo militar
    flags["modulo_militar"] = any(v.e_militar for v in vinculos)

    # Militar: gatilho por lacuna CNIS (homem, 17-19 anos sem contribuição)
    if pessoa.sexo == Sexo.MASCULINO and not flags["modulo_militar"]:
        idade_primeiro_vinculo = _idade_no_primeiro_vinculo(pessoa, vinculos)
        if idade_primeiro_vinculo is not None and idade_primeiro_vinculo >= 19:
            # Possível serviço militar entre 17-19 anos sem registro
            flags["modulo_militar_possivel"] = True

    return flags


def _idade_no_primeiro_vinculo(pessoa: Pessoa, vinculos: list[Vinculo]) -> Optional[int]:
    """Calcula a idade do segurado no início do primeiro vínculo."""
    vinculos_ordenados = sorted(
        [v for v in vinculos if not v.e_beneficio],
        key=lambda v: v.data_inicio,
    )
    if not vinculos_ordenados:
        return None

    primeiro = vinculos_ordenados[0]
    idade = pessoa.idade_em(primeiro.data_inicio)
    return idade.anos
