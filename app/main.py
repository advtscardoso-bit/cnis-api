"""
API FastAPI — Sistema de Análise de CNIS
Endpoint principal: POST /analisar-cnis

Recebe PDF do CNIS via multipart/form-data
Retorna JSON com resumo da análise + PDF e DOCX do relatório em base64
"""

import base64
import json
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Header
from fastapi.responses import JSONResponse

# Garantir que imports "from app." funcionem no Docker (WORKDIR=/app)
_app_dir = Path(__file__).parent
_project_root = _app_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
# Também garantir que imports sem prefixo funcionem (from cnis_parser)
if str(_app_dir) not in sys.path:
    sys.path.insert(0, str(_app_dir))

from cnis_parser import parse_cnis
from cnis_analyzer import analisar_cnis
from cnis_report_generator import gerar_html, gerar_pdf, gerar_nome_arquivo
from cnis_docx_generator import gerar_docx, gerar_nome_arquivo_docx
from conversor_modelos import converter, DadosConvertidos
from formulario_parser import parse_formulario


# ============================================================================
#  CONFIGURAÇÃO
# ============================================================================

API_KEY = os.environ.get('API_KEY', '')

app = FastAPI(
    title="API de Análise de CNIS",
    description="Tatiana Sampaio Advocacia — Sistema automatizado de análise de extratos CNIS",
    version="1.0.0",
)


# ============================================================================
#  AUTENTICAÇÃO
# ============================================================================

def verificar_api_key(x_api_key: str = Header(default=None)):
    """Verifica a chave de API no header X-API-Key."""
    if not API_KEY:
        return  # Se API_KEY não configurada, aceita tudo (dev)
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Chave de API inválida")


# ============================================================================
#  ENDPOINTS
# ============================================================================

