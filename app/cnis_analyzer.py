"""
Analisador de CNIS — Lógica de Negócio
Recebe dados estruturados do parser e aplica regras de análise:
- Classificação de indicadores (P/I/A/Desconhecido)
- Cálculo de lacunas contributivas
- Verificação de remunerações vs salário mínimo
- Avaliação de qualidade de segurado
- Estimativa de tempo de contribuição
"""

import json
import os
import sys
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional
from pathlib import Path

from config.constantes_cnis import (
    LACUNA_LIMIAR_DIAS,
    LACUNA_MESES_BAIXA,
    LACUNA_MESES_MEDIA,
    LACUNA_MESES_ALTA,
    MARGEM_PROPORCIONAL_SM,
    PERIODO_GRACA_GERAL,
    PERIODO_GRACA_120_CONTRIBUICOES,
    LIMIAR_CONTRIBUICOES_ININTERRUPTAS,
)


# ============================================================================
#  INDICADORES QUE BLOQUEIAM TEMPO DE CONTRIBUIÇÃO
#  (decisão jurídica — Dra. Tatiana Sampaio, 2026-08-03)
# ============================================================================

# G1 competência-level — competência inválida para todos os fins.
INDICADORES_TEMPO_G1_COMPETENCIA = frozenset({
    'PSC-MEN-SM-EC103',
    'PREC-MENOR-MIN',
    'PREM-BLOQ-EC103',
    'PREC-OBITO',
    'PREM-OBITO',
    'IREC-PROC-RFB',
})

# G1 vínculo-level — vínculo com data admissão/desligamento pós-óbito
# (todas as competências do vínculo saem).
INDICADORES_TEMPO_G1_VINCULO = frozenset({
    'PVIN-ADM-OBITO',
    'PVIN-DESLIG-OBITO',
})

# G2 competência-level — não conta para tempo de contribuição
# (mas conta para idade/carência). Art. 21 §2º Lei 8.212/91.
INDICADORES_TEMPO_G2_COMPETENCIA = frozenset({
    'ILEI123', 'IRECOL (ILEI123)',
    'IMEI', 'IRECOL (IMEI)', 'IREC-MEI',
    'IREC-FBR', 'PREC-FBR',
    'FBR-AUT-CONCQSA', 'FBR-AUT-DUPGRUPFAM', 'FBR-AUT-EXPCAD',
    'FBR-AUT-OBITO', 'FBR-AUT-PENDCAD', 'FBR-AUT-RENPES',
    'IREC-LC123-SUP',
})

# G3 vínculo-level — vínculo problemático (todas as competências saem).
INDICADORES_TEMPO_G3_VINCULO = frozenset({
    'PVIN-CAGED', 'PVIN-ME', 'PVIN-AGRUP-INC',
    'AEXT-VI', 'NDET',
    'PSE-NEG', 'PSE-PEN',
})


# ============================================================================
#  CARREGAMENTO DE CONFIGURAÇÕES
# ============================================================================

CONFIG_DIR = Path(__file__).parent / 'config'


def carregar_indicadores() -> dict:
    """Carrega dicionário de indicadores do JSON."""
    caminho = CONFIG_DIR / 'indicadores_cnis.json'
    with open(caminho, 'r', encoding='utf-8') as f:
        return json.load(f)


def carregar_salarios_minimos() -> list[dict]:
    """Carrega tabela de salários mínimos do JSON."""
    caminho = CONFIG_DIR / 'tabela_salario_minimo.json'
    with open(caminho, 'r', encoding='utf-8') as f:
        dados = json.load(f)
    return dados['salarios_minimos']


def carregar_serie_inpc() -> dict:
    """Carrega série INPC mensal (BCB SGS 188) com fatores acumulados.

    Retorna {} se o arquivo não existe — correção monetária é opcional.
    """
    caminho = CONFIG_DIR / 'serie_inpc.json'
    if not caminho.exists():
        return {}
    with open(caminho, 'r', encoding='utf-8') as f:
        return json.load(f)


def corrigir_valor_inpc(valor: float, competencia: str, serie_inpc: dict) -> Optional[float]:
    """Aplica fator INPC acumulado para trazer o valor da competência à data-base.

    Args:
        valor: salário-de-contribuição nominal da competência
        competencia: 'MM/YYYY'
        serie_inpc: dict carregado de serie_inpc.json

    Returns:
        Valor corrigido (float) ou None se não houver fator para a competência.

    Limitação: INPC isolado aproxima bem o índice oficial INSS para competências
    a partir de 1995. Para competências pré-Real, a divergência pode ser
    significativa porque o INSS usa índice composto (BTN/IPC/INPC).
    """
    if not serie_inpc or not valor or not competencia:
        return None
    try:
        mes, ano = competencia.split('/')
        chave = f'{ano}-{int(mes):02d}'
    except (ValueError, AttributeError):
        return None
    fator = serie_inpc.get('fatores_correcao_para_data_base', {}).get(chave)
    if fator is None:
        return None
    return round(float(valor) * float(fator), 2)


def obter_salario_minimo(competencia: str, tabela_sm: list[dict]) -> Optional[float]:
    """Retorna o salário mínimo vigente para uma competência (MM/AAAA).

    Encontra a maior vigência que seja <= primeiro dia da competência.
    """
    if not competencia:
        return None

    try:
        mes, ano = competencia.split('/')
        data_comp = date(int(ano), int(mes), 1)
    except (ValueError, AttributeError):
        return None

    # Tabela já está ordenada do mais recente ao mais antigo
    for entrada in tabela_sm:
        data_vigencia = date.fromisoformat(entrada['vigencia'])
        if data_vigencia <= data_comp:
            return entrada['valor']

    return None


# ============================================================================
#  CLASSIFICAÇÃO DE INDICADORES
# ============================================================================

def classificar_indicadores(indicadores: list[str], dicionario: dict) -> list[dict]:
    """Classifica cada indicador como P (Pendência), I (Alerta), A (Acerto) ou Desconhecido."""
    classificados = []

    for codigo in indicadores:
        encontrado = False

        # Buscar em pendências
        if codigo in dicionario.get('PENDENCIAS', {}):
            info = dicionario['PENDENCIAS'][codigo]
            classificados.append({
                'codigo': codigo,
                'tipo': 'PENDENCIA',
                'tipo_label': 'Pendência',
                'nome': info['nome'],
                'descricao': info['descricao'],
                'impacto': info['impacto'],
                'acao': info['acao'],
            })
            encontrado = True

        # Buscar em alertas
        elif codigo in dicionario.get('ALERTAS', {}):
            info = dicionario['ALERTAS'][codigo]
            classificados.append({
                'codigo': codigo,
                'tipo': 'ALERTA',
                'tipo_label': 'Alerta',
                'nome': info['nome'],
                'descricao': info['descricao'],
                'impacto': info['impacto'],
                'acao': info['acao'],
            })
            encontrado = True

        # Buscar em acertos
        elif codigo in dicionario.get('ACERTOS', {}):
            info = dicionario['ACERTOS'][codigo]
            classificados.append({
                'codigo': codigo,
                'tipo': 'ACERTO',
                'tipo_label': 'Acerto',
                'nome': info['nome'],
                'descricao': info['descricao'],
                'impacto': info['impacto'],
                'acao': info['acao'],
            })
            encontrado = True

        if not encontrado:
            classificados.append({
                'codigo': codigo,
                'tipo': 'DESCONHECIDO',
                'tipo_label': 'Desconhecido',
                'nome': f'Indicador {codigo}',
                'descricao': (
                    f'Este indicador ({codigo}) não consta na base de conhecimento. '
                    'Recomenda-se consultar a Portaria DIRBEN/INSS nº 1.316/2025, '
                    'o canal 135 ou um advogado previdenciário.'
                ),
                'impacto': 'Não foi possível determinar o impacto automaticamente.',
                'acao': 'Consultar legislação vigente ou solicitar esclarecimento ao INSS.',
            })

    return classificados


# ============================================================================
#  CÁLCULO DE LACUNAS CONTRIBUTIVAS
# ============================================================================

def parse_data_str(data_str: str) -> Optional[date]:
    """Converte DD/MM/AAAA para date."""
    if not data_str:
        return None
    try:
        return datetime.strptime(data_str.strip(), '%d/%m/%Y').date()
    except ValueError:
        return None


