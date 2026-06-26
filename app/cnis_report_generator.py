"""
Gerador de Relatório CNIS
Recebe JSON da análise, renderiza template Jinja2 e converte para PDF via Gotenberg.

Modos de uso:
  1. Como módulo: importar gerar_html() e gerar_pdf()
  2. Via linha de comando: python cnis_report_generator.py (lê JSON de stdin, escreve HTML em stdout)
"""

import base64
import json
import sys
import os
from datetime import date
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader


# ============================================================================
#  CONFIGURAÇÃO
# ============================================================================

TEMPLATES_DIR = os.environ.get('TEMPLATES_DIR', '/templates')
GOTENBERG_URL = os.environ.get('GOTENBERG_URL', 'http://gotenberg:3000')


def criar_ambiente_jinja() -> Environment:
    """Cria o ambiente Jinja2 com o diretório de templates."""
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=False,  # HTML já é confiável (gerado internamente)
    )


# ============================================================================
#  GERAÇÃO DE HTML
# ============================================================================

def gerar_html(dados_analise: dict) -> str:
    """Renderiza o template HTML do relatório com os dados da análise.

    Args:
        dados_analise: Dicionário retornado pelo cnis_analyzer.analisar_cnis()

    Returns:
        String HTML completa do relatório de 12 páginas
    """
    env = criar_ambiente_jinja()
    template = env.get_template('relatorio_cnis.html')

    # Carregar logo como base64 para embutir no HTML (Gotenberg não acessa paths locais)
    logo_path = Path(TEMPLATES_DIR) / 'assets' / 'logo_ts.png'
    logo_base64 = ''
    if logo_path.exists():
        logo_base64 = base64.b64encode(logo_path.read_bytes()).decode('utf-8')

    # Preparar contexto para o template
    contexto = {
        'data_analise': dados_analise.get('data_analise', date.today().strftime('%d/%m/%Y')),
        'cabecalho': dados_analise.get('cabecalho', {}),
        'idade': dados_analise.get('idade'),
        'qualidade_segurado': dados_analise.get('qualidade_segurado', {}),
        'tempo_contribuicao': dados_analise.get('tempo_contribuicao', {}),
        'avisos_beneficios': dados_analise.get('avisos_beneficios', []),
        'vinculos': dados_analise.get('vinculos', []),
        'indicadores': dados_analise.get('indicadores', {}),
        'lacunas': dados_analise.get('lacunas', {}),
        'remuneracoes': dados_analise.get('remuneracoes', {}),
        'verificacoes': dados_analise.get('verificacoes', {}),
        'conclusao': dados_analise.get('conclusao', {}),
        'resumo': dados_analise.get('resumo', {}),
        'logo_base64': logo_base64,
    }

    return template.render(**contexto)


# ============================================================================
#  CONVERSÃO HTML → PDF VIA GOTENBERG
# ============================================================================

def gerar_pdf(html: str, timeout: float = 30.0) -> bytes:
    """Converte HTML para PDF usando Gotenberg (Chromium headless).

    Args:
        html: String HTML completa do relatório
        timeout: Timeout em segundos para a requisição ao Gotenberg

    Returns:
        Bytes do arquivo PDF gerado

    Raises:
        httpx.HTTPStatusError: Se Gotenberg retornar erro
        httpx.ConnectError: Se Gotenberg não estiver acessível
    """
    url = f"{GOTENBERG_URL}/forms/chromium/convert/html"

    # Gotenberg espera multipart/form-data com o HTML como arquivo
    files = {
        'files': ('index.html', html.encode('utf-8'), 'text/html'),
    }

    # Configurações de impressão para A4
    data = {
        'paperWidth': '8.27',    # A4 em polegadas (210mm)
        'paperHeight': '11.69',  # A4 em polegadas (297mm)
        'marginTop': '0',
        'marginBottom': '0',
        'marginLeft': '0',
        'marginRight': '0',
        'printBackground': 'true',        # Imprimir cores de fundo
        'preferCssPageSize': 'true',       # Respeitar @page CSS
        'waitDelay': '2s',                 # Esperar 2s para fontes carregarem
        'emulatedMediaType': 'print',      # Modo de impressão
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, files=files, data=data)
        response.raise_for_status()
        return response.content


def gerar_nome_arquivo(dados_analise: dict) -> str:
    """Gera o nome do arquivo PDF de saída.

    Formato: Análise CNIS - NOME DO SEGURADO - DD-MM-AAAA.pdf
    """
    nome = dados_analise.get('cabecalho', {}).get('nome', 'SEGURADO')
    data = date.today().strftime('%d-%m-%Y')
    # Limpar caracteres inválidos para nome de arquivo
    nome_limpo = ''.join(c for c in nome if c.isalnum() or c in ' .-_')
    return f"Análise CNIS - {nome_limpo.strip()} - {data}.pdf"


# ============================================================================
#  PIPELINE COMPLETO
# ============================================================================

def gerar_relatorio_completo(dados_analise: dict) -> dict:
    """Pipeline completo: dados → HTML → PDF.

    Args:
        dados_analise: Dicionário da análise completa

    Returns:
        Dicionário com:
          - html: string HTML renderizada
          - pdf_bytes: bytes do PDF
          - nome_arquivo: nome sugerido para o arquivo
    """
    html = gerar_html(dados_analise)
    pdf_bytes = gerar_pdf(html)
    nome_arquivo = gerar_nome_arquivo(dados_analise)

    return {
        'html': html,
        'pdf_bytes': pdf_bytes,
        'nome_arquivo': nome_arquivo,
    }


# ============================================================================
#  PONTO DE ENTRADA (linha de comando)
# ============================================================================

if __name__ == '__main__':
    # Modo CLI: lê JSON de stdin, escreve HTML em stdout
    # Útil para debug e testes sem Gotenberg
    dados_stdin = sys.stdin.read()

    try:
        dados_analise = json.loads(dados_stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({
            'sucesso': False,
            'erro': f'JSON inválido: {str(e)}',
        }), file=sys.stderr)
        sys.exit(1)

    html = gerar_html(dados_analise)
    print(html)
