"""
Parser de CNIS (Cadastro Nacional de Informações Sociais)
Extrai dados estruturados de PDFs do portal Meu INSS.

Entrada: caminho do PDF
Saída: JSON estruturado com cabeçalho, vínculos, remunerações e indicadores
"""

import logging
import re
import json
import sys
from datetime import datetime, date
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


# ============================================================================
#  CONSTANTES E PATTERNS REGEX
# ============================================================================

# Cabeçalho
RE_NIT = re.compile(r'NIT[:\s]*([\d]{3}\.?[\d]{5}\.?[\d]{2}-?[\d]{1})', re.IGNORECASE)
RE_CPF = re.compile(r'CPF[:\s]*([\d]{3}\.?[\d]{3}\.?[\d]{3}-?[\d]{2})', re.IGNORECASE)
RE_NOME = re.compile(
    r'Nome[:\s]+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s]+?)(?:\s{2,}|\s*Data|\s*Nome da [Mm]ãe|\n)',
    re.IGNORECASE
)
RE_DATA_NASCIMENTO = re.compile(
    r'(?:Data\s+de\s+[Nn]ascimento|Nascimento)[:\s]*(\d{2}/\d{2}/\d{4})',
    re.IGNORECASE
)
RE_NOME_MAE = re.compile(
    r'Nome\s+da\s+[Mm]ãe[:\s]+([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s]+?)(?:\s{2,}|\n|$)',
    re.IGNORECASE
)
RE_DATA_EMISSAO = re.compile(
    r'(\d{2}/\d{2}/\d{4})\s+\d{2}:\d{2}:\d{2}',
)

# Vínculos empregatícios
RE_SEQ_VINCULO = re.compile(
    r'^(\d{1,3})\s+',
    re.MULTILINE
)
RE_CNPJ = re.compile(r'(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})')
RE_CEI = re.compile(r'(\d{2}\.\d{3}\.\d{5}/\d{2})')
RE_DATA = re.compile(r'(\d{2}/\d{2}/\d{4})')
RE_COMPETENCIA = re.compile(r'(\d{2}/\d{4})')
RE_VALOR_MONETARIO = re.compile(r'([\d]{1,3}(?:\.[\d]{3})*,[\d]{2})')

# Indicadores
RE_INDICADOR = re.compile(r'([A-Z][A-Z0-9]{1,}(?:-[A-Z0-9]+)*)')

# Tipos de vínculo/filiação
# ORDEM IMPORTA: chaves mais específicas primeiro para evitar match parcial.
# Ex: "EMPREGADO DOMÉSTICO" antes de "EMPREGADO", "SEGURADO ESPECIAL" antes de "CI".
TIPOS_VINCULO = [
    ('EMPREGADO DOMÉSTICO', 'Empregado Doméstico'),
    ('DOMÉSTICO', 'Empregado Doméstico'),
    ('CONTRIBUINTE INDIVIDUAL', 'Contribuinte Individual'),
    ('SEGURADO ESPECIAL', 'Segurado Especial'),
    ('TRABALHADOR AVULSO', 'Trabalhador Avulso'),
    ('AGENTE PÚBLICO', 'Agente Público'),
    ('EMPREGADO', 'Empregado'),
    ('FACULTATIVO', 'Facultativo'),
    ('AVULSO', 'Trabalhador Avulso'),
    ('MEI', 'Microempreendedor Individual'),
    ('CI', 'Contribuinte Individual'),
]

# Marcadores de seção do CNIS
MARCADORES_SECAO = [
    'Relações Previdenciárias',
    'Remunerações',
    'Contribuições',
    'Benefícios',
    'Vínculos',
]


# ============================================================================
#  FUNÇÕES DE PARSING
# ============================================================================

def extrair_texto_pdf(pdf_path: str) -> list[str]:
    """Extrai texto de todas as páginas do PDF."""
    paginas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            paginas.append(texto)
    return paginas