def calcular_lacunas(vinculos: list[dict]) -> list[dict]:
    """Calcula lacunas reais — gaps na UNIÃO dos períodos contributivos.

    Sprint 2: antes a função iterava vínculos consecutivos por ordem de
    `data_inicio`, o que produzia lacunas falsas em históricos com vínculos
    paralelos (ex.: Beltrão com 3 empregos simultâneos a partir de 14/03/1983).
    Agora faz UNIÃO dos intervalos primeiro — assim o gap só é detectado se
    não houver NENHUM vínculo cobrindo o período.

    Classificação de gravidade:
      Baixa: ≤ 3 meses
      Média: 4 a 12 meses
      Alta: 13 a 24 meses
      Crítica: > 24 meses
    """
    # Filtrar apenas vínculos de emprego (não benefícios) com datas
    vinculos_emprego = [
        v for v in vinculos
        if not v.get('eh_beneficio')
        and v.get('data_inicio')
        and v.get('data_fim')
    ]

    # Ordenar por data de início (auxiliar) e construir tuplas (ini, fim, vinc)
    vinculos_emprego.sort(key=lambda v: parse_data_str(v['data_inicio']) or date.min)
    intervalos_v: list[tuple[date, date, dict]] = []
    for v in vinculos_emprego:
        di = parse_data_str(v['data_inicio'])
        df = parse_data_str(v['data_fim'])
        if di and df and di <= df:
            intervalos_v.append((di, df, v))

    # União de intervalos com referência ao vínculo terminal de cada bloco
    unidos: list[tuple[date, date, dict, dict]] = []  # (ini, fim, v_inicio, v_fim)
    for di, df, v in intervalos_v:
        if unidos and di <= unidos[-1][1]:
            ult = unidos[-1]
            if df > ult[1]:
                unidos[-1] = (ult[0], df, ult[2], v)
        else:
            unidos.append((di, df, v, v))

    lacunas = []
    for i in range(len(unidos) - 1):
        data_fim_atual = unidos[i][1]
        data_inicio_prox = unidos[i + 1][0]
        v_anterior = unidos[i][3]
        v_posterior = unidos[i + 1][2]

        # Calcular diferença em meses
        diff_dias = (data_inicio_prox - data_fim_atual).days
        if diff_dias <= LACUNA_LIMIAR_DIAS:
            continue

        meses = diff_dias // 30

        # Classificar gravidade
        if meses <= LACUNA_MESES_BAIXA:
            gravidade = 'BAIXA'
        elif meses <= LACUNA_MESES_MEDIA:
            gravidade = 'MEDIA'
        elif meses <= LACUNA_MESES_ALTA:
            gravidade = 'ALTA'
        else:
            gravidade = 'CRITICA'

        lacunas.append({
            'vinculo_anterior': v_anterior['seq'],
            'vinculo_posterior': v_posterior['seq'],
            'empregador_anterior': v_anterior.get('empregador', 'N/I'),
            'empregador_posterior': v_posterior.get('empregador', 'N/I'),
            'data_fim': v_anterior['data_fim'],
            'data_inicio': v_posterior['data_inicio'],
            'dias': diff_dias,
            'meses': meses,
            'anos_meses': f"{meses // 12} ano(s) e {meses % 12} mês(es)" if meses >= 12 else f"{meses} mês(es)",
            'gravidade': gravidade,
        })

    return lacunas


# ============================================================================
#  VERIFICAÇÃO DE REMUNERAÇÕES VS SALÁRIO MÍNIMO
# ============================================================================

_TIPOS_RECOLHIMENTO = {
    'Contribuinte Individual',
    'Facultativo',
    'Microempreendedor Individual',
    'Segurado Especial',
}


def _classificar_tipo_competencia(tipo_vinculo: str) -> str:
    """Decide se uma competência é 'Recolhimento' (CI/MEI/Facultativo/Esp.)
    ou 'Remuneração' (CLT, Avulso, Doméstico, Agente Público)."""
    if tipo_vinculo in _TIPOS_RECOLHIMENTO:
        return 'Recolhimento'
    return 'Remuneração'


def _classificar_indicador_sc_menor_sm(competencia: str) -> str:
    """Determina o indicador oficial INSS para SC < SM:
       PSC-MEN-SM-EC103 → competências a partir de 11/2019 (Art. 29 EC 103/2019)
       PREC-MENOR-MIN   → competências anteriores a 11/2019.
    """
    try:
        mes, ano = competencia.split('/')
        if (int(ano), int(mes)) >= (2019, 11):
            return 'PSC-MEN-SM-EC103'
    except (ValueError, AttributeError):
        pass
    return 'PREC-MENOR-MIN'


def analisar_remuneracoes(vinculos: list[dict], tabela_sm: list[dict], serie_inpc: Optional[dict] = None) -> dict:
    """Analisa remunerações: identifica abaixo do SM, proporcionais, etc.

    Para cada competência abaixo do SM, classifica:
      - `indicador_oficial`: PSC-MEN-SM-EC103 (≥ 11/2019) ou PREC-MENOR-MIN (< 11/2019)
      - `tipo_competencia`: 'Recolhimento' (CI/MEI/Facultativo/Esp.) ou 'Remuneração' (CLT)
      - `valor_corrigido`: valor atualizado pelo INPC até a data-base do índice
        (omitido se a série INPC não está disponível ou se a competência é pré-Real).
    """
    abaixo_minimo = []
    proporcionais = []
    moeda_antiga = []
    total_competencias = 0
    serie_inpc = serie_inpc or {}

    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue

        data_inicio = parse_data_str(vinculo.get('data_inicio', ''))
        data_fim = parse_data_str(vinculo.get('data_fim', ''))
        tipo_competencia = _classificar_tipo_competencia(vinculo.get('tipo', ''))

        for rem in vinculo.get('remuneracoes', []):
            comp = rem.get('competencia')
            valor = rem.get('valor')

            if not comp or valor is None:
                continue

            total_competencias += 1

            # Anota tipo (Recolhimento/Remuneração) na própria remuneração
            # para que tabelas posteriores possam exibir o tipo correto.
            rem.setdefault('tipo_competencia', tipo_competencia)

            # Anota valor corrigido pelo INPC, quando disponível.
            if 'valor_corrigido' not in rem:
                vc = corrigir_valor_inpc(valor, comp, serie_inpc)
                if vc is not None:
                    rem['valor_corrigido'] = vc

            # Verificar se é pré-1994 (moeda antiga)
            try:
                ano_comp = int(comp.split('/')[1])
                mes_comp = int(comp.split('/')[0])
            except (ValueError, IndexError):
                continue

            if ano_comp < 1994 or (ano_comp == 1994 and mes_comp < 7):
                moeda_antiga.append({
                    'competencia': comp,
                    'valor': valor,
                    'vinculo_seq': vinculo['seq'],
                    'empregador': vinculo.get('empregador', 'N/I'),
                    'nota': 'Moeda antiga — verificar conversão para Real',
                })
                continue

            # Obter SM vigente
            sm = obter_salario_minimo(comp, tabela_sm)
            if not sm:
                continue

            # Verificar se está abaixo do SM (margem de 5% para proporcionais)
            if valor < sm * float(MARGEM_PROPORCIONAL_SM):
                # Verificar se é mês de admissão ou rescisão (proporcional)
                eh_proporcional = False
                data_comp = date(ano_comp, mes_comp, 1)

                if data_inicio and data_inicio.year == ano_comp and data_inicio.month == mes_comp:
                    eh_proporcional = True
                    dias_trabalhados = (
                        date(ano_comp, mes_comp + 1, 1) if mes_comp < 12
                        else date(ano_comp + 1, 1, 1)
                    ) - data_inicio
                    proporcionais.append({
                        'competencia': comp,
                        'valor': valor,
                        'salario_minimo': sm,
                        'vinculo_seq': vinculo['seq'],
                        'empregador': vinculo.get('empregador', 'N/I'),
                        'tipo': 'admissao',
                        'tipo_competencia': tipo_competencia,
                        'dias_trabalhados': dias_trabalhados.days,
                        'nota': f'Proporcional — admissão em {vinculo.get("data_inicio", "N/I")} ({dias_trabalhados.days} dias)',
                    })

                elif data_fim and data_fim.year == ano_comp and data_fim.month == mes_comp:
                    eh_proporcional = True
                    dias_trabalhados = data_fim.day
                    proporcionais.append({
                        'competencia': comp,
                        'valor': valor,
                        'salario_minimo': sm,
                        'vinculo_seq': vinculo['seq'],
                        'empregador': vinculo.get('empregador', 'N/I'),
                        'tipo': 'rescisao',
                        'tipo_competencia': tipo_competencia,
                        'dias_trabalhados': dias_trabalhados,
                        'nota': f'Proporcional — rescisão em {vinculo.get("data_fim", "N/I")} ({dias_trabalhados} dias)',
                    })

                if not eh_proporcional:
                    item = {
                        'competencia': comp,
                        'valor': valor,
                        'salario_minimo': sm,
                        'diferenca': round(sm - valor, 2),
                        'percentual': round((valor / sm) * 100, 1),
                        'vinculo_seq': vinculo['seq'],
                        'empregador': vinculo.get('empregador', 'N/I'),
                        'tipo_competencia': tipo_competencia,
                        'indicador_oficial': _classificar_indicador_sc_menor_sm(comp),
                    }
                    vc = corrigir_valor_inpc(valor, comp, serie_inpc)
                    if vc is not None:
                        item['valor_corrigido'] = vc
                        sm_corr = corrigir_valor_inpc(sm, comp, serie_inpc)
                        if sm_corr is not None:
                            item['salario_minimo_corrigido'] = sm_corr
                    abaixo_minimo.append(item)

    # ------------------------------------------------------------------
    # Recortes PSC-MEN-SM-EC103 vs PREC-MENOR-MIN
    # ------------------------------------------------------------------
    # Sprint 1 derivava esses recortes do conjunto abaixo_minimo (cálculo
    # próprio do analyzer, SC < SM e NÃO proporcional). Mas o INSS marca o
    # indicador PSC-MEN-SM-EC103 também em competências PROPORCIONAIS de
    # mês de admissão/rescisão. Por isso, em casos como Maria Aparecida, a
    # contagem do CJ (4 PSC) ficava maior que a nossa (1 PSC).
    #
    # Solução Sprint 2: popular essas listas a partir dos INDICADORES já
    # extraídos pelo parser para cada remuneração (rem['indicadores']),
    # garantindo paridade com o que está oficialmente no CNIS. Mantém
    # abaixo_minimo, proporcionais e moeda_antiga como cálculos próprios
    # para outras seções do relatório.
    psc_men_sm: list[dict] = []
    prec_menor: list[dict] = []
    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue
        tipo_v = _classificar_tipo_competencia(vinculo.get('tipo', ''))
        for rem in vinculo.get('remuneracoes', []):
            inds = set(rem.get('indicadores', []))
            comp = rem.get('competencia')
            valor = rem.get('valor')
            if not comp:
                continue

            sm = obter_salario_minimo(comp, tabela_sm) or 0.0
            base = {
                'competencia': comp,
                'valor': valor,
                'salario_minimo': sm,
                'vinculo_seq': vinculo.get('seq'),
                'empregador': vinculo.get('empregador', 'N/I'),
                'tipo_competencia': tipo_v,
            }
            if serie_inpc and valor is not None:
                vc = corrigir_valor_inpc(valor, comp, serie_inpc)
                if vc is not None:
                    base['valor_corrigido'] = vc
                if sm:
                    sm_corr = corrigir_valor_inpc(sm, comp, serie_inpc)
                    if sm_corr is not None:
                        base['salario_minimo_corrigido'] = sm_corr

            if 'PSC-MEN-SM-EC103' in inds:
                item = dict(base)
                item['indicador_oficial'] = 'PSC-MEN-SM-EC103'
                psc_men_sm.append(item)
            if 'PREC-MENOR-MIN' in inds:
                item = dict(base)
                item['indicador_oficial'] = 'PREC-MENOR-MIN'
                prec_menor.append(item)

    return {
        'total_competencias_analisadas': total_competencias,
        'abaixo_minimo': abaixo_minimo,
        'proporcionais': proporcionais,
        'moeda_antiga': moeda_antiga,
        'total_abaixo_minimo': len(abaixo_minimo),
        'total_proporcionais': len(proporcionais),
        'total_moeda_antiga': len(moeda_antiga),
        # Recortes granulares por indicador oficial INSS extraído do CNIS
        'psc_men_sm_ec103': psc_men_sm,
        'prec_menor_min': prec_menor,
        'total_psc_men_sm_ec103': len(psc_men_sm),
        'total_prec_menor_min': len(prec_menor),
    }