@app.get("/health")
async def health():
    """Health check para o Docker e monitoramento."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.post("/analisar-cnis")
async def analisar_cnis_endpoint(
    file: UploadFile = File(...),
    x_api_key: str = Header(default=None),
):
    """Endpoint principal: recebe PDF do CNIS e retorna análise + relatório PDF.

    Headers:
        X-API-Key: Chave de autenticação (obrigatório se API_KEY configurada)

    Body (multipart/form-data):
        file: Arquivo PDF do CNIS

    Returns:
        JSON com:
        - sucesso (bool)
        - resumo (dict): dados resumidos da análise
        - relatorio_pdf_base64 (str): PDF do relatório codificado em base64
        - nome_arquivo (str): nome sugerido para o arquivo PDF
    """
    # Autenticação
    verificar_api_key(x_api_key)

    # Validar que é um PDF
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=400,
            detail="O arquivo deve ser um PDF (.pdf)"
        )

    # Salvar PDF em arquivo temporário
    try:
        conteudo = await file.read()
        if len(conteudo) == 0:
            raise HTTPException(status_code=400, detail="Arquivo PDF vazio")

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(conteudo)
            tmp_path = tmp.name

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro ao ler o arquivo: {str(e)}")

    try:
        # ---- ETAPA 1: PARSING ----
        resultado_parser = parse_cnis(tmp_path)

        if not resultado_parser.get('sucesso'):
            return JSONResponse(
                status_code=422,
                content={
                    "sucesso": False,
                    "erro": resultado_parser.get('erro', 'Erro desconhecido no parsing'),
                    "nome_arquivo": file.filename,
                },
            )

        # ---- ETAPA 2: ANÁLISE ----
        resultado_analise = analisar_cnis(resultado_parser)

        if not resultado_analise.get('sucesso'):
            return JSONResponse(
                status_code=422,
                content={
                    "sucesso": False,
                    "erro": resultado_analise.get('erro', 'Erro desconhecido na análise'),
                    "nome_arquivo": file.filename,
                },
            )

        # ---- ETAPA 3: GERAR HTML ----
        html = gerar_html(resultado_analise)

        # ---- ETAPA 4: CONVERTER PARA PDF VIA GOTENBERG ----
        try:
            pdf_bytes = gerar_pdf(html)
        except Exception as e:
            # Se Gotenberg falhar, ainda gera o DOCX
            try:
                docx_bytes = gerar_docx(resultado_analise)
                docx_base64 = base64.b64encode(docx_bytes).decode('utf-8')
                nome_docx = gerar_nome_arquivo_docx(resultado_analise)
            except Exception:
                docx_base64 = None
                nome_docx = None

            return JSONResponse(
                status_code=200,
                content={
                    "sucesso": True,
                    "aviso": f"Análise concluída mas o PDF não pôde ser gerado: {str(e)}. DOCX gerado com sucesso.",
                    "resumo": resultado_analise.get('resumo', {}),
                    "analise_completa": json.loads(
                        json.dumps(resultado_analise, default=str)
                    ),
                    "relatorio_pdf_base64": None,
                    "nome_arquivo_pdf": gerar_nome_arquivo(resultado_analise),
                    "relatorio_docx_base64": docx_base64,
                    "nome_arquivo_docx": nome_docx,
                },
            )

        # ---- ETAPA 5: GERAR DOCX (editável) ----
        try:
            docx_bytes = gerar_docx(resultado_analise)
            docx_base64 = base64.b64encode(docx_bytes).decode('utf-8')
            nome_arquivo_docx = gerar_nome_arquivo_docx(resultado_analise)
        except Exception as e:
            docx_base64 = None
            nome_arquivo_docx = None

        # ---- ETAPA 6: RETORNAR RESULTADO ----
        nome_arquivo_pdf = gerar_nome_arquivo(resultado_analise)
        pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')

        return {
            "sucesso": True,
            "resumo": resultado_analise.get('resumo', {}),
            "analise_completa": json.loads(
                json.dumps(resultado_analise, default=str)
            ),
            "relatorio_pdf_base64": pdf_base64,
            "nome_arquivo_pdf": nome_arquivo_pdf,
            "relatorio_docx_base64": docx_base64,
            "nome_arquivo_docx": nome_arquivo_docx,
        }

    except HTTPException:
        raise
    except Exception as e:
        # Erro inesperado — logar e retornar
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "sucesso": False,
                "erro": f"Erro interno no processamento: {str(e)}",
                "nome_arquivo": file.filename,
            },
        )
    finally:
        # Limpar arquivo temporário
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@app.post("/analisar-cnis-v2")
async def analisar_cnis_v2_endpoint(
    file: UploadFile = File(..., description="PDF do CNIS"),
    formulario: UploadFile = File(None, description="PDF do formulário de entrevista (opcional)"),
    formulario_json: str = Form(None, description="JSON do formulário de entrevista (opcional, alternativa ao PDF)"),
    x_api_key: str = Header(default=None),
):
    """Endpoint V2: análise CNIS com modelos Pydantic tipados.

    Aceita o PDF do CNIS + opcionalmente o formulário do cliente (PDF ou JSON).
    Retorna análise completa + dados Pydantic estruturados (pessoa, vínculos,
    contribuições, benefícios, indicadores) + relatório PDF/DOCX.

    O formulário fornece dados que o CNIS não contém (sexo, PcD, rural, etc.).
    Sem formulário, o sistema usa fallbacks conservadores com avisos.

    Body (multipart/form-data):
        file: PDF do CNIS (obrigatório)
        formulario: PDF do formulário Google Forms (opcional)
        formulario_json: JSON com dados do formulário (opcional, alternativa ao PDF)
    """
    verificar_api_key(x_api_key)

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="O arquivo CNIS deve ser PDF")

    tmp_cnis = None
    tmp_form = None

    try:
        # Salvar CNIS em temp
        conteudo_cnis = await file.read()
        if len(conteudo_cnis) == 0:
            raise HTTPException(status_code=400, detail="PDF do CNIS vazio")

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(conteudo_cnis)
            tmp_cnis = tmp.name

        # ---- ETAPA 1: PARSING CNIS ----
        resultado_parser = parse_cnis(tmp_cnis)

        if not resultado_parser.get('sucesso'):
            return JSONResponse(
                status_code=422,
                content={
                    "sucesso": False,
                    "erro": resultado_parser.get('erro', 'Erro no parsing do CNIS'),
                },
            )

        # ---- ETAPA 2: PARSING FORMULÁRIO (opcional) ----
        dados_formulario = None

        if formulario_json:
            try:
                dados_formulario = json.loads(formulario_json)
            except json.JSONDecodeError as e:
                return JSONResponse(
                    status_code=400,
                    content={"sucesso": False, "erro": f"JSON do formulário inválido: {e}"},
                )
        elif formulario and formulario.filename:
            conteudo_form = await formulario.read()
            if len(conteudo_form) > 0:
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                    tmp.write(conteudo_form)
                    tmp_form = tmp.name
                try:
                    dados_formulario = parse_formulario(tmp_form)
                except Exception as e:
                    dados_formulario = None

        # ---- ETAPA 3: CONVERSÃO dict → Pydantic ----
        try:
            dados_convertidos = converter(resultado_parser, dados_formulario)
        except ValueError as e:
            return JSONResponse(
                status_code=422,
                content={"sucesso": False, "erro": f"Erro na conversão: {e}"},
            )

        # ---- ETAPA 4: ANÁLISE (pipeline existente, ainda usa dicts) ----
        resultado_analise = analisar_cnis(resultado_parser)

        # ---- ETAPA 5: GERAR RELATÓRIOS ----
        pdf_base64 = None
        docx_base64 = None
        nome_pdf = None
        nome_docx = None

        if resultado_analise.get('sucesso'):
            try:
                html = gerar_html(resultado_analise)
                pdf_bytes = gerar_pdf(html)
                pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
                nome_pdf = gerar_nome_arquivo(resultado_analise)
            except Exception:
                pass

            try:
                docx_bytes = gerar_docx(resultado_analise)
                docx_base64 = base64.b64encode(docx_bytes).decode('utf-8')
                nome_docx = gerar_nome_arquivo_docx(resultado_analise)
            except Exception:
                pass

        # ---- ETAPA 6: MONTAR RESPOSTA ESTRUTURADA ----
        pessoa_dict = dados_convertidos.pessoa.model_dump(mode='json')
        vinculos_dict = [v.model_dump(mode='json') for v in dados_convertidos.vinculos]
        contribuicoes_dict = [c.model_dump(mode='json') for c in dados_convertidos.contribuicoes]
        beneficios_dict = [b.model_dump(mode='json') for b in dados_convertidos.beneficios]
        indicadores_dict = [i.model_dump(mode='json') for i in dados_convertidos.indicadores]
        formulario_dict = dados_convertidos.formulario.model_dump(mode='json') if dados_convertidos.formulario else None

        return {
            "sucesso": True,
            "versao": "2.0",
            "pessoa": pessoa_dict,
            "vinculos": vinculos_dict,
            "total_vinculos": len(vinculos_dict),
            "contribuicoes": contribuicoes_dict,
            "total_contribuicoes": len(contribuicoes_dict),
            "beneficios": beneficios_dict,
            "total_beneficios": len(beneficios_dict),
            "indicadores": indicadores_dict,
            "total_indicadores": len(indicadores_dict),
            "formulario": formulario_dict,
            "avisos": dados_convertidos.avisos,
            "analise": resultado_analise if resultado_analise.get('sucesso') else None,
            "relatorio_pdf_base64": pdf_base64,
            "nome_arquivo_pdf": nome_pdf,
            "relatorio_docx_base64": docx_base64,
            "nome_arquivo_docx": nome_docx,
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"sucesso": False, "erro": f"Erro interno: {str(e)}"},
        )
    finally:
        for tmp in [tmp_cnis, tmp_form]:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


@app.post("/parse-formulario")
async def parse_formulario_endpoint(
    file: UploadFile = File(..., description="PDF do formulário de entrevista"),
    x_api_key: str = Header(default=None),
):
    """Extrai dados do formulário de entrevista (Google Forms PDF).

    Retorna JSON com os campos extraídos: sexo, estado civil, PcD, etc.
    Pode ser usado standalone ou como input para /analisar-cnis-v2.
    """
    verificar_api_key(x_api_key)

    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="O arquivo deve ser PDF")

    tmp_path = None
    try:
        conteudo = await file.read()
        if len(conteudo) == 0:
            raise HTTPException(status_code=400, detail="PDF vazio")

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
            tmp.write(conteudo)
            tmp_path = tmp.name

        dados = parse_formulario(tmp_path)

        return {
            "sucesso": True,
            "dados_formulario": dados,
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"sucesso": False, "erro": f"Erro ao processar formulário: {str(e)}"},
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@app.get("/")
async def root():
    """Rota raiz com informações da API."""
    return {
        "nome": "API de Análise de CNIS",
        "versao": "2.0.0",
        "escritorio": "Tatiana Sampaio Advocacia e Consultoria Jurídica",
        "endpoints": {
            "POST /analisar-cnis": "V1 — Análise CNIS (dicts, compatibilidade)",
            "POST /analisar-cnis-v2": "V2 — Análise CNIS com modelos Pydantic + formulário",
            "POST /parse-formulario": "Extrai dados do formulário de entrevista (PDF)",
            "GET /health": "Health check",
        },
    }