def limpar_texto(texto: str) -> str:
    """Remove espaços extras e normaliza quebras de linha."""
    texto = re.sub(r'\r\n', '\n', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()


def parse_cabecalho(texto_completo: str) -> dict:
    """Extrai dados cadastrais do cabeçalho do CNIS."""
    cabecalho = {
        'nit': None,
        'cpf': None,
        'nome': None,
        'data_nascimento': None,
        'nome_mae': None,
        'data_emissao': None,
    }

    # NIT
    m = RE_NIT.search(texto_completo)
    if m:
        cabecalho['nit'] = m.group(1).strip()

    # CPF
    m = RE_CPF.search(texto_completo)
    if m:
        cabecalho['cpf'] = m.group(1).strip()

    # Nome
    m = RE_NOME.search(texto_completo)
    if m:
        cabecalho['nome'] = m.group(1).strip().upper()

    # Data de nascimento
    m = RE_DATA_NASCIMENTO.search(texto_completo)
    if m:
        cabecalho['data_nascimento'] = m.group(1)

    # Nome da mãe
    m = RE_NOME_MAE.search(texto_completo)
    if m:
        cabecalho['nome_mae'] = m.group(1).strip().upper()

    # Data de emissão do extrato
    m = RE_DATA_EMISSAO.search(texto_completo)
    if m:
        cabecalho['data_emissao'] = m.group(1)

    return cabecalho


def converter_valor(texto_valor: str) -> Optional[float]:
    """Converte valor monetário brasileiro (1.234,56) para float."""
    if not texto_valor:
        return None
    try:
        limpo = texto_valor.replace('.', '').replace(',', '.')
        return float(limpo)
    except (ValueError, AttributeError):
        logger.warning("Falha ao converter valor monetário: %r", texto_valor)
        return None


def parse_data(texto_data: str) -> Optional[date]:
    """Converte data no formato DD/MM/AAAA para objeto date."""
    if not texto_data:
        return None
    try:
        return datetime.strptime(texto_data.strip(), '%d/%m/%Y').date()
    except ValueError:
        logger.warning("Falha ao converter data: %r", texto_data)
        return None


def parse_competencia(texto_comp: str) -> Optional[str]:
    """Valida e normaliza competência no formato MM/AAAA."""
    if not texto_comp:
        return None
    m = RE_COMPETENCIA.match(texto_comp.strip())
    if m:
        return m.group(1)
    return None


def extrair_indicadores_linha(linha: str) -> list[str]:
    """Extrai códigos de indicadores de uma linha de texto.

    Reconhece:
      1) Códigos com hífen e/ou underscore (regex genérica) — pega a maioria
         (ex.: IREC-LC123, PREC-MENOR-MIN, PSC-MEN-SM-EC103, PREC-COD1821_FORA_VIG).
      2) Códigos curtos sem hífen mapeados explicitamente no allowlist
         (ex.: GFIP, IDT, ILEI123, IMEI, IRECOL, ISALMIN, NDET, PEXT, IEAN, PRPPS).
      3) Códigos com cedilha (IVIN-DESLIG-JUSTIÇA-TRAB) — checados literalmente
         antes de aplicar a regex genérica para evitar fragmentação.

    Palavras simples em maiúsculas (BANCO, TURISMO, LTDA) NÃO são indicadores.
    """
    # Allowlist de códigos curtos sem hífen — registry tem entradas como
    # IRECOL, GFIP, IMEI, ILEI123 que a regex de hífen sozinha não captura.
    indicadores_sem_hifen = {
        # Originais
        'PEXT', 'IEAN', 'PRPPS', 'PRPSE', 'AVRC-DEF', 'AEXT-VT', 'ACNISVR',
        # Curtos sem hífen do registry
        'GFIP', 'IDT', 'ILEI123', 'IMEI', 'IRECOL', 'ISALMIN', 'NDET',
    }

    # Códigos com caractere especial (Ç) que precisariam de regex ampliada.
    # Tratamos por presença literal antes da regex pra evitar fragmentação
    # no caractere não-ASCII.
    indicadores_especiais = [
        'IVIN-DESLIG-JUSTIÇA-TRAB',
        'IVIN-DESLIG-JUSTICA-TRAB',  # variante sem cedilha (alguns extratos)
        'PVIN-DESLIG-JUSTIÇA-TRAB',
        'PVIN-DESLIG-JUSTICA-TRAB',  # variante sem cedilha
    ]

    indicadores: list[str] = []
    linha_resto = linha

    # Passo 1: códigos especiais (consome do texto pra evitar fragmentos)
    for cod in indicadores_especiais:
        if cod in linha_resto:
            indicadores.append(cod)
            # Mascara mantendo comprimento, evita reordenar índices
            linha_resto = linha_resto.replace(cod, ' ' * len(cod))

    # Passo 2: regex genérica (com hífen e/ou underscore)
    re_indicador_hifen = re.compile(r'([A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)+)')
    indicadores.extend(re_indicador_hifen.findall(linha_resto))

    # Passo 3: códigos curtos sem hífen — busca literal com boundary natural
    # (não admite continuação alfanumérica), pega itens como ILEI123 (com dígitos).
    for cod in indicadores_sem_hifen:
        if re.search(r'(?<![A-Z0-9])' + re.escape(cod) + r'(?![A-Z0-9])', linha):
            indicadores.append(cod)

    # Variantes do tipo "PREC-FBR (FBR-AUT-*)" — a regex já pega PREC-FBR e
    # FBR-AUT-* separadamente, então ambas as marcas ficam disponíveis para
    # o classifier. Não precisa de tratamento adicional.

    return list(set(indicadores))


def identificar_tipo_vinculo(texto_bloco: str) -> str:
    """Identifica o tipo de vínculo/filiação a partir do texto do bloco.

    Usa lista ordenada (mais específico primeiro) para evitar match parcial.
    Chaves curtas (≤3 chars) usam word boundary para não casar dentro de palavras.
    """
    texto_upper = texto_bloco.upper()
    for chave, valor in TIPOS_VINCULO:
        if len(chave) <= 3:
            # Word boundary para chaves curtas ("CI", "MEI") — evita match em "ESPECIAL"
            if re.search(r'\b' + re.escape(chave) + r'\b', texto_upper):
                return valor
        else:
            if chave in texto_upper:
                return valor
    return 'Não identificado'


def parse_bloco_vinculo(bloco_texto: str, seq: int) -> dict:
    """Faz parsing de um bloco de vínculo empregatício."""
    vinculo = {
        'seq': seq,
        'tipo': identificar_tipo_vinculo(bloco_texto),
        'empregador': None,
        'identificador_empregador': None,
        'data_inicio': None,
        'data_fim': None,
        'ultima_remuneracao': None,
        'indicadores_vinculo': [],
        'remuneracoes': [],
        'eh_beneficio': False,
        'numero_beneficio': None,
        'especie_beneficio': None,
        'situacao_beneficio': None,
    }

    linhas = bloco_texto.split('\n')

    # Buscar CNPJ ou CEI
    m_cnpj = RE_CNPJ.search(bloco_texto)
    m_cei = RE_CEI.search(bloco_texto)
    if m_cnpj:
        vinculo['identificador_empregador'] = m_cnpj.group(1)
    elif m_cei:
        vinculo['identificador_empregador'] = m_cei.group(1)

    # Buscar datas (início e fim)
    datas = RE_DATA.findall(bloco_texto)
    if len(datas) >= 1:
        vinculo['data_inicio'] = datas[0]
    if len(datas) >= 2:
        vinculo['data_fim'] = datas[1]

    # Verificar se é benefício (NB = número do benefício)
    m_nb = re.search(r'NB[:\s]*(\d{10})', bloco_texto)
    if m_nb:
        vinculo['eh_beneficio'] = True
        vinculo['numero_beneficio'] = m_nb.group(1)
        # Espécie do benefício
        m_esp = re.search(r'(\d{2})\s*-\s*([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s]+)', bloco_texto)
        if m_esp:
            vinculo['especie_beneficio'] = f"{m_esp.group(1)} - {m_esp.group(2).strip()}"
        # Situação
        for sit in ['ATIVO', 'CESSADO', 'INDEFERIDO', 'SUSPENSO']:
            if sit in bloco_texto.upper():
                vinculo['situacao_beneficio'] = sit
                break

    # Extrair empregador (heurística: primeira linha longa após o seq)
    for linha in linhas:
        linha_limpa = linha.strip()
        # Pular linhas de cabeçalho, números puros, competências
        if (len(linha_limpa) > 10
                and not RE_COMPETENCIA.match(linha_limpa)
                and not linha_limpa.startswith('Seq')
                and not linha_limpa.startswith('Competência')):
            # Remover CNPJ/CEI da linha para pegar só o nome
            nome = RE_CNPJ.sub('', linha_limpa)
            nome = RE_CEI.sub('', nome)
            nome = re.sub(r'\d{2}/\d{2}/\d{4}', '', nome)
            nome = re.sub(r'\s+', ' ', nome).strip()
            if len(nome) > 3 and vinculo['empregador'] is None:
                vinculo['empregador'] = nome
                break

    if vinculo['empregador'] is None:
        logger.warning("Empregador não identificado no vínculo seq=%d", seq)

    # Extrair remunerações
    vinculo['remuneracoes'] = parse_remuneracoes_bloco(bloco_texto)

    # Extrair indicadores do vínculo (fora das linhas de remuneração)
    for linha in linhas[:5]:  # Indicadores do vínculo geralmente nas primeiras linhas
        inds = extrair_indicadores_linha(linha)
        vinculo['indicadores_vinculo'].extend(inds)
    # Deduplica
    vinculo['indicadores_vinculo'] = list(set(vinculo['indicadores_vinculo']))

    return vinculo


def parse_remuneracoes_bloco(bloco_texto: str) -> list[dict]:
    """Extrai remunerações (competência + valor + indicadores) de um bloco."""
    remuneracoes = []
    linhas = bloco_texto.split('\n')

    for linha in linhas:
        # Procurar padrão: MM/AAAA seguido de valor
        m_comp = RE_COMPETENCIA.search(linha)
        m_valor = RE_VALOR_MONETARIO.search(linha)

        if m_comp and m_valor:
            competencia = m_comp.group(1)
            valor = converter_valor(m_valor.group(1))

            # Indicadores na mesma linha (após o valor)
            # Pegar texto após o valor
            pos_valor_fim = m_valor.end()
            resto = linha[pos_valor_fim:]
            indicadores = extrair_indicadores_linha(resto)

            remuneracoes.append({
                'competencia': competencia,
                'valor': valor,
                'indicadores': indicadores,
            })

    return remuneracoes


def extrair_legenda_indicadores(texto_completo: str) -> set:
    """Extrai os indicadores da seção 'Legenda de Indicadores' do CNIS.

    O CNIS tem uma tabela no final com todos os indicadores usados no extrato.
    Ex: IREC-INDPEND, IREC-LC123, IREC-LIM-SM, PREC-MENOR-MIN
    Esses são os ÚNICOS indicadores válidos do extrato.
    """
    indicadores_legenda = set()

    # Procurar a seção "Legenda de Indicadores" ou "Legenda"
    match_legenda = re.search(
        r'[Ll]egenda\s+(?:de\s+)?[Ii]ndicadores?(.*?)(?:Página|\Z)',
        texto_completo,
        re.DOTALL
    )

    if match_legenda:
        bloco_legenda = match_legenda.group(1)
        # Extrair códigos com hífen (IREC-LC123, PREC-MENOR-MIN, etc.)
        codigos = re.findall(r'([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)', bloco_legenda)
        indicadores_legenda.update(codigos)

        # Também extrair códigos conhecidos sem hífen (PEXT, IEAN, etc.)
        palavras = re.findall(r'\b([A-Z]{3,})\b', bloco_legenda)
        indicadores_conhecidos_sem_hifen = {
            'PEXT', 'IEAN', 'PRPPS', 'ACNISVR',
        }
        for p in palavras:
            if p in indicadores_conhecidos_sem_hifen:
                indicadores_legenda.add(p)

    return indicadores_legenda


def segmentar_vinculos(texto_completo: str) -> list[str]:
    """Divide o texto em blocos, um por vínculo.

    Estratégia: vínculos no CNIS são identificados por um número
    sequencial (Seq) seguido de dados do empregador. Usamos a
    numeração sequencial como delimitador.
    """
    # Padrão: linha que começa com "Seq" (cabeçalho de tabela) ou
    # número sequencial seguido de NIT
    padrao_inicio = re.compile(
        r'(?:^|\n)(\d{1,3})\s+(\d{3}\.?\d{5}\.?\d{2}-?\d{1})',
        re.MULTILINE
    )

    matches = list(padrao_inicio.finditer(texto_completo))

    if not matches:
        # Tentar padrão alternativo: "Empregador:" ou "Origem do Vínculo:"
        padrao_alt = re.compile(
            r'(?:Empregador|Origem\s+do\s+V[ií]nculo)[:\s]+',
            re.IGNORECASE | re.MULTILINE
        )
        matches = list(padrao_alt.finditer(texto_completo))

    if not matches:
        logger.warning("Nenhum vínculo encontrado no texto (nenhum padrão Seq+NIT ou Empregador)")
        return []

    blocos = []
    for i, match in enumerate(matches):
        inicio = match.start()
        fim = matches[i + 1].start() if i + 1 < len(matches) else len(texto_completo)
        blocos.append(texto_completo[inicio:fim])

    return blocos


def parse_cnis(pdf_path: str) -> dict:
    """Função principal: faz parsing completo de um PDF de CNIS.

    Args:
        pdf_path: Caminho para o arquivo PDF do CNIS

    Returns:
        Dicionário com dados estruturados do CNIS
    """
    # 1. Extrair texto de todas as páginas
    logger.info("Iniciando parsing do CNIS: %s", pdf_path)
    paginas = extrair_texto_pdf(pdf_path)

    if not paginas or all(not p.strip() for p in paginas):
        logger.error("PDF sem texto digital: %s", pdf_path)
        return {
            'sucesso': False,
            'erro': 'PDF sem texto digital — provável escaneamento ou PDF protegido',
            'dados': None,
        }

    texto_completo = '\n'.join(paginas)
    texto_limpo = limpar_texto(texto_completo)

    # 2. Extrair cabeçalho
    cabecalho = parse_cabecalho(texto_limpo)

    # Validação mínima: precisa ter pelo menos nome ou NIT
    if not cabecalho['nome'] and not cabecalho['nit']:
        logger.error("Formato não reconhecido — sem nome nem NIT: %s", pdf_path)
        return {
            'sucesso': False,
            'erro': 'Formato de extrato não reconhecido — não foi possível identificar dados cadastrais',
            'dados': None,
        }

    # 3. Extrair legenda de indicadores do CNIS (fonte oficial)
    legenda_indicadores = extrair_legenda_indicadores(texto_limpo)

    # 4. Segmentar e parsear vínculos
    blocos = segmentar_vinculos(texto_limpo)
    vinculos = []
    for i, bloco in enumerate(blocos):
        vinculo = parse_bloco_vinculo(bloco, seq=i + 1)
        vinculos.append(vinculo)

    # 5. Filtrar indicadores: só manter os que estão na legenda do CNIS
    #    ou no dicionário de indicadores conhecidos
    if legenda_indicadores:
        for v in vinculos:
            v['indicadores_vinculo'] = [
                ind for ind in v['indicadores_vinculo']
                if ind in legenda_indicadores
            ]
            for r in v['remuneracoes']:
                r['indicadores'] = [
                    ind for ind in r['indicadores']
                    if ind in legenda_indicadores
                ]

    # 6. Calcular resumo
    todas_remuneracoes = []
    for v in vinculos:
        todas_remuneracoes.extend(v['remuneracoes'])

    competencias = [r['competencia'] for r in todas_remuneracoes if r['competencia']]
    competencias_sorted = sorted(competencias, key=lambda c: (c[3:7], c[0:2]))

    # Coletar todos os indicadores únicos (já filtrados)
    todos_indicadores = set()
    for v in vinculos:
        todos_indicadores.update(v['indicadores_vinculo'])
        for r in v['remuneracoes']:
            todos_indicadores.update(r['indicadores'])

    resumo = {
        'total_vinculos': len(vinculos),
        'total_vinculos_emprego': len([v for v in vinculos if not v['eh_beneficio']]),
        'total_beneficios': len([v for v in vinculos if v['eh_beneficio']]),
        'total_remuneracoes': len(todas_remuneracoes),
        'primeira_competencia': competencias_sorted[0] if competencias_sorted else None,
        'ultima_competencia': competencias_sorted[-1] if competencias_sorted else None,
        'total_indicadores_unicos': len(todos_indicadores),
        'indicadores_encontrados': sorted(list(todos_indicadores)),
    }

    logger.info(
        "Parsing concluído: %s — %d vínculos, %d remunerações, %d indicadores",
        cabecalho.get('nome', 'N/I'),
        resumo['total_vinculos'],
        resumo['total_remuneracoes'],
        resumo['total_indicadores_unicos'],
    )

    return {
        'sucesso': True,
        'erro': None,
        'dados': {
            'cabecalho': cabecalho,
            'vinculos': vinculos,
            'resumo': resumo,
        },
    }


# ============================================================================
#  PONTO DE ENTRADA (para uso via linha de comando)
# ============================================================================

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({
            'sucesso': False,
            'erro': 'Uso: python cnis_parser.py <caminho_pdf>',
        }))
        sys.exit(1)

    resultado = parse_cnis(sys.argv[1])
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
