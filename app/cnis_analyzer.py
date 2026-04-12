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
from typing import Optional
from pathlib import Path


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
    """Calcula lacunas entre vínculos consecutivos.

    Ordena vínculos por data_inicio e calcula intervalos.
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

    # Ordenar por data de início
    vinculos_emprego.sort(key=lambda v: parse_data_str(v['data_inicio']) or date.min)

    lacunas = []
    for i in range(len(vinculos_emprego) - 1):
        data_fim_atual = parse_data_str(vinculos_emprego[i]['data_fim'])
        data_inicio_prox = parse_data_str(vinculos_emprego[i + 1]['data_inicio'])

        if not data_fim_atual or not data_inicio_prox:
            continue

        # Calcular diferença em meses
        diff_dias = (data_inicio_prox - data_fim_atual).days
        if diff_dias <= 31:  # Até 1 mês não é lacuna
            continue

        meses = diff_dias // 30

        # Classificar gravidade
        if meses <= 3:
            gravidade = 'BAIXA'
        elif meses <= 12:
            gravidade = 'MEDIA'
        elif meses <= 24:
            gravidade = 'ALTA'
        else:
            gravidade = 'CRITICA'

        lacunas.append({
            'vinculo_anterior': vinculos_emprego[i]['seq'],
            'vinculo_posterior': vinculos_emprego[i + 1]['seq'],
            'empregador_anterior': vinculos_emprego[i].get('empregador', 'N/I'),
            'empregador_posterior': vinculos_emprego[i + 1].get('empregador', 'N/I'),
            'data_fim': vinculos_emprego[i]['data_fim'],
            'data_inicio': vinculos_emprego[i + 1]['data_inicio'],
            'dias': diff_dias,
            'meses': meses,
            'anos_meses': f"{meses // 12} ano(s) e {meses % 12} mês(es)" if meses >= 12 else f"{meses} mês(es)",
            'gravidade': gravidade,
        })

    return lacunas


# ============================================================================
#  VERIFICAÇÃO DE REMUNERAÇÕES VS SALÁRIO MÍNIMO
# ============================================================================

def analisar_remuneracoes(vinculos: list[dict], tabela_sm: list[dict]) -> dict:
    """Analisa remunerações: identifica abaixo do SM, proporcionais, etc."""
    abaixo_minimo = []
    proporcionais = []
    moeda_antiga = []
    total_competencias = 0

    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue

        data_inicio = parse_data_str(vinculo.get('data_inicio', ''))
        data_fim = parse_data_str(vinculo.get('data_fim', ''))

        for rem in vinculo.get('remuneracoes', []):
            comp = rem.get('competencia')
            valor = rem.get('valor')

            if not comp or valor is None:
                continue

            total_competencias += 1

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
            if valor < sm * 0.95:
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
                        'dias_trabalhados': dias_trabalhados,
                        'nota': f'Proporcional — rescisão em {vinculo.get("data_fim", "N/I")} ({dias_trabalhados} dias)',
                    })

                if not eh_proporcional:
                    abaixo_minimo.append({
                        'competencia': comp,
                        'valor': valor,
                        'salario_minimo': sm,
                        'diferenca': round(sm - valor, 2),
                        'percentual': round((valor / sm) * 100, 1),
                        'vinculo_seq': vinculo['seq'],
                        'empregador': vinculo.get('empregador', 'N/I'),
                    })

    return {
        'total_competencias_analisadas': total_competencias,
        'abaixo_minimo': abaixo_minimo,
        'proporcionais': proporcionais,
        'moeda_antiga': moeda_antiga,
        'total_abaixo_minimo': len(abaixo_minimo),
        'total_proporcionais': len(proporcionais),
        'total_moeda_antiga': len(moeda_antiga),
    }


# ============================================================================
#  QUALIDADE DE SEGURADO (PERÍODO DE GRAÇA)
# ============================================================================

def avaliar_qualidade_segurado(vinculos: list[dict], data_extrato: str) -> dict:
    """Avalia se o segurado mantém qualidade de segurado na data do extrato.

    Regras do período de graça:
    - CLT/Empregado: 12 meses após última contribuição
    - CI/MEI/Facultativo com ≥120 contribuições: 24 meses
    - +12 meses se desemprego involuntário (não verificável automaticamente)
    """
    data_ref = parse_data_str(data_extrato) or date.today()

    # Encontrar última contribuição válida
    ultima_competencia = None
    ultima_data = None
    tipo_ultimo_vinculo = None
    total_contribuicoes = 0

    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue

        tipo_v = vinculo.get('tipo', '')
        for rem in vinculo.get('remuneracoes', []):
            comp = rem.get('competencia')
            if not comp:
                continue

            total_contribuicoes += 1

            try:
                mes, ano = comp.split('/')
                data_comp = date(int(ano), int(mes), 1)
            except (ValueError, AttributeError):
                continue

            if ultima_data is None or data_comp > ultima_data:
                ultima_data = data_comp
                ultima_competencia = comp
                tipo_ultimo_vinculo = tipo_v

    if not ultima_data:
        return {
            'status': 'INDETERMINADO',
            'mensagem': 'Não foram encontradas contribuições válidas no extrato.',
            'ultima_contribuicao': None,
            'periodo_graca_meses': 0,
            'data_perda_estimada': None,
        }

    # Determinar período de graça
    periodo_graca = 12  # Base: 12 meses

    # Se tem 120+ contribuições, +12 meses
    if total_contribuicoes >= 120:
        periodo_graca = 24

    # Calcular data estimada de perda
    # Adicionar meses ao último mês de contribuição
    mes_perda = ultima_data.month + periodo_graca
    ano_perda = ultima_data.year + (mes_perda - 1) // 12
    mes_perda = ((mes_perda - 1) % 12) + 1
    try:
        data_perda = date(ano_perda, mes_perda, 1)
    except ValueError:
        data_perda = date(ano_perda, mes_perda, 28)

    # Avaliar status
    if data_ref <= data_perda:
        meses_restantes = (data_perda.year - data_ref.year) * 12 + (data_perda.month - data_ref.month)
        status = 'MANTIDA'
        mensagem = (
            f'O(a) segurado(a) possui qualidade de segurado. '
            f'A última contribuição registrada foi em {ultima_competencia}. '
            f'O período de graça de {periodo_graca} meses se estende até '
            f'{data_perda.strftime("%m/%Y")} ({meses_restantes} meses restantes).'
        )
    else:
        anos_sem = (data_ref.year - data_perda.year)
        status = 'PERDIDA'
        mensagem = (
            f'O(a) segurado(a) PERDEU a qualidade de segurado. '
            f'A última contribuição foi em {ultima_competencia} e o período de graça '
            f'de {periodo_graca} meses expirou em {data_perda.strftime("%m/%Y")} '
            f'(há aproximadamente {anos_sem} ano(s)). Para recuperar, são necessárias '
            f'6 contribuições válidas consecutivas (50% da carência de 12 meses).'
        )

    return {
        'status': status,
        'mensagem': mensagem,
        'ultima_contribuicao': ultima_competencia,
        'tipo_ultimo_vinculo': tipo_ultimo_vinculo,
        'total_contribuicoes': total_contribuicoes,
        'periodo_graca_meses': periodo_graca,
        'data_perda_estimada': data_perda.strftime('%d/%m/%Y'),
    }


# ============================================================================
#  ESTIMATIVA DE TEMPO DE CONTRIBUIÇÃO
# ============================================================================

def estimar_tempo_contribuicao(vinculos: list[dict]) -> dict:
    """Estima o tempo total de contribuição válido.

    Conta meses com remuneração para vínculos de emprego.
    Para vínculos sem remunerações detalhadas, estima pela duração.
    """
    total_dias = 0
    periodos = []

    for vinculo in vinculos:
        if vinculo.get('eh_beneficio'):
            continue

        data_inicio = parse_data_str(vinculo.get('data_inicio', ''))
        data_fim = parse_data_str(vinculo.get('data_fim', ''))

        if data_inicio and data_fim:
            dias = (data_fim - data_inicio).days + 1  # Inclui o dia
            if dias > 0:
                total_dias += dias
                periodos.append({
                    'vinculo_seq': vinculo['seq'],
                    'empregador': vinculo.get('empregador', 'N/I'),
                    'inicio': vinculo['data_inicio'],
                    'fim': vinculo['data_fim'],
                    'dias': dias,
                    'meses': round(dias / 30, 1),
                })
        elif data_inicio and not data_fim:
            # Vínculo ativo (sem data fim) — conta até hoje
            hoje = date.today()
            dias = (hoje - data_inicio).days + 1
            if dias > 0:
                total_dias += dias
                periodos.append({
                    'vinculo_seq': vinculo['seq'],
                    'empregador': vinculo.get('empregador', 'N/I'),
                    'inicio': vinculo['data_inicio'],
                    'fim': 'Em aberto (ativo)',
                    'dias': dias,
                    'meses': round(dias / 30, 1),
                })

    # Converter total para anos, meses e dias
    anos = total_dias // 365
    resto = total_dias % 365
    meses = resto // 30
    dias = resto % 30

    return {
        'total_dias': total_dias,
        'anos': anos,
        'meses': meses,
        'dias': dias,
        'descricao': f'{anos} ano(s), {meses} mês(es) e {dias} dia(s)',
        'periodos': periodos,
        'nota': (
            'Estimativa baseada nas datas de início e fim dos vínculos. '
            'Períodos concomitantes (dois empregos simultâneos) podem estar contados em duplicidade. '
            'A contagem oficial é feita pelo INSS considerando apenas contribuições válidas.'
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
    """Identifica vínculos sem data fim que não sejam o mais recente."""
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
            anomalias.append({
                'vinculo_seq': v['seq'],
                'empregador': v.get('empregador', 'N/I'),
                'data_inicio': v['data_inicio'],
                'nota': 'Vínculo sem data de fim e não é o mais recente. Possível inconsistência.',
            })

    return anomalias


# ============================================================================
#  GERAÇÃO DA CONCLUSÃO
# ============================================================================

def gerar_conclusao(cabecalho, qualidade, indicadores_info, lacunas_info,
                    remuneracoes_info, verificacoes_info, tempo_info, vinculos) -> dict:
    """Gera a conclusão completa da análise de CNIS.

    A conclusão identifica os problemas encontrados e seus impactos na
    aposentadoria. NÃO sugere soluções — apenas descreve os problemas.
    """
    nome = cabecalho.get('nome', 'N/I')
    problemas = []

    # 1. QUALIDADE DE SEGURADO
    if qualidade.get('status', '') == 'PERDIDA':
        problemas.append(
            f'O(a) Sr(a). {nome} perdeu a qualidade de segurado(a). '
            f'A última contribuição foi em {qualidade.get("ultima_contribuicao", "N/I")} '
            f'e o período de graça expirou em {qualidade.get("data_perda_estimada", "N/I")}. '
            'Sem qualidade de segurado, não há direito a nenhum benefício do INSS em caso '
            'de doença, acidente ou óbito.'
        )

    # 2. PENDÊNCIAS (INDICADORES P)
    pendencias = indicadores_info.get('pendencias', [])
    if pendencias:
        nomes_pend = ', '.join([p['codigo'] for p in pendencias])
        problemas.append(
            f'Foram identificadas {len(pendencias)} pendência(s) no extrato ({nomes_pend}). '
            'Pendências são bloqueios que impedem o cômputo de períodos contributivos. '
            'Enquanto não forem resolvidas, o INSS pode desconsiderar esses períodos, '
            'o que pode atrasar a aposentadoria ou reduzir o valor do benefício.'
        )

    # 3. SALÁRIOS ABAIXO DO MÍNIMO
    total_abaixo = remuneracoes_info.get('total_abaixo_minimo', 0)
    if total_abaixo > 0:
        problemas.append(
            f'Foram identificadas {total_abaixo} competência(s) com remuneração abaixo do '
            'salário mínimo vigente. Contribuições abaixo do mínimo NÃO contam para carência '
            'e NÃO são computadas no tempo de contribuição. O(a) segurado(a) pode estar com '
            'menos tempo de contribuição do que imagina, o que pode atrasar significativamente '
            'a data da aposentadoria ou resultar em um benefício menor.'
        )

    # 4. CONTRIBUIÇÕES MEI / PLANO SIMPLIFICADO
    alertas_mei = [a for a in indicadores_info.get('alertas', [])
                   if a['codigo'] in ('IREC-LC123', 'IREC-MEI', 'IREC-FBR')]
    if alertas_mei:
        problemas.append(
            'O extrato contém contribuições realizadas no plano simplificado (11% sobre o '
            'salário mínimo) ou como MEI (5%). Essas contribuições NÃO dão direito à '
            'Aposentadoria por Tempo de Contribuição — apenas à Aposentadoria por Idade. '
            'Se o(a) segurado(a) pretende se aposentar por tempo de contribuição ou utilizar '
            'regras de transição, esses períodos não serão contados, o que pode atrasar '
            'a aposentadoria em anos.'
        )

    # 5. LACUNAS CONTRIBUTIVAS
    total_lacunas = lacunas_info.get('total', 0)
    if total_lacunas > 0:
        maior_lacuna = lacunas_info.get('maior_lacuna_meses', 0)
        problemas.append(
            f'Foram identificadas {total_lacunas} lacuna(s) contributiva(s), sendo a maior '
            f'de {maior_lacuna} meses. Lacunas representam períodos sem contribuição ao INSS. '
            'Além de reduzir o tempo total de contribuição, lacunas longas podem causar a '
            'perda da qualidade de segurado e impactar negativamente a carência para benefícios.'
        )

    # 6. VÍNCULOS SEM DATA FIM
    vinculos_sem_fim = verificacoes_info.get('vinculos_sem_fim', [])
    if vinculos_sem_fim:
        problemas.append(
            f'Foram identificados {len(vinculos_sem_fim)} vínculo(s) sem data de saída '
            'registrada. O INSS pode não ter o registro correto da rescisão, o que pode '
            'causar inconsistências no cálculo do tempo de contribuição e dificultar a '
            'concessão do benefício.'
        )

    # 7. REMUNERAÇÕES EM MOEDA ANTIGA
    total_moeda_antiga = remuneracoes_info.get('total_moeda_antiga', 0)
    if total_moeda_antiga > 0:
        problemas.append(
            f'O extrato contém {total_moeda_antiga} remuneração(ões) registrada(s) em moeda '
            'antiga (Cruzeiro, Cruzado, etc.). Se a conversão para o Real não estiver correta, '
            'o valor do benefício pode ser calculado abaixo do devido.'
        )

    # 8. INDICADORES PENDENTES (IREC-INDPEND)
    alertas_indpend = [a for a in indicadores_info.get('alertas', [])
                       if a['codigo'] == 'IREC-INDPEND']
    if alertas_indpend:
        problemas.append(
            'Existem recolhimentos com indicadores pendentes (IREC-INDPEND). Há indícios de '
            'problemas nesses recolhimentos que podem impedir sua contagem. As contribuições '
            'podem não ser consideradas pelo INSS até que sejam resolvidos.'
        )

    # MONTAR TEXTO DA CONCLUSÃO
    paragrafos_problemas = []
    if problemas:
        paragrafos_problemas.append(
            f'Diante da análise realizada no extrato de CNIS do(a) Sr(a). {nome}, '
            f'foram identificados os seguintes problemas que podem impactar diretamente '
            f'a concessão, o valor e o tempo da aposentadoria:'
        )
        for i, prob in enumerate(problemas, 1):
            paragrafos_problemas.append(f'{i}. {prob}')

        paragrafos_problemas.append(
            'Esses problemas, se não corrigidos, podem resultar em negativas do INSS, '
            'aposentadoria com valor inferior ao devido ou demora maior do que o necessário '
            'para se aposentar.'
        )
    else:
        paragrafos_problemas.append(
            f'Diante da análise realizada no extrato de CNIS do(a) Sr(a). {nome}, '
            'não foram identificados problemas graves. O extrato encontra-se em boas condições.'
        )

    # PARÁGRAFOS FIXOS (sempre ao final)
    paragrafos_fixos = [
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

    return {
        'problemas': problemas,
        'total_problemas': len(problemas),
        'paragrafos_problemas': paragrafos_problemas,
        'paragrafos_fixos': paragrafos_fixos,
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

    # 1. Classificar todos os indicadores
    todos_indicadores = set()
    for v in vinculos:
        todos_indicadores.update(v.get('indicadores_vinculo', []))
        for r in v.get('remuneracoes', []):
            todos_indicadores.update(r.get('indicadores', []))

    indicadores_classificados = classificar_indicadores(
        list(todos_indicadores), dicionario_indicadores
    )

    # Separar por tipo
    pendencias = [i for i in indicadores_classificados if i['tipo'] == 'PENDENCIA']
    alertas = [i for i in indicadores_classificados if i['tipo'] == 'ALERTA']
    acertos = [i for i in indicadores_classificados if i['tipo'] == 'ACERTO']
    desconhecidos = [i for i in indicadores_classificados if i['tipo'] == 'DESCONHECIDO']

    # 2. Calcular lacunas
    lacunas = calcular_lacunas(vinculos)

    # 3. Analisar remunerações
    analise_remuneracoes = analisar_remuneracoes(vinculos, tabela_sm)

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
