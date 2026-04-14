"""
Parser do formulário de entrevista do cliente (Google Forms → PDF).

Extrai as respostas do PDF do Google Forms "Planejamento Previdenciário -
Formulário de Entrevista com o Cliente" e retorna um dict compatível com
DadosFormulario.

O PDF do Google Forms tem estrutura previsível:
- Perguntas seguidas de respostas
- Checkboxes marcados vs não marcados
- Campos de texto livre após a pergunta
"""

import logging
import re
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ============================================================================
#  PATTERNS REGEX PARA EXTRAÇÃO
# ============================================================================

# O texto do PDF do Google Forms tem encoding com caracteres especiais
# quando exportado. Usar patterns flexíveis.

# Respostas sim/não (circled = selecionado)
RE_SEXO_FEMININO = re.compile(r"Feminino", re.IGNORECASE)
RE_SEXO_MASCULINO = re.compile(r"Masculino", re.IGNORECASE)

# Data de nascimento: formatos comuns
RE_DATA_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
RE_DATA_SEM_BARRA = re.compile(r"^(\d{2})(\d{2})(\d{4})$")

# CPF
RE_CPF = re.compile(r"(\d{3}\.?\d{3}\.?\d{3}-?\d{2})")

# Celular
RE_CELULAR = re.compile(r"(\d{2}\s?\d{4,5}\s?\d{4})")


# ============================================================================
#  FUNÇÕES AUXILIARES
# ============================================================================

def _extrair_texto_pdf(pdf_path: str) -> list[str]:
    """Extrai texto de todas as páginas do PDF."""
    try:
        import pdfplumber
    except ImportError:
        import fitz
        doc = fitz.open(pdf_path)
        paginas = [page.get_text() for page in doc]
        doc.close()
        return paginas

    paginas = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texto = page.extract_text() or ""
            paginas.append(texto)
    return paginas