# ============================================================================
#  QUALIDADE DE SEGURADO (PERÍODO DE GRAÇA)
# ============================================================================

def _adicionar_meses(d: date, n: int) -> date:
    """Soma n meses preservando dia 1 do mês resultante."""
    novo_mes = d.month + n
    novo_ano = d.year + (novo_mes - 1) // 12
    novo_mes = ((novo_mes - 1) % 12) + 1
    return date(novo_ano, novo_mes, 1)


def _data_fim_graca(ultima_competencia: date, meses_graca: int) -> date:
    """Calcula a data exata em que a qualidade de segurado deixa de ser mantida.

    Regra: Art. 15 §4º da Lei 8.213/91 + Art. 14 do Decreto 3.048/99 —
    a QS é mantida durante o período de graça (N meses contados a partir
    do mês SEGUINTE ao da última contribuição) e ainda até o dia 15 do
    2º mês subsequente ao término desse prazo.

    Ex.: última contribuição em 12/2024, graça de 24 meses →
         período de graça: 01/2025 a 12/2026
         + 15 dias do 2º mês seguinte = 15/02/2027 (data limite da QS).
    """
    # Início do período de graça = 1º dia do mês seguinte à última contribuição
    inicio_graca = _adicionar_meses(ultima_competencia.replace(day=1), 1)
    # Fim do período de graça (último mês contado) = início + (graça-1) meses
    fim_periodo = _adicionar_meses(inicio_graca, meses_graca - 1)
    # 2º mês seguinte = fim_periodo + 2 meses
    segundo_mes = _adicionar_meses(fim_periodo, 2)
    return date(segundo_mes.year, segundo_mes.month, 15)


def avaliar_qualidade_segurado(vinculos: list[dict], data_extrato: str) -> dict:
    """Avalia se o segurado mantém qualidade de segurado na data do extrato.

    Algoritmo (Art. 15 Lei 8.213/91 + Art. 14 Decreto 3.048/99):
      1) Lista todas as competências contributivas em ordem cronológica.
      2) Varre o histórico: para cada gap entre competências, calcula a graça
         vigente naquele ponto (24m se já havia ≥120 contribuições ininterruptas
         desde a última perda, senão 12m). Se o gap supera o fim da graça
         (incluindo o +15 dias do 2º mês seguinte), marca PERDA HISTÓRICA e
         REINICIA o contador de contribuições.
      3) Após varrer tudo, decide a QS na data de referência com base na
         última contribuição e nas contribuições acumuladas desde a última
         perda histórica (ou desde o início se nunca perdeu).

    Devolve também `periodos_manutencao` — lista análoga à da aba "Qualidade
    de segurado" do Cálculo Jurídico, útil pra exibir histórico no PDF.
    """
    data_ref = parse_data_str(data_extrato) or date.today()

    # Coletar todas as competências contributivas (mes/ano → date(ano, mes, 1))
    competencias = []
    tipo_ultimo_vinculo = None
    for vinculo in sorted(vinculos, key=lambda v: parse_data_str(v.get('data_inicio') or '') or date.min):
        if vinculo.get('eh_beneficio'):
            continue
        tipo_v = vinculo.get('tipo', '')
        for rem in vinculo.get('remuneracoes', []):
            comp = rem.get('competencia') or ''
            try:
                mes, ano = comp.split('/')
                d = date(int(ano), int(mes), 1)
            except (ValueError, AttributeError):
                continue
            competencias.append((d, comp, tipo_v))
        # Memoriza o tipo do último vínculo cronológico
        tipo_ultimo_vinculo = tipo_v or tipo_ultimo_vinculo

    competencias.sort(key=lambda x: x[0])

    if not competencias:
        return {
            'status': 'INDETERMINADO',
            'mensagem': 'Não foram encontradas contribuições válidas no extrato.',
            'ultima_contribuicao': None,
            'periodo_graca_meses': 0,
            'data_perda_estimada': None,
            'periodos_manutencao': [],
            'perdas_historicas': [],
        }

    perdas_historicas: list[dict] = []
    periodos_manutencao: list[dict] = []
    contribuicoes_acumuladas = 0
    inicio_manutencao_atual = competencias[0][0]
    ultima_comp_data = None
    ultima_comp_str = None

    for i, (comp_data, comp_str, _tipo) in enumerate(competencias):
        if ultima_comp_data is None:
            contribuicoes_acumuladas = 1
            ultima_comp_data = comp_data
            ultima_comp_str = comp_str
            continue

        # Graça vigente NAQUELE momento (com base nas contribuições já acumuladas)
        graca_meses = (
            PERIODO_GRACA_120_CONTRIBUICOES
            if contribuicoes_acumuladas >= LIMIAR_CONTRIBUICOES_ININTERRUPTAS
            else PERIODO_GRACA_GERAL
        )
        limite_qs = _data_fim_graca(ultima_comp_data, graca_meses)

        if comp_data > limite_qs:
            # Perda histórica de qualidade
            perdas_historicas.append({
                'ultima_contribuicao': ultima_comp_str,
                'graca_meses': graca_meses,
                'perdida_em': limite_qs.strftime('%d/%m/%Y'),
                'retomada_em': comp_str,
                'contribuicoes_no_periodo': contribuicoes_acumuladas,
            })
            periodos_manutencao.append({
                'inicio': inicio_manutencao_atual.strftime('%d/%m/%Y'),
                'fim': limite_qs.strftime('%d/%m/%Y'),
                'meses': (limite_qs.year - inicio_manutencao_atual.year) * 12
                          + (limite_qs.month - inicio_manutencao_atual.month),
                'graca_aplicada': graca_meses,
            })
            inicio_manutencao_atual = comp_data
            contribuicoes_acumuladas = 1
        else:
            contribuicoes_acumuladas += 1

        ultima_comp_data = comp_data
        ultima_comp_str = comp_str

    # Avaliação da QS na data de referência
    graca_atual = (
        PERIODO_GRACA_120_CONTRIBUICOES
        if contribuicoes_acumuladas >= LIMIAR_CONTRIBUICOES_ININTERRUPTAS
        else PERIODO_GRACA_GERAL
    )
    data_perda_atual = _data_fim_graca(ultima_comp_data, graca_atual)
    periodos_manutencao.append({
        'inicio': inicio_manutencao_atual.strftime('%d/%m/%Y'),
        'fim': data_perda_atual.strftime('%d/%m/%Y'),
        'meses': (data_perda_atual.year - inicio_manutencao_atual.year) * 12
                  + (data_perda_atual.month - inicio_manutencao_atual.month),
        'graca_aplicada': graca_atual,
    })

    if data_ref <= data_perda_atual:
        meses_restantes = (data_perda_atual.year - data_ref.year) * 12 + (data_perda_atual.month - data_ref.month)
        status = 'MANTIDA'
        mensagem = (
            f'O(a) segurado(a) possui qualidade de segurado. '
            f'A última contribuição registrada foi em {ultima_comp_str}. '
            f'O período de graça de {graca_atual} meses se estende até '
            f'{data_perda_atual.strftime("%d/%m/%Y")} ({meses_restantes} meses restantes).'
        )
    else:
        anos_sem = (data_ref.year - data_perda_atual.year)
        status = 'PERDIDA'
        mensagem = (
            f'O(a) segurado(a) PERDEU a qualidade de segurado. '
            f'A última contribuição foi em {ultima_comp_str} e o período de graça '
            f'de {graca_atual} meses expirou em {data_perda_atual.strftime("%d/%m/%Y")} '
            f'(há aproximadamente {anos_sem} ano(s)). Para recuperar, são necessárias '
            f'6 contribuições válidas consecutivas (50% da carência de 12 meses).'
        )

    return {
        'status': status,
        'mensagem': mensagem,
        'ultima_contribuicao': ultima_comp_str,
        'tipo_ultimo_vinculo': tipo_ultimo_vinculo,
        'total_contribuicoes': sum(1 for _ in competencias),
        'contribuicoes_desde_ultima_perda': contribuicoes_acumuladas,
        'periodo_graca_meses': graca_atual,
        'data_perda_estimada': data_perda_atual.strftime('%d/%m/%Y'),
        'periodos_manutencao': periodos_manutencao,
        'perdas_historicas': perdas_historicas,
    }


