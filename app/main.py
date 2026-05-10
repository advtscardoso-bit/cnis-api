"""
API FastAPI — Sistema de Análise de CNIS
Endpoint principal: POST /analisar-cnis

Recebe PDF do CNIS via multipart/form-data
Retorna JSON com resumo da análise + PDF e DOCX do relatório em base64
"""

import base64
import json
import os
import tempfile
import traceback
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException, Header, Form
from fastapi.responses import JSONResponse

from cnis_parser import parse_cnis
from cnis_analyzer import analisar_cnis
from cnis_report_generator import gerar_html, gerar_pdf, gerar_nome_arquivo
from cnis_docx_generator import gerar_docx, gerar_nome_arquivo_docx
from advbox_uploader import AdvboxClient, AdvboxLoginError, AdvboxUploadError


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


@app.get("/info")
async def info():
    """Retorna estatísticas da base de indicadores carregada no servidor.
    Útil para confirmar se o deploy está com a versão mais recente."""
    try:
        from cnis_analyzer import carregar_indicadores
        d = carregar_indicadores()
        return {
            "total": sum(len(v) for v in d.values()),
            "por_categoria": {k: len(v) for k, v in d.items()},
            "amostra_pendencia": list(d.get('PENDENCIAS', {}).keys())[:5],
            "amostra_alerta": list(d.get('ALERTAS', {}).keys())[:5],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"erro": str(e)}


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


@app.post("/upload-to-advbox")
async def upload_to_advbox_endpoint(
    pdf: UploadFile = File(...),
    docx: UploadFile = File(None),
    lawsuits_id: int = Form(...),
    tasks_id: int = Form(...),
    user_id: int = Form(...),
    date: str = Form(...),
    date_deadline: str = Form(""),
    comments: str = Form(""),
    x_api_key: str = Header(default=None),
):
    """Cria uma tarefa no ADVBOX com PDF (e opcionalmente DOCX) anexados.

    Faz login programático no ADVBOX (usa env vars ADVBOX_EMAIL e ADVBOX_PASSWORD),
    sobe os arquivos pra pasta temp do user, cria a tarefa e o ADVBOX auto-anexa.

    Body (multipart/form-data):
        pdf: arquivo PDF (obrigatório)
        docx: arquivo DOCX (opcional)
        lawsuits_id: ID do processo no ADVBOX
        tasks_id: ID do template de tarefa (ex: 9097703 = ENTREGAR PARA O CLIENTE)
        user_id: user_id do responsável (ex: 260801 = Cláudia)
        date: data início no formato DD/MM/YYYY
        date_deadline: prazo fatal DD/MM/YYYY (opcional)
        comments: descrição da tarefa

    Returns:
        {sucesso: True, post_id: <int>}              -> 200
        {sucesso: False, erro: "2fa_required", ...}  -> 403  (precisa renovar trust)
        {sucesso: False, erro: "credentials", ...}   -> 401  (senha errada)
        {sucesso: False, erro: "...", ...}           -> 500  (outro erro)
    """
    verificar_api_key(x_api_key)

    email = os.environ.get("ADVBOX_EMAIL")
    password = os.environ.get("ADVBOX_PASSWORD")
    if not email or not password:
        return JSONResponse(
            status_code=500,
            content={
                "sucesso": False,
                "erro": "config",
                "mensagem": "ADVBOX_EMAIL e ADVBOX_PASSWORD não configurados no servidor",
            },
        )

    client = AdvboxClient(email, password)
    try:
        client.login()
    except AdvboxLoginError as e:
        status_code = 403 if e.code == "2fa_required" else 401
        return JSONResponse(
            status_code=status_code,
            content={"sucesso": False, "erro": e.code, "mensagem": e.message},
        )

    try:
        pdf_bytes = await pdf.read()
        client.upload_file(pdf.filename, pdf_bytes, "application/pdf", user_id)

        if docx is not None:
            docx_bytes = await docx.read()
            client.upload_file(
                docx.filename,
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                user_id,
            )

        post_id = client.create_post(
            lawsuits_id=lawsuits_id,
            tasks_id=tasks_id,
            user_id=user_id,
            date_br=date,
            deadline_br=date_deadline,
            comments=comments,
        )
        return {"sucesso": True, "post_id": post_id}
    except AdvboxUploadError as e:
        return JSONResponse(
            status_code=500,
            content={"sucesso": False, "erro": "upload_failed", "mensagem": str(e)},
        )
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"sucesso": False, "erro": "exception", "mensagem": str(e)},
        )


@app.get("/")
async def root():
    """Rota raiz com informações da API."""
    return {
        "nome": "API de Análise de CNIS",
        "versao": "1.0.0",
        "escritorio": "Tatiana Sampaio Advocacia e Consultoria Jurídica",
        "endpoints": {
            "POST /analisar-cnis": "Envia PDF do CNIS e recebe análise + relatório PDF",
            "POST /upload-to-advbox": "Anexa PDF/DOCX em uma tarefa do ADVBOX",
            "GET /health": "Health check",
        },
    }