def _normalizar_texto(texto: str) -> str:
    """Remove caracteres de controle e normaliza espaços."""
    # Substituir caracteres problemáticos de encoding
    texto = texto.replace("\u00a0", " ")  # non-breaking space
    texto = texto.replace("\ufffd", "")   # replacement char
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _encontrar_resposta_apos(texto: str, pergunta: str) -> Optional[str]:
    """Encontra a resposta textual que aparece após uma pergunta no texto."""
    # Escapar caracteres regex na pergunta
    pergunta_escaped = re.escape(pergunta)
    # Ser mais flexível com espaços e acentos
    pergunta_flexivel = pergunta_escaped.replace(r"\ ", r"\s+")

    m = re.search(pergunta_flexivel + r"\s*\*?\s*\n?\s*(.+?)(?:\n|$)", texto, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _opcao_selecionada(texto_pagina: str, opcoes: list[str]) -> Optional[str]:
    """
    Detecta qual opção está selecionada em uma pergunta de múltipla escolha.

    No PDF do Google Forms, a opção selecionada aparece como texto regular,
    enquanto as não selecionadas aparecem de forma diferente. A heurística é:
    a resposta selecionada aparece APÓS a pergunta como texto isolado em uma linha.
    """
    for opcao in opcoes:
        if opcao.lower() in texto_pagina.lower():
            return opcao
    return None


def _parse_data_nascimento(texto: str) -> Optional[date]:
    """Tenta parsear data de nascimento em múltiplos formatos."""
    # Formato DD/MM/AAAA
    m = RE_DATA_BR.search(texto)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    # Formato DDMMAAAA (sem barras)
    texto_limpo = texto.strip().replace("/", "").replace("-", "").replace(".", "")
    m = RE_DATA_SEM_BARRA.match(texto_limpo)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass

    return None


def _detectar_sexo(texto_pagina2: str) -> str:
    """
    Detecta o sexo do cliente a partir da página 2 do formulário.

    LIMITAÇÃO CONHECIDA: a extração de texto do PDF do Google Forms NÃO
    consegue distinguir entre opções selecionadas e não selecionadas em
    radio buttons. Ambas "Feminino" e "Masculino" aparecem no texto.

    Usamos múltiplas heurísticas:
    1. Se só uma opção aparece → é essa
    2. Se ambas aparecem → retornar None (precisa de input manual ou
       usar pdfplumber com análise de curvas)

    NOTA: O sexo será confirmado pelo conversor_modelos.py que também
    pode receber o dado via JSON do Google Forms (workflow n8n).
    """
    return None  # Indicar que não foi possível detectar do PDF


def _detectar_sexo_por_curvas(pdf_path: str) -> Optional[str]:
    """
    Tenta detectar o sexo usando análise de curvas (radio buttons) do PDF.

    No Google Forms PDF, a opção selecionada tem um radio button com
    cor teal (0.0, 0.52, 0.58) + inner dot. A não selecionada tem cor
    cinza (0.60, 0.63, 0.65).

    LIMITAÇÃO: Funciona para "Feminino" (1ª opção) mas pode não renderizar
    o indicador para "Masculino" (2ª opção) em alguns PDFs.
    """
    try:
        import pdfplumber
        pdf = pdfplumber.open(pdf_path)
        pag2 = pdf.pages[1] if len(pdf.pages) > 1 else None
        if not pag2:
            pdf.close()
            return None

        # Radio buttons do Sexo estão nas primeiras posições da página 2
        # Feminino ≈ y=94.5, Masculino ≈ y=124.5
        radio_curves = [
            c for c in pag2.curves
            if 40 < c.get("x0", 0) < 70 and 80 < c.get("top", 0) < 150
            and (c["x1"] - c["x0"]) < 20
        ]

        teal_count = 0
        teal_feminino = False
        teal_masculino = False
        inner_dots = 0

        for c in radio_curves:
            stroke = c.get("stroking_color", (0, 0, 0))
            w = c["x1"] - c["x0"]
            is_teal = abs(stroke[0]) < 0.02 and abs(stroke[1] - 0.52) < 0.03

            if is_teal:
                teal_count += 1
                if w < 5:
                    inner_dots += 1
                elif c["top"] < 110:
                    teal_feminino = True
                elif c["top"] > 110:
                    teal_masculino = True

        pdf.close()

        # Se há indicador teal com inner dot em Feminino → Feminino selecionado
        if teal_feminino and inner_dots > 0 and not teal_masculino:
            return "F"
        # Se há indicador teal com inner dot em Masculino → Masculino selecionado
        if teal_masculino and inner_dots > 0 and not teal_feminino:
            return "M"

        # Sem indicador teal → provavelmente Masculino (2ª opção, bug de render)
        if teal_count == 0:
            return "M"

        return None  # Inconclusivo

    except Exception as e:
        logger.warning("Falha na detecção de sexo por curvas: %s", e)
        return None


def _extrair_secao(texto: str, inicio: str, fim: str) -> Optional[str]:
    """Extrai texto entre dois marcadores."""
    texto_lower = texto.lower()
    pos_inicio = texto_lower.find(inicio.lower())
    pos_fim = texto_lower.find(fim.lower())

    if pos_inicio == -1:
        return None
    if pos_fim == -1:
        return texto[pos_inicio:]
    if pos_fim <= pos_inicio:
        return texto[pos_inicio:]

    return texto[pos_inicio:pos_fim]


def _detectar_estado_civil(texto: str) -> str:
    """
    Detecta estado civil selecionado.

    NOTA: No PDF do Google Forms, todas as opções aparecem no texto.
    A heurística usa a PRIMEIRA opção que aparece como texto isolado
    (em linha própria) na seção do Estado Civil.
    """
    secao = _extrair_secao(texto, "Estado Civil", "Se vive em")
    if not secao:
        secao = _extrair_secao(texto, "Estado Civil", "dependentes")

    if secao:
        # Analisar linha por linha — a primeira opção isolada é a selecionada
        linhas = secao.split("\n")
        for linha in linhas:
            linha_limpa = linha.strip().lower()
            # Pular a própria pergunta e texto genérico
            if "estado civil" in linha_limpa or not linha_limpa:
                continue
            # Cada opção é uma linha separada no PDF
            if "solteiro" in linha_limpa:
                return "SOLTEIRO"
            if "casado" in linha_limpa or "casada" in linha_limpa:
                return "CASADO"
            if "uni" in linha_limpa and "est" in linha_limpa:
                return "UNIAO_ESTAVEL"
            if "divorciado" in linha_limpa or "divorciada" in linha_limpa:
                return "DIVORCIADO"
            if "vi" in linha_limpa and "vo" in linha_limpa:
                return "VIUVO"

    return "SOLTEIRO"


def _detectar_sim_nao(texto: str, pergunta: str) -> bool:
    """Detecta se a resposta para uma pergunta Sim/Não é Sim."""
    secao = texto[texto.lower().find(pergunta.lower()):]
    # Pegar apenas as próximas linhas
    linhas = secao.split("\n")[:5]
    for linha in linhas[1:]:  # Pular a própria pergunta
        linha = linha.strip().lower()
        if linha == "sim":
            return True
        if linha.startswith("sim"):
            return True
        if linha == "não" or linha == "nao":
            return False
    return False


# ============================================================================
#  PARSER PRINCIPAL
# ============================================================================

def parse_formulario(pdf_path: str) -> dict:
    """
    Extrai dados do formulário de entrevista do cliente (Google Forms PDF).

    Args:
        pdf_path: caminho para o PDF do formulário preenchido

    Returns:
        dict compatível com DadosFormulario (pode ser passado para conversor_modelos)
    """
    paginas = _extrair_texto_pdf(pdf_path)
    texto_completo = "\n".join(paginas)
    texto_completo_norm = _normalizar_texto(texto_completo)

    # Juntar páginas relevantes
    pag2 = paginas[1] if len(paginas) > 1 else ""
    pag3 = paginas[2] if len(paginas) > 2 else ""
    pag4 = paginas[3] if len(paginas) > 3 else ""
    pag5 = paginas[4] if len(paginas) > 4 else ""
    pag6 = paginas[5] if len(paginas) > 5 else ""
    pag7 = paginas[6] if len(paginas) > 6 else ""
    pag8 = paginas[7] if len(paginas) > 7 else ""
    pag9 = paginas[8] if len(paginas) > 8 else ""
    pag10 = paginas[9] if len(paginas) > 9 else ""
    pag11 = paginas[10] if len(paginas) > 10 else ""
    pag12 = paginas[11] if len(paginas) > 11 else ""
    pag13 = paginas[12] if len(paginas) > 12 else ""
    pag14 = paginas[13] if len(paginas) > 13 else ""

    # ── Página 1: Nome ──
    pag1 = paginas[0] if paginas else ""
    nome = _extrair_nome(pag1)

    # ── Página 2: Sexo, Celular, Data Nascimento, CPF, Profissão ──
    # Sexo: texto não distingue seleção; usar curvas do PDF
    sexo = _detectar_sexo_por_curvas(pdf_path)
    if sexo is None:
        sexo = _detectar_sexo(pag2)
    if sexo is None:
        sexo = "M"  # Fallback conservador (requisitos mais altos)
    celular = _extrair_celular(pag2)
    data_nascimento = _extrair_data_nascimento(pag2)
    cpf = _extrair_cpf(pag2)
    profissao = _extrair_profissao(pag2)

    # ── Página 3: Estado Civil, Dependentes, Motivação ──
    estado_civil = _detectar_estado_civil(pag3)
    tem_dependentes = _detectar_sim_nao(pag3, "dependentes")

    # Motivação
    motivacao = "Planejamento previdenciário"
    if "idade m" in pag3.lower():
        motivacao = "Atingir a idade mínima para aposentadoria"
    elif "aumentar o valor" in pag3.lower():
        motivacao = "Desejo de aumentar o valor do futuro benefício"
    elif "planejar o recolhimento" in pag3.lower():
        motivacao = "Necessidade de planejar o recolhimento"

    # ── Página 4: Regularização CNIS, Trabalhando, Carteira ──
    interesse_regularizacao = _detectar_sim_nao(pag4, "regulariza")
    trabalhando = _detectar_sim_nao(pag4, "trabalhando no momento")

    # ── Página 5: Renda, Expectativa Idade ──
    faixa_renda = _detectar_faixa_renda(pag5)
    expectativa = _detectar_expectativa_idade(pag5)

    # ── Página 6: Condições especiais ──
    tem_atividade_especial = "agentes nocivos" in pag6.lower() and "insalubres" in pag6.lower()
    tem_trabalho_rural = "trabalho rural" in pag6.lower()
    tem_mei = "microempreendedor" in pag6.lower() or "mei" in pag6.lower()

    # ── Página 7: Valor contribuição, Regime tributário ──
    regime_tributario = _detectar_regime_tributario(pag7)

    # ── Página 8: Benefício solicitado, Pensão, Sal.Maternidade ──
    ja_solicitou_beneficio = _detectar_sim_nao(pag8, "solicitou algum bene")
    recebe_pensao = _detectar_sim_nao(pag8, "pens")
    salario_maternidade = _detectar_sim_nao(pag8, "Maternidade")

    # ── Página 9: Serviço público, Processo trabalhista ──
    processo_trabalhista = None
    if "houve acordo" in pag9.lower():
        processo_trabalhista = "Sim - Houve acordo"
    elif _detectar_sim_nao(pag9, "Processo Trabalhista"):
        processo_trabalhista = "Sim"

    # ── Página 10: Trabalho exterior ──
    trabalhou_exterior = _detectar_sim_nao(pag10, "exterior")

    # ── Página 11: Atividade insalubre ──
    trabalhou_insalubre = _detectar_sim_nao(pag11, "insalubre")

    # ── Página 12: Parcelamento, MEI, Rural ──
    parcelamento = _detectar_sim_nao(pag12, "parcelamento")
    ja_foi_mei = _detectar_sim_nao(pag12, "MEI")
    trabalhou_rural = _detectar_sim_nao(pag12, "rural")

    # ── Página 13: PcD, Acidentes ──
    e_pcd = _detectar_sim_nao(pag13, "defici")
    descricao_pcd = _extrair_descricao_pcd(pag13)
    sofreu_acidente = _detectar_sim_nao(pag13, "acidente")
    sequela = _detectar_sim_nao(pag13, "sequela")
    cirurgia = _detectar_sim_nao(pag13, "cirurgia")

    # ── Página 14: Informações adicionais ──
    info_adicional = _extrair_info_adicional(pag14)

    # ── Origem de conhecimento (Página 1) ──
    origem = _detectar_origem(pag1)

    resultado = {
        "nome_completo": nome or "NÃO IDENTIFICADO",
        "sexo": sexo,
        "data_nascimento": data_nascimento,
        "cpf": cpf or "00000000000",
        "celular": celular or "",
        "profissao": profissao or "Não informada",
        "origem_conhecimento": origem,
        "estado_civil": estado_civil,
        "tem_dependentes": tem_dependentes,
        "motivacao_principal": motivacao,
        "interesse_regularizacao_cnis": interesse_regularizacao,
        "trabalhando_atualmente": trabalhando,
        "faixa_renda": faixa_renda,
        "expectativa_idade_aposentadoria": expectativa,
        "regime_tributario": regime_tributario,
        "tem_atividade_especial": tem_atividade_especial,
        "tem_trabalho_rural": tem_trabalho_rural,
        "tem_mei": tem_mei,
        "ja_solicitou_beneficio": ja_solicitou_beneficio,
        "recebe_pensao_morte": recebe_pensao,
        "ja_recebeu_salario_maternidade": salario_maternidade,
        "processo_trabalhista": processo_trabalhista,
        "trabalhou_exterior": trabalhou_exterior,
        "trabalhou_insalubre": trabalhou_insalubre,
        "parcelamento_divida_previdenciaria": parcelamento,
        "ja_foi_mei": ja_foi_mei,
        "trabalhou_meio_rural": trabalhou_rural,
        "e_pcd": e_pcd,
        "descricao_pcd": descricao_pcd,
        "sofreu_acidente": sofreu_acidente,
        "sequela_acidente": sequela,
        "cirurgia_acidente": cirurgia,
        "informacoes_adicionais": info_adicional,
    }

    logger.info(
        "Formulário parseado: %s, sexo=%s, PcD=%s",
        resultado["nome_completo"],
        resultado["sexo"],
        resultado["e_pcd"],
    )

    return resultado


# ============================================================================
#  EXTRATORES ESPECÍFICOS
# ============================================================================

def _extrair_nome(texto_pag1: str) -> Optional[str]:
    """Extrai o nome completo do cliente da página 1."""
    # O nome aparece logo antes da seção "Planejamento Previdenciário"
    # ou logo após "Nome Completo do Cliente"
    linhas = texto_pag1.split("\n")
    for i, linha in enumerate(linhas):
        if "nome completo" in linha.lower():
            # A próxima linha não-vazia que não seja header é o nome
            for j in range(i + 1, min(i + 3, len(linhas))):
                candidato = linhas[j].strip()
                if candidato and len(candidato) > 3 and not candidato.startswith("14/"):
                    return candidato
            break

    # Fallback: procurar nome que aparece antes do texto de introdução
    for i, linha in enumerate(linhas):
        if "planejamento previdenci" in linha.lower() and "formul" in linha.lower():
            # Nome geralmente está 1-2 linhas acima
            for j in range(max(0, i - 3), i):
                candidato = linhas[j].strip()
                if (candidato and len(candidato) > 5
                        and not any(w in candidato.lower() for w in
                                    ["youtube", "instagram", "facebook", "tiktok",
                                     "google", "indica", "outro"])):
                    return candidato
            break

    return None


def _extrair_celular(texto_pag2: str) -> Optional[str]:
    """Extrai número de celular."""
    m = RE_CELULAR.search(texto_pag2)
    if m:
        return "".join(c for c in m.group(1) if c.isdigit())
    return None


def _extrair_data_nascimento(texto_pag2: str) -> Optional[date]:
    """
    Extrai data de nascimento da página 2.

    No Google Forms PDF, as RESPOSTAS ficam no topo da página e as
    PERGUNTAS abaixo. A data de nascimento é a 3ª resposta (após sexo e celular).
    Pode vir como DD/MM/AAAA ou DDMMAAAA.
    """
    # Estratégia 1: procurar na seção entre "Nascimento" e "CPF"
    secao = _extrair_secao(texto_pag2, "Nascimento", "CPF")
    if secao:
        data = _parse_data_nascimento(secao)
        if data:
            return data

    # Estratégia 2: analisar as primeiras linhas (respostas vêm antes das perguntas)
    linhas = texto_pag2.split("\n")
    for linha in linhas[:8]:
        linha = linha.strip()
        if not linha:
            continue
        # Tentar parsear cada linha como data
        data = _parse_data_nascimento(linha)
        if data and 1920 < data.year < 2020:
            return data

    # Estratégia 3: fallback procurando padrão DDMMAAAA em qualquer lugar
    for linha in linhas:
        linha = linha.strip()
        if re.match(r"^\d{8}$", linha):
            data = _parse_data_nascimento(linha)
            if data and 1920 < data.year < 2020:
                return data

    return None


def _extrair_cpf(texto_pag2: str) -> Optional[str]:
    """Extrai CPF da página 2."""
    secao = _extrair_secao(texto_pag2, "CPF", "Profiss")
    if secao:
        m = RE_CPF.search(secao)
        if m:
            return "".join(c for c in m.group(1) if c.isdigit())

    # Fallback
    m = RE_CPF.search(texto_pag2)
    if m:
        return "".join(c for c in m.group(1) if c.isdigit())
    return None


def _extrair_profissao(texto_pag2: str) -> Optional[str]:
    """Extrai profissão da página 2."""
    secao = _extrair_secao(texto_pag2, "Profiss", "14/")
    if secao:
        linhas = secao.split("\n")
        for linha in linhas[1:]:
            linha = linha.strip()
            if linha and len(linha) > 2 and not linha.startswith("14/"):
                return linha
    return None


def _detectar_faixa_renda(texto: str) -> Optional[str]:
    """Detecta faixa de renda selecionada."""
    texto_lower = texto.lower()
    if "acima do teto" in texto_lower:
        return "ACIMA_TETO"
    if "4.863" in texto and "8.475" in texto:
        return "DE_3_A_TETO"
    if "3.242" in texto and "4.863" in texto:
        return "DE_2_A_3SM"
    if "1.621" in texto and "3.242" in texto:
        return "DE_1_A_2SM"
    return None


def _detectar_expectativa_idade(texto: str) -> Optional[str]:
    """Detecta expectativa de idade para aposentadoria."""
    texto_lower = texto.lower()
    if "assim que poss" in texto_lower:
        return "ASSIM_QUE_POSSIVEL"
    if "mais de 65" in texto_lower:
        return "MAIS_65"
    if "61" in texto and "65" in texto:
        return "ENTRE_61_65"
    if "56" in texto and "60" in texto:
        return "ENTRE_56_60"
    if "55" in texto_lower:
        return "ATE_55"
    return None


def _detectar_regime_tributario(texto: str) -> Optional[str]:
    """Detecta regime tributário."""
    texto_lower = texto.lower()
    if "simples nacional" in texto_lower:
        return "SIMPLES_NACIONAL"
    if "lucro presumido" in texto_lower:
        return "LUCRO_PRESUMIDO"
    if "lucro real" in texto_lower:
        return "LUCRO_REAL"
    if "mei" in texto_lower:
        return "MEI"
    if "n" in texto_lower and "aplica" in texto_lower:
        return "NAO_APLICA"
    return None


def _extrair_descricao_pcd(texto: str) -> Optional[str]:
    """Extrai descrição da deficiência/PcD."""
    secao = _extrair_secao(texto, "defici", "acidente")
    if secao:
        linhas = secao.split("\n")
        for linha in linhas[2:]:
            linha = linha.strip()
            if linha and len(linha) > 10 and not linha.startswith("14/"):
                return linha
    return None


def _extrair_info_adicional(texto: str) -> Optional[str]:
    """Extrai informações adicionais da última página."""
    secao = _extrair_secao(texto, "mais informa", "Formul")
    if secao:
        linhas = secao.split("\n")
        texto_livre = []
        for linha in linhas[1:]:
            linha = linha.strip()
            if linha and not linha.startswith("14/") and "Formul" not in linha:
                texto_livre.append(linha)
        if texto_livre:
            return " ".join(texto_livre)
    return None


def _detectar_origem(texto_pag1: str) -> Optional[str]:
    """Detecta como o cliente conheceu o escritório."""
    texto_lower = texto_pag1.lower()
    if "youtube" in texto_lower:
        return "YOUTUBE"
    if "instagram" in texto_lower:
        return "INSTAGRAM"
    if "facebook" in texto_lower:
        return "FACEBOOK"
    if "tiktok" in texto_lower:
        return "TIKTOK"
    if "google" in texto_lower:
        return "GOOGLE"
    if "indica" in texto_lower:
        return "INDICACAO"
    return None