# ============================================================================
#  ESTIMATIVA DE TEMPO DE CONTRIBUIÇÃO
# ============================================================================

def _unir_intervalos(intervalos: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Une intervalos [inicio, fim] sobrepostos ou adjacentes (gap ≤ 1 dia).

    Garante que períodos concomitantes (CI sobreposto com Empregado) não sejam
    contados em duplicidade na soma de tempo de contribuição.
    """
    if not intervalos:
        return []
    s = sorted(intervalos, key=lambda x: x[0])
    out = [s[0]]
    for ini, fim in s[1:]:
        ult_ini, ult_fim = out[-1]
        if ini <= ult_fim or (ini - ult_fim).days <= 1:
            out[-1] = (ult_ini, max(ult_fim, fim))
        else:
            out.append((ini, fim))
    return out


def detectar_avisos_beneficios(vinculos: list[dict]) -> list[dict]:
    """Sprint 2: gera avisos no topo do PDF para benefícios presentes no CNIS.

    Padrões reconhecidos:
      - Pensão por morte (espécie 21) → benefício de dependente, não deve
        contar no cálculo de outro benefício próprio do segurado.
      - Aposentadoria por Tempo de Contribuição (espécie 42) — se ATIVA,
        indica que o segurado já está aposentado; se INDEFERIDA, registra
        tentativa recente.
      - Auxílio-Doença (espécie 31) INDEFERIDO — sinaliza problema
        pendente em incapacidade temporária.
    """
    avisos = []
    for v in vinculos:
        if not v.get('eh_beneficio'):
            continue
        especie = (v.get('especie_beneficio') or '').upper()
        situacao = (v.get('situacao_beneficio') or '').upper()
        nb = v.get('numero_beneficio') or 'N/I'

        if 'PENSAO POR MORTE' in especie or especie.startswith('21'):
            avisos.append({
                'tipo': 'PENSAO_POR_MORTE',
                'severidade': 'AVISO',
                'titulo': 'Há uma pensão por morte no CNIS importado.',
                'mensagem': (
                    'A pensão por morte é benefício de dependente — não deve ser '
                    f'considerada no cálculo de outro benefício do(a) próprio(a) segurado(a). '
                    f'NB {nb}, situação {situacao or "não informada"}.'
                ),
            })
        elif 'TEMPO DE CONTRIBU' in especie or especie.startswith('42'):
            if 'ATIVO' in situacao:
                avisos.append({
                    'tipo': 'APOSENTADORIA_ATIVA',
                    'severidade': 'INFO',
                    'titulo': 'Aposentadoria por Tempo de Contribuição ATIVA no CNIS.',
                    'mensagem': (
                        f'O(a) segurado(a) já está recebendo Aposentadoria por Tempo '
                        f'de Contribuição (NB {nb}). Para análise de outro benefício, '
                        'verificar regras de acumulação aplicáveis.'
                    ),
                })
            elif 'INDEFERIDO' in situacao:
                avisos.append({
                    'tipo': 'APOSENTADORIA_INDEFERIDA',
                    'severidade': 'AVISO',
                    'titulo': 'Pedido de Aposentadoria por Tempo de Contribuição INDEFERIDO.',
                    'mensagem': (
                        f'Há um pedido de aposentadoria por tempo de contribuição '
                        f'INDEFERIDO no CNIS (NB {nb}). Avaliar motivos do indeferimento '
                        'e cabimento de recurso administrativo ou novo requerimento.'
                    ),
                })
        elif 'AUXILIO DOENCA' in especie or especie.startswith('31'):
            if 'INDEFERIDO' in situacao:
                avisos.append({
                    'tipo': 'AUXILIO_DOENCA_INDEFERIDO',
                    'severidade': 'AVISO',
                    'titulo': 'Pedido de Auxílio-Doença INDEFERIDO no CNIS.',
                    'mensagem': (
                        f'Há um pedido de auxílio-doença INDEFERIDO (NB {nb}). '
                        'Avaliar histórico médico e cabimento de recurso ou novo pedido.'
                    ),
                })
    return avisos


def estimar_tempo_contribuicao(vinculos: list[dict]) -> dict:
    """Calcula o tempo total de contribuição apurado pelo CNIS.

    Algoritmo:
      1) Coleta todos os intervalos contributivos dos vínculos (exclui benefícios).
      2) Faz UNIÃO dos intervalos — períodos concomitantes (empregado + CI ao
         mesmo tempo) entram uma vez só.
      3) Soma a duração em dias de cada intervalo unido.
      4) Converte total em anos/meses/dias (365/30 dias por ano/mês).

    Esse é o tempo BRUTO apurado pelo extrato. NÃO desconta competências
    bloqueadas por indicadores (PSC-MEN-SM, PREC-MENOR-MIN, PREM-FVIN etc.) —
    isso fica para a próxima etapa quando implementarmos a verificação por
    competência.
    """
    intervalos: list[tuple[date, date]] = []
    periodos_raw = []

    hoje = date.today()
    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue

        data_inicio = parse_data_str(vinculo.get('data_inicio', ''))
        data_fim = parse_data_str(vinculo.get('data_fim', '')) or hoje
        if not data_inicio or data_fim < data_inicio:
            continue

        intervalos.append((data_inicio, data_fim))
        periodos_raw.append({
            'vinculo_seq': vinculo['seq'],
            'empregador': vinculo.get('empregador', 'N/I'),
            'inicio': vinculo.get('data_inicio'),
            'fim': vinculo.get('data_fim') or 'Em aberto (ativo)',
            'dias': (data_fim - data_inicio).days + 1,
        })

    unidos = _unir_intervalos(intervalos)
    total_dias = sum((fim - ini).days + 1 for ini, fim in unidos)

    anos = total_dias // 365
    resto = total_dias % 365
    meses = resto // 30
    dias = resto % 30

    intervalos_unidos = [
        {
            'inicio': ini.strftime('%d/%m/%Y'),
            'fim': fim.strftime('%d/%m/%Y'),
            'dias': (fim - ini).days + 1,
        }
        for ini, fim in unidos
    ]

    liquido = _calcular_tempo_liquido(vinculos, total_dias)

    return {
        'total_dias': total_dias,
        'anos': anos,
        'meses': meses,
        'dias': dias,
        'descricao': f'{anos} ano(s), {meses} mês(es) e {dias} dia(s)',
        'periodos': periodos_raw,
        'intervalos_unidos': intervalos_unidos,
        'total_intervalos_unidos': len(unidos),
        'nota': (
            'Tempo bruto apurado pela união dos intervalos dos vínculos do '
            'extrato, sem dupla contagem de períodos concomitantes. NÃO inclui '
            'descontos por competências bloqueadas por pendências (PSC-MEN-SM, '
            'PREC-MENOR-MIN, PREM-FVIN, etc.). A contagem oficial pelo INSS '
            'considera apenas contribuições válidas.'
        ),
        'liquido': liquido,
    }


def _proximo_mes(mes: int, ano: int) -> tuple[int, int]:
    if mes == 12:
        return 1, ano + 1
    return mes + 1, ano


def _meses_no_intervalo(inicio: date, fim: date):
    """Itera (mes, ano) para cada mês tocado por [inicio, fim]."""
    mes, ano = inicio.month, inicio.year
    fim_mes, fim_ano = fim.month, fim.year
    while (ano, mes) <= (fim_ano, fim_mes):
        yield mes, ano
        mes, ano = _proximo_mes(mes, ano)


def _calcular_tempo_liquido(vinculos: list[dict], total_dias_bruto: int) -> dict:
    """Calcula o tempo LÍQUIDO descontando meses bloqueados por indicadores.

    Descontos aplicados (aprovados pela Dra. em 2026-08-03):
      - G1: competência inválida para todos os fins (SC<SM, óbito, RFB) ou
            vínculo com data admissão/desligamento pós-óbito
      - G2: não conta para tempo de contribuição (MEI/LC123/FBR)
      - G3: vínculo problemático (CAGED, mandato eletivo, seg. especial não
            ratificado, extemporâneo indeferido, etc.)

    Um mês só é descontado se TODOS os vínculos que o cobrem tiverem algum
    indicador bloqueador — se houver ao menos uma cobertura válida, o mês
    permanece no cômputo (usa-se ela).
    """
    hoje = date.today()
    cobertura: dict[tuple[int, int], list[tuple[int, Optional[tuple[str, str]]]]] = {}

    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue
        inicio = parse_data_str(vinculo.get('data_inicio', ''))
        fim = parse_data_str(vinculo.get('data_fim', '')) or hoje
        if not inicio or fim < inicio:
            continue

        inds_v = set(vinculo.get('indicadores_vinculo', []) or [])
        bloqueio_g1v = inds_v & INDICADORES_TEMPO_G1_VINCULO
        bloqueio_g3 = inds_v & INDICADORES_TEMPO_G3_VINCULO
        if bloqueio_g1v:
            motivo_vinculo: Optional[tuple[str, str]] = ('G1', sorted(bloqueio_g1v)[0])
        elif bloqueio_g3:
            motivo_vinculo = ('G3', sorted(bloqueio_g3)[0])
        else:
            motivo_vinculo = None

        rem_por_comp: dict[tuple[int, int], set[str]] = {}
        for rem in vinculo.get('remuneracoes', []) or []:
            comp = rem.get('competencia')
            if not comp:
                continue
            try:
                m_str, a_str = comp.split('/')
                key = (int(m_str), int(a_str))
            except (ValueError, IndexError):
                continue
            rem_por_comp[key] = set(rem.get('indicadores', []) or [])

        for mes, ano in _meses_no_intervalo(inicio, fim):
            key = (mes, ano)
            if motivo_vinculo is not None:
                motivo = motivo_vinculo
            else:
                inds_r = rem_por_comp.get(key, set())
                bloq_g1c = inds_r & INDICADORES_TEMPO_G1_COMPETENCIA
                bloq_g2c = inds_r & INDICADORES_TEMPO_G2_COMPETENCIA
                if bloq_g1c:
                    motivo = ('G1', sorted(bloq_g1c)[0])
                elif bloq_g2c:
                    motivo = ('G2', sorted(bloq_g2c)[0])
                else:
                    motivo = None
            cobertura.setdefault(key, []).append((vinculo['seq'], motivo))

    total_meses_bruto = len(cobertura)
    meses_descontados_por_grupo = {'G1': 0, 'G2': 0, 'G3': 0}
    codigos_por_grupo: dict[str, set[str]] = {'G1': set(), 'G2': set(), 'G3': set()}
    meses_validos = 0

    for coberturas in cobertura.values():
        motivos = [m for (_, m) in coberturas if m is not None]
        tem_cobertura_valida = len(motivos) < len(coberturas)
        if tem_cobertura_valida:
            meses_validos += 1
            continue

        # Todas as coberturas bloqueadas — escolher pior grupo (G1 > G2 > G3
        # em impacto jurídico, mas para contabilidade damos preferência ao
        # primeiro grupo encontrado na ordem G1, G2, G3).
        grupos_presentes = {g for (g, _) in motivos}
        for g in ('G1', 'G2', 'G3'):
            if g in grupos_presentes:
                meses_descontados_por_grupo[g] += 1
                for gg, cod in motivos:
                    if gg == g:
                        codigos_por_grupo[g].add(cod)
                break

    meses_descontados = sum(meses_descontados_por_grupo.values())
    dias_descontados = meses_descontados * 30
    dias_liquido = max(0, total_dias_bruto - dias_descontados)

    anos_l = dias_liquido // 365
    resto_l = dias_liquido % 365
    meses_l = resto_l // 30
    dias_l = resto_l % 30

    if meses_descontados:
        diff_anos = meses_descontados // 12
        diff_meses = meses_descontados % 12
        if diff_anos and diff_meses:
            diff_desc = f'{diff_anos} ano(s) e {diff_meses} mês(es) descontados'
        elif diff_anos:
            diff_desc = f'{diff_anos} ano(s) descontados'
        else:
            diff_desc = f'{diff_meses} mês(es) descontados'
    else:
        diff_desc = 'Sem descontos aplicados'

    return {
        'total_dias': dias_liquido,
        'anos': anos_l,
        'meses': meses_l,
        'dias': dias_l,
        'descricao': f'{anos_l} ano(s), {meses_l} mês(es) e {dias_l} dia(s)',
        'total_meses_bruto': total_meses_bruto,
        'meses_descontados': meses_descontados,
        'diferenca_descricao': diff_desc,
        'descontos_por_grupo': {
            'G1': {
                'meses': meses_descontados_por_grupo['G1'],
                'indicadores': sorted(codigos_por_grupo['G1']),
                'descricao': (
                    'Competência inválida para todos os fins '
                    '(SC<SM, óbito, processo RFB, data pós-óbito).'
                ),
            },
            'G2': {
                'meses': meses_descontados_por_grupo['G2'],
                'indicadores': sorted(codigos_por_grupo['G2']),
                'descricao': (
                    'Não conta para tempo de contribuição, mas conta para '
                    'idade/carência (MEI/LC123/FBR — Art. 21 §2º Lei 8.212/91).'
                ),
            },
            'G3': {
                'meses': meses_descontados_por_grupo['G3'],
                'indicadores': sorted(codigos_por_grupo['G3']),
                'descricao': (
                    'Vínculo problemático (CAGED, mandato eletivo, seg. '
                    'especial não ratificado, extemporâneo indeferido, etc.).'
                ),
            },
        },
        'nota': (
            'Tempo líquido = tempo bruto − meses bloqueados por indicadores '
            'CNIS. Um mês só é descontado quando TODOS os vínculos que o '
            'cobrem estão bloqueados. Cálculo aproximado em meses (30 dias/mês).'
        ),
    }


# ============================================================================
#  VERIFICAÇÕES ADICIONAIS
# ============================================================================

def verificar_sobreposicoes(vinculos: list[dict]) -> list[dict]:
    """Identifica vínculos com períodos sobrepostos."""
    sobreposicoes = []
    vinculos_emprego = [
        v for v in vinculos
        if not v.get('eh_beneficio')
        and v.get('data_inicio')
    ]

    for i in range(len(vinculos_emprego)):
        for j in range(i + 1, len(vinculos_emprego)):
            vi = vinculos_emprego[i]
            vj = vinculos_emprego[j]

            inicio_i = parse_data_str(vi['data_inicio'])
            fim_i = parse_data_str(vi.get('data_fim', '')) or date.today()
            inicio_j = parse_data_str(vj['data_inicio'])
            fim_j = parse_data_str(vj.get('data_fim', '')) or date.today()

            if not inicio_i or not inicio_j:
                continue

            # Verificar sobreposição
            if inicio_i <= fim_j and inicio_j <= fim_i:
                sobreposicoes.append({
                    'vinculo_a': vi['seq'],
                    'empregador_a': vi.get('empregador', 'N/I'),
                    'periodo_a': f"{vi['data_inicio']} a {vi.get('data_fim', 'aberto')}",
                    'vinculo_b': vj['seq'],
                    'empregador_b': vj.get('empregador', 'N/I'),
                    'periodo_b': f"{vj['data_inicio']} a {vj.get('data_fim', 'aberto')}",
                    'nota': 'Pode ser legítimo (dois empregos simultâneos). Verificar se ambos estão sendo computados.',
                })

    return sobreposicoes


def verificar_vinculos_sem_fim(vinculos: list[dict]) -> list[dict]:
    """Identifica vínculos sem data fim que têm outro vínculo posterior.

    Esses vínculos precisam ser levados a acerto no CNIS (via Portal CNIS / Meu INSS)
    para que o INSS considere o período corretamente para fins previdenciários.
    Também marca `requer_acerto_cnis=True` no próprio vínculo (in-place)
    para que o template possa destacar visualmente na tabela.
    """
    anomalias = []
    vinculos_emprego = [
        v for v in vinculos
        if not v.get('eh_beneficio') and v.get('data_inicio')
    ]

    if len(vinculos_emprego) <= 1:
        return anomalias

    # Ordenar por data de início
    vinculos_emprego.sort(
        key=lambda v: parse_data_str(v['data_inicio']) or date.min
    )

    # O último vínculo pode legitimamente não ter data fim (ativo)
    for v in vinculos_emprego[:-1]:
        if not v.get('data_fim'):
            # Marca no próprio vínculo para o template destacar
            v['requer_acerto_cnis'] = True
            anomalias.append({
                'vinculo_seq': v['seq'],
                'empregador': v.get('empregador', 'N/I'),
                'data_inicio': v['data_inicio'],
                'nota': (
                    'Vínculo sem data de fim possui outro vínculo posterior. '
                    'Requer acerto do CNIS para que o INSS considere esse período '
                    'de contribuição para fins previdenciários.'
                ),
            })

    return anomalias


# ============================================================================
#  GERAÇÃO DA CONCLUSÃO
# ============================================================================

def _conclusao_perda_qualidade(nome: str, qualidade: dict) -> Optional[dict]:
    """Gera problema de perda da qualidade de segurado."""
    if qualidade.get('status', '') != 'PERDIDA':
        return None
    return {
        'problema': (
            f'O(a) Sr(a). {nome} perdeu a qualidade de segurado(a). '
            f'A última contribuição foi em {qualidade.get("ultima_contribuicao", "N/I")} '
            f'e o período de graça expirou em {qualidade.get("data_perda_estimada", "N/I")}.'
        ),
        'impacto': (
            'Sem qualidade de segurado, o(a) segurado(a) não tem direito a nenhum benefício '
            'do INSS em caso de doença, acidente ou óbito. Caso venha a precisar de '
            'auxílio-doença, aposentadoria por invalidez ou seus dependentes necessitem de '
            'pensão por morte, o INSS negará o pedido.'
        ),
    }


def _conclusao_pendencias(pendencias: list[dict], vinculos: list[dict]) -> Optional[dict]:
    """Gera problema de pendências bloqueando períodos.

    Retorna estrutura com frase de abertura curta + `tabela_pendencias`
    (lista de dicts) para o template renderizar como cards legíveis
    em vez de um único parágrafo denso.
    """
    if not pendencias:
        return None

    tabela_pendencias = []
    for p in pendencias:
        vinculos_afetados = []
        for v in vinculos:
            if p['codigo'] in v.get('indicadores_vinculo', []):
                vinculos_afetados.append(v.get('empregador', 'N/I'))
            for rem in v.get('remuneracoes', []):
                if p['codigo'] in rem.get('indicadores', []):
                    vinculos_afetados.append(
                        f'{v.get("empregador", "N/I")} (comp. {rem.get("competencia", "N/I")})'
                    )
        vinculos_afetados = list(set(vinculos_afetados))
        onde = '; '.join(vinculos_afetados[:5]) if vinculos_afetados else 'vínculo não identificado'

        # Separa descrição do procedimento, quando a descrição trouxer
        # a sentença "Procedimento: ..." (padrão da base de indicadores).
        descricao_raw = p.get('descricao', '') or ''
        descricao_limpa = descricao_raw
        procedimento = ''
        if 'Procedimento:' in descricao_raw:
            partes = descricao_raw.split('Procedimento:', 1)
            descricao_limpa = partes[0].strip().rstrip('.').strip()
            procedimento = partes[1].strip()

        tabela_pendencias.append({
            'codigo': p['codigo'],
            'nome': p['nome'],
            'descricao': descricao_limpa,
            'procedimento': procedimento,
            'onde': onde,
        })

    return {
        'problema': (
            f'Foram identificadas {len(pendencias)} pendência(s) no extrato que bloqueiam '
            f'o cômputo de períodos contributivos.'
        ),
        'tabela_pendencias': tabela_pendencias,
        'impacto': (
            'Enquanto essas pendências não forem resolvidas, o INSS desconsiderará os '
            'períodos afetados no cálculo do tempo de contribuição e da carência. Isso pode '
            'atrasar a aposentadoria, reduzir o valor do benefício ou gerar uma negativa '
            'na hora de requerer o benefício.'
        ),
    }


def _agrupar_por_empregador(itens: list[dict]) -> list[dict]:
    """Agrupa lista de competências por empregador, mostrando até 10 competências
    e o valor médio nominal/corrigido (INPC) das competências do grupo."""
    por_emp = {}
    for it in itens:
        emp = it.get('empregador', 'N/I')
        por_emp.setdefault(emp, []).append(it)
    out = []
    for emp, lista in por_emp.items():
        comps = ', '.join(i['competencia'] for i in lista[:10])
        if len(lista) > 10:
            comps += f' e mais {len(lista) - 10}'
        tipos = sorted({i.get('tipo_competencia', '') for i in lista if i.get('tipo_competencia')})
        valores = [i.get('valor') for i in lista if i.get('valor') is not None]
        valores_corr = [i.get('valor_corrigido') for i in lista if i.get('valor_corrigido') is not None]
        media_nominal = round(sum(valores) / len(valores), 2) if valores else None
        media_corr = round(sum(valores_corr) / len(valores_corr), 2) if valores_corr else None
        out.append({
            'empregador': emp,
            'qtd': len(lista),
            'competencias': comps,
            'tipo_competencia': ' / '.join(tipos) if tipos else '',
            'valor_medio_nominal': media_nominal,
            'valor_medio_corrigido': media_corr,
        })
    return out


def _conclusao_abaixo_minimo(
    abaixo_minimo: list[dict],
    psc_men_sm: Optional[list[dict]] = None,
    prec_menor: Optional[list[dict]] = None,
) -> Optional[dict]:
    """Gera problema de salários abaixo do mínimo.

    Sprint 2: PSC-MEN-SM-EC103 e PREC-MENOR-MIN agora vêm prontos dos
    indicadores extraídos pelo parser (mais fiel ao CNIS), não do recorte
    abaixo_minimo. Mantemos o cálculo próprio (`abaixo_minimo`) como
    sinalização adicional de qualidade de contribuição.
    """
    psc = psc_men_sm if psc_men_sm is not None else (
        [x for x in (abaixo_minimo or []) if x.get('indicador_oficial') == 'PSC-MEN-SM-EC103']
    )
    prec = prec_menor if prec_menor is not None else (
        [x for x in (abaixo_minimo or []) if x.get('indicador_oficial') == 'PREC-MENOR-MIN']
    )

    if not abaixo_minimo and not psc and not prec:
        return None

    total = len(set(
        (x.get('vinculo_seq'), x.get('competencia'))
        for x in (abaixo_minimo or []) + psc + prec
    ))

    return {
        'problema': (
            f'Foram identificadas {total} competência(s) com salário de '
            f'contribuição abaixo do mínimo vigente na época, classificadas em dois '
            f'indicadores oficiais do INSS conforme a data.'
        ),
        # Mantém chave legada pra retrocompatibilidade do template
        'tabela_abaixo_minimo': _agrupar_por_empregador(abaixo_minimo or []),
        # Recortes novos
        'tabela_psc_men_sm_ec103': _agrupar_por_empregador(psc),
        'tabela_prec_menor_min': _agrupar_por_empregador(prec),
        'total_psc_men_sm_ec103': len(psc),
        'total_prec_menor_min': len(prec),
        'impacto': (
            'Contribuições abaixo do salário mínimo NÃO contam para carência e NÃO são '
            'computadas no tempo de contribuição. O(a) segurado(a) pode estar com menos '
            'tempo de contribuição do que imagina, o que pode atrasar significativamente '
            'a data da aposentadoria ou resultar em um benefício com valor menor do que '
            'teria direito.'
        ),
        'acao_psc_men_sm_ec103': (
            'Para competências PSC-MEN-SM-EC103 (a partir de 11/2019): solicitar os '
            'Ajustes do Art. 29 da EC 103/2019 (complementação, utilização ou '
            'agrupamento) via canal de atendimento remoto do Meu INSS. Após processamento '
            'do DARF de complementação, o indicador é removido e a competência passa a '
            'contar normalmente para carência e tempo de contribuição.'
        ),
        'acao_prec_menor_min': (
            'Para competências PREC-MENOR-MIN (anteriores a 11/2019): a regularização '
            'depende de análise jurídica caso a caso — pode envolver recolhimento '
            'complementar com base na jurisprudência aplicável. Recomenda-se avaliação '
            'previdenciária específica antes de iniciar o procedimento.'
        ),
    }


def _conclusao_mei_simplificado(indicadores_info: dict, vinculos: list[dict]) -> Optional[dict]:
    """Gera problema de contribuições MEI/simplificado."""
    alertas_mei = [a for a in indicadores_info.get('alertas', [])
                   if a['codigo'] in ('IREC-LC123', 'IREC-MEI', 'IREC-FBR')]
    if not alertas_mei:
        return None

    vinculos_mei = []
    for v in vinculos:
        inds_v = set(v.get('indicadores_vinculo', []))
        for rem in v.get('remuneracoes', []):
            inds_v.update(rem.get('indicadores', []))
        codigos_mei = inds_v & {'IREC-LC123', 'IREC-MEI', 'IREC-FBR'}
        if codigos_mei:
            tipos_v = []
            if 'IREC-MEI' in codigos_mei:
                tipos_v.append('MEI 5%')
            if 'IREC-LC123' in codigos_mei:
                tipos_v.append('plano simplificado 11%')
            if 'IREC-FBR' in codigos_mei:
                tipos_v.append('facultativo baixa renda 5%')
            periodo = f'{v.get("data_inicio", "N/I")} a {v.get("data_fim", "atual")}'
            vinculos_mei.append(
                f'{v.get("empregador", "N/I")} ({periodo}) — {", ".join(tipos_v)}'
            )

    lista_mei = '; '.join(vinculos_mei) if vinculos_mei else 'vínculos não identificados'
    return {
        'problema': (
            f'O extrato contém contribuições que NÃO dão direito à Aposentadoria por '
            f'Tempo de Contribuição. Vínculos afetados: {lista_mei}.'
        ),
        'impacto': (
            'Essas contribuições servem apenas para Aposentadoria por Idade. Se o(a) '
            'segurado(a) pretende se aposentar por tempo de contribuição ou utilizar '
            'regras de transição, esses períodos não serão contados, o que pode atrasar '
            'a aposentadoria em anos.'
        ),
    }


def _conclusao_lacunas(lacunas_lista: list[dict]) -> Optional[dict]:
    """Gera problema de lacunas contributivas."""
    if not lacunas_lista:
        return None

    tabela_lacunas = []
    for lac in lacunas_lista:
        tabela_lacunas.append({
            'de': lac['data_fim'],
            'empregador_anterior': lac['empregador_anterior'],
            'ate': lac['data_inicio'],
            'empregador_posterior': lac['empregador_posterior'],
            'duracao': lac['anos_meses'],
            'gravidade': lac['gravidade'],
        })
    return {
        'problema': (
            f'Foram identificadas {len(lacunas_lista)} lacuna(s) contributiva(s) no extrato.'
        ),
        'impacto': (
            'Lacunas representam períodos sem contribuição ao INSS. Além de reduzir o '
            'tempo total de contribuição, lacunas longas podem causar a perda da qualidade '
            'de segurado, impactar negativamente a carência para benefícios e atrasar '
            'a data da aposentadoria.'
        ),
        'tabela_lacunas': tabela_lacunas,
    }


def _conclusao_vinculos_sem_fim(vinculos_sem_fim: list[dict]) -> Optional[dict]:
    """Gera problema de vínculos sem data de saída.

    Retorna estrutura com frase curta + `tabela_vinculos_sem_fim` para
    o template renderizar a lista de vínculos como tabela legível.
    """
    if not vinculos_sem_fim:
        return None

    tabela = [
        {
            'empregador': vsf.get('empregador', 'N/I'),
            'data_inicio': vsf.get('data_inicio', ''),
        }
        for vsf in vinculos_sem_fim
    ]
    return {
        'problema': (
            f'Foram identificados {len(vinculos_sem_fim)} vínculo(s) sem data de saída '
            f'registrada no CNIS, mas com outro(s) vínculo(s) posterior(es).'
        ),
        'tabela_vinculos_sem_fim': tabela,
        'impacto': (
            'Nessa situação, o INSS não considera automaticamente o período do vínculo sem '
            'data de rescisão para fins previdenciários (contagem de tempo de contribuição e '
            'carência). Como consta outro vínculo começando depois, presume-se que o anterior '
            'deveria ter sido encerrado, e o INSS exige a regularização antes de computar o '
            'período. Isso pode atrasar a aposentadoria e reduzir o tempo de contribuição '
            'reconhecido.'
        ),
        'acao': (
            'Solicitar ACERTO DO CNIS pelo Portal Meu INSS ou Portal CNIS para incluir a '
            'data de rescisão correta do(s) vínculo(s) acima, anexando CTPS, TRCT ou outro '
            'documento que comprove a data de saída. Sem esse acerto, o período não será '
            'considerado pelo INSS para fins previdenciários.'
        ),
    }


def _conclusao_moeda_antiga(moeda_antiga: list[dict]) -> Optional[dict]:
    """Gera problema de remunerações em moeda antiga."""
    if not moeda_antiga:
        return None

    por_emp_ma = {}
    for item in moeda_antiga:
        emp = item.get('empregador', 'N/I')
        if emp not in por_emp_ma:
            por_emp_ma[emp] = {'competencias': [], 'seq': item.get('vinculo_seq', '')}
        por_emp_ma[emp]['competencias'].append(item['competencia'])

    tabela_moeda = []
    for emp, dados in por_emp_ma.items():
        comps = dados['competencias']
        periodo = f'{comps[0]} a {comps[-1]}' if len(comps) > 1 else comps[0]
        tabela_moeda.append({
            'empregador': emp,
            'periodo': periodo,
            'qtd': len(comps),
        })

    return {
        'problema': (
            f'O extrato contém {len(moeda_antiga)} remuneração(ões) registrada(s) em '
            'moeda antiga (Cruzeiro, Cruzado, etc.).'
        ),
        'impacto': (
            'Se a conversão para o Real não estiver correta, o valor do salário de '
            'contribuição será calculado abaixo do real, resultando em uma aposentadoria '
            'com valor menor do que o(a) segurado(a) teria direito.'
        ),
        'tabela_moeda': tabela_moeda,
    }


def _conclusao_indicadores_pendentes(indicadores_info: dict, vinculos: list[dict]) -> Optional[dict]:
    """Gera problema de indicadores pendentes (INDPEND)."""
    alertas_indpend = [a for a in indicadores_info.get('alertas', [])
                       if a['codigo'] in ('IREC-INDPEND', 'IREM-INDPEND')]
    if not alertas_indpend:
        return None

    tabela_indpend = []
    for v in vinculos:
        inds_v = set(v.get('indicadores_vinculo', []))
        encontrados_v = inds_v & {'IREC-INDPEND', 'IREM-INDPEND'}
        if encontrados_v:
            tabela_indpend.append({
                'empregador': v.get('empregador', 'N/I'),
                'competencia': 'Vínculo inteiro',
                'indicador': ', '.join(encontrados_v),
            })
        for rem in v.get('remuneracoes', []):
            inds_rem = set(rem.get('indicadores', []))
            encontrados = inds_rem & {'IREC-INDPEND', 'IREM-INDPEND'}
            if encontrados:
                tabela_indpend.append({
                    'empregador': v.get('empregador', 'N/I'),
                    'competencia': rem.get('competencia', 'N/I'),
                    'indicador': ', '.join(encontrados),
                })

    return {
        'problema': (
            f'Foram identificados {len(tabela_indpend)} registro(s) com indicadores '
            'pendentes que sinalizam problemas.'
        ),
        'impacto': (
            'As contribuições afetadas podem não ser consideradas pelo INSS no cálculo '
            'do tempo de contribuição e do valor do benefício até que sejam resolvidos. '
            'Isso pode atrasar a aposentadoria ou reduzir seu valor.'
        ),
        'tabela_indpend': tabela_indpend,
    }


# PARÁGRAFOS FIXOS (sempre ao final da conclusão)
_PARAGRAFOS_FIXOS = [
    'Ressaltamos que todas as conclusões aqui apresentadas estão fundamentadas na '
    'legislação previdenciária vigente, podendo sofrer alterações caso o INSS ou o '
    'legislador promovam mudanças nas regras atualmente aplicáveis.',

    'Informo, ainda, que a análise foi realizada a partir da documentação '
    'apresentada pelo requerente, qual seja, CNIS.',

    'Colocamo-nos à disposição para auxiliar em todas as etapas do processo e '
    'esclarecer quaisquer dúvidas que possam surgir durante a correção das '
    'pendências analisadas nesta análise de CNIS, estando nossa equipe disponível, '
    'especialmente, nas próximas 48 horas úteis para sanar todas as dúvidas.',
]


def gerar_conclusao(cabecalho, qualidade, indicadores_info, lacunas_info,
                    remuneracoes_info, verificacoes_info, tempo_info, vinculos) -> dict:
    """Gera a conclusão completa da análise de CNIS.

    Para cada problema encontrado, lista:
      1. O problema (o que foi encontrado)
      2. O impacto na vida do segurado (negativa do INSS, aposentadoria menor, demora)

    NÃO apresenta soluções — a Análise de CNIS apresenta apenas os problemas.
    """
    nome = cabecalho.get('nome', 'N/I')
    problemas = []

    # Executar cada detector de problema
    detectores = [
        _conclusao_perda_qualidade(nome, qualidade),
        _conclusao_pendencias(indicadores_info.get('pendencias', []), vinculos),
        _conclusao_abaixo_minimo(
            remuneracoes_info.get('abaixo_minimo', []),
            psc_men_sm=remuneracoes_info.get('psc_men_sm_ec103'),
            prec_menor=remuneracoes_info.get('prec_menor_min'),
        ),
        _conclusao_mei_simplificado(indicadores_info, vinculos),
        _conclusao_lacunas(lacunas_info.get('lista', [])),
        _conclusao_vinculos_sem_fim(verificacoes_info.get('vinculos_sem_fim', [])),
        _conclusao_moeda_antiga(remuneracoes_info.get('moeda_antiga', [])),
        _conclusao_indicadores_pendentes(indicadores_info, vinculos),
    ]

    for resultado in detectores:
        if resultado is not None:
            problemas.append(resultado)

    # Parágrafo de abertura
    if problemas:
        paragrafo_abertura = (
            f'Diante da análise realizada no extrato de CNIS do(a) Sr(a). {nome}, '
            f'foram identificados {len(problemas)} problema(s) que podem impactar diretamente '
            'a concessão, o valor e o tempo da aposentadoria. É fundamental que esses problemas '
            'sejam corrigidos para evitar negativas do INSS, aposentadoria com valor inferior '
            'ao devido ou demora maior do que o necessário para se aposentar.'
        )
    else:
        paragrafo_abertura = (
            f'Diante da análise realizada no extrato de CNIS do(a) Sr(a). {nome}, '
            'não foram identificados problemas que impeçam ou prejudiquem a concessão de '
            'benefícios previdenciários. O extrato encontra-se em boas condições.'
        )

    return {
        'problemas': problemas,
        'total_problemas': len(problemas),
        'paragrafo_abertura': paragrafo_abertura,
        'paragrafos_fixos': list(_PARAGRAFOS_FIXOS),
    }


# ============================================================================
#  FUNÇÃO PRINCIPAL DE ANÁLISE
# ============================================================================

def analisar_cnis(dados_parser: dict) -> dict:
    """Função principal: analisa dados do CNIS já parseados.

    Args:
        dados_parser: Dicionário retornado pelo cnis_parser.parse_cnis()

    Returns:
        Dicionário com análise completa
    """
    if not dados_parser.get('sucesso') or not dados_parser.get('dados'):
        return {
            'sucesso': False,
            'erro': dados_parser.get('erro', 'Dados do parser inválidos'),
        }

    dados = dados_parser['dados']
    cabecalho = dados['cabecalho']
    vinculos = dados['vinculos']

    # Carregar configurações
    dicionario_indicadores = carregar_indicadores()
    tabela_sm = carregar_salarios_minimos()
    serie_inpc = carregar_serie_inpc()

    # 1. Classificar todos os indicadores
    # Indicadores cujo escopo é SÓ vínculo de empregado (CJ filtra esses).
    # IREM-* (Indicador de REMuneração) faz sentido só onde existe
    # remuneração CLT — para Contribuinte Individual o equivalente é
    # IREC-INDPEND (Indicador de REColhimento).
    _IND_SOMENTE_EMPREGADO = {'IREM-INDPEND', 'IREM-ACD'}
    _TIPOS_EMPREGADO = {'Empregado', 'Empregado Doméstico', 'Agente Público', 'Trabalhador Avulso'}

    todos_indicadores = set()
    contagem_ocorrencias: dict[str, int] = {}
    contagem_vinculos_distintos: dict[str, set] = {}

    for v in vinculos:
        if v.get('eh_beneficio'):
            continue
        seq = v.get('seq')
        tipo_v = v.get('tipo', '')
        eh_empregado = tipo_v in _TIPOS_EMPREGADO
        inds_neste_vinculo = set()
        for ind in v.get('indicadores_vinculo', []):
            if ind in _IND_SOMENTE_EMPREGADO and not eh_empregado:
                continue
            inds_neste_vinculo.add(ind)
            contagem_ocorrencias[ind] = contagem_ocorrencias.get(ind, 0) + 1
        for r in v.get('remuneracoes', []):
            for ind in r.get('indicadores', []):
                if ind in _IND_SOMENTE_EMPREGADO and not eh_empregado:
                    continue
                contagem_ocorrencias[ind] = contagem_ocorrencias.get(ind, 0) + 1
                inds_neste_vinculo.add(ind)
        for ind in inds_neste_vinculo:
            contagem_vinculos_distintos.setdefault(ind, set()).add(seq)
        todos_indicadores.update(inds_neste_vinculo)

    indicadores_classificados = classificar_indicadores(
        list(todos_indicadores), dicionario_indicadores
    )
    # Anota cada indicador com contagem de ocorrências e de vínculos distintos.
    # Para indicadores de competência (PREM-*, IREM-ACD, PSC-*, PREC-*) a
    # `total_ocorrencias` é a métrica relevante; para indicadores de vínculo
    # (IREM-INDPEND, IREC-INDPEND, IVIN-*, PVIN-*, PRPPS, PEXT, PADM-*,
    # AVRC-*, AEXT-*, IEAN) a `total_vinculos` é o que o Cálculo Jurídico
    # exibe na aba "Períodos com Indicadores".
    for item in indicadores_classificados:
        cod = item['codigo']
        item['total_ocorrencias'] = contagem_ocorrencias.get(cod, 0)
        item['total_vinculos'] = len(contagem_vinculos_distintos.get(cod, set()))

    # Separar por tipo
    pendencias = [i for i in indicadores_classificados if i['tipo'] == 'PENDENCIA']
    alertas = [i for i in indicadores_classificados if i['tipo'] == 'ALERTA']
    acertos = [i for i in indicadores_classificados if i['tipo'] == 'ACERTO']
    desconhecidos = [i for i in indicadores_classificados if i['tipo'] == 'DESCONHECIDO']

    # 2. Calcular lacunas
    lacunas = calcular_lacunas(vinculos)

    # 3. Analisar remunerações
    analise_remuneracoes = analisar_remuneracoes(vinculos, tabela_sm, serie_inpc)

    # 4. Qualidade de segurado
    qualidade = avaliar_qualidade_segurado(vinculos, cabecalho.get('data_emissao', ''))

    # 5. Tempo de contribuição
    tempo = estimar_tempo_contribuicao(vinculos)

    # 6. Verificações adicionais
    sobreposicoes = verificar_sobreposicoes(vinculos)
    vinculos_sem_fim = verificar_vinculos_sem_fim(vinculos)

    # 7. Calcular idade do segurado
    idade = None
    if cabecalho.get('data_nascimento'):
        dn = parse_data_str(cabecalho['data_nascimento'])
        if dn:
            hoje = date.today()
            anos = hoje.year - dn.year - ((hoje.month, hoje.day) < (dn.month, dn.day))
            meses_idade = (hoje.month - dn.month) % 12
            dias_idade = (hoje.day - dn.day) % 30
            idade = {
                'anos': anos,
                'meses': meses_idade,
                'dias': dias_idade,
                'descricao': f'{anos} anos, {meses_idade} meses e {dias_idade} dias',
            }

    # 7.1 Avisos sobre benefícios presentes no CNIS (Sprint 2 #D)
    avisos_beneficios = detectar_avisos_beneficios(vinculos)

    # 8. Gerar conclusão detalhada
    conclusao = gerar_conclusao(
        cabecalho=cabecalho,
        qualidade=qualidade,
        indicadores_info={
            'pendencias': pendencias,
            'alertas': alertas,
            'acertos': acertos,
            'desconhecidos': desconhecidos,
        },
        lacunas_info={
            'total': len(lacunas),
            'lista': lacunas,
            'gravidade_maxima': max(
                (l['gravidade'] for l in lacunas),
                key=lambda g: {'BAIXA': 1, 'MEDIA': 2, 'ALTA': 3, 'CRITICA': 4}.get(g, 0),
                default='NENHUMA'
            ) if lacunas else 'NENHUMA',
            'maior_lacuna_meses': max((l['meses'] for l in lacunas), default=0),
        },
        remuneracoes_info=analise_remuneracoes,
        verificacoes_info={
            'vinculos_sem_fim': vinculos_sem_fim,
        },
        tempo_info=tempo,
        vinculos=vinculos,
    )

    # 9. Montar resultado
    resultado = {
        'sucesso': True,
        'data_analise': date.today().strftime('%d/%m/%Y'),
        'cabecalho': cabecalho,
        'idade': idade,
        'qualidade_segurado': qualidade,
        'tempo_contribuicao': tempo,
        'avisos_beneficios': avisos_beneficios,
        'vinculos': vinculos,
        'indicadores': {
            'todos': indicadores_classificados,
            'pendencias': pendencias,
            'alertas': alertas,
            'acertos': acertos,
            'desconhecidos': desconhecidos,
            'total_pendencias': len(pendencias),
            'total_alertas': len(alertas),
            'total_acertos': len(acertos),
            'total_desconhecidos': len(desconhecidos),
        },
        'lacunas': {
            'lista': lacunas,
            'total': len(lacunas),
            'gravidade_maxima': max(
                (l['gravidade'] for l in lacunas),
                key=lambda g: {'BAIXA': 1, 'MEDIA': 2, 'ALTA': 3, 'CRITICA': 4}.get(g, 0),
                default='NENHUMA'
            ) if lacunas else 'NENHUMA',
            'maior_lacuna_meses': max((l['meses'] for l in lacunas), default=0),
        },
        'remuneracoes': analise_remuneracoes,
        'verificacoes': {
            'sobreposicoes': sobreposicoes,
            'vinculos_sem_fim': vinculos_sem_fim,
            'total_anomalias': len(sobreposicoes) + len(vinculos_sem_fim),
        },
        'conclusao': conclusao,
        'resumo': {
            'nome': cabecalho.get('nome', 'N/I'),
            'cpf': cabecalho.get('cpf', 'N/I'),
            'total_vinculos': len(vinculos),
            'total_pendencias': len(pendencias),
            'total_alertas': len(alertas),
            'tempo_contribuicao': tempo['descricao'],
            'qualidade_segurado': qualidade['status'],
            'total_lacunas': len(lacunas),
            'total_abaixo_minimo': analise_remuneracoes['total_abaixo_minimo'],
            'total_problemas': conclusao['total_problemas'],
        },
    }

    return resultado


# ============================================================================
#  PONTO DE ENTRADA
# ============================================================================

if __name__ == '__main__':
    # Lê JSON do parser via stdin
    dados_stdin = sys.stdin.read()

    try:
        dados_parser = json.loads(dados_stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({
            'sucesso': False,
            'erro': f'JSON inválido recebido do parser: {str(e)}',
        }))
        sys.exit(1)

    resultado = analisar_cnis(dados_parser)
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
