"""
Cliente para upload de anexos no ADVBOX via endpoints web (não-públicos).

Mecanismo descoberto via reverse-engineering em 2026-05-09:
  1. POST /login            -> autentica (sem 2FA se device confiável)
  2. POST /s3               -> file vai pra files/temp/{user_id}/
  3. POST /posts            -> cria tarefa + AUTO-ANEXA arquivos da pasta temp do user

A API pública /api/v1/posts NÃO suporta upload. Por isso usamos os endpoints web.
"""
from __future__ import annotations

import email as email_mod
import gzip
import http.cookiejar
import imaplib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Optional, Tuple

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


class AdvboxLoginError(Exception):
    """Falha de autenticação (credenciais inválidas, 2FA exigido, etc)."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}")
        self.code = code  # "credentials" | "2fa_required" | "session_parse"
        self.message = message


class AdvboxUploadError(Exception):
    pass


class AdvboxClient:
    """Cliente Laravel/web da ADVBOX (não-API).

    Uso típico:
        client = AdvboxClient(email, password)
        client.login()                                            # raises AdvboxLoginError se falhar
        client.upload_file("a.pdf", pdf_bytes, "application/pdf", user_id)
        client.upload_file("a.docx", docx_bytes, "application/...", user_id)
        post_id = client.create_post(lawsuits_id, tasks_id, user_id, "11/05/2026", "12/05/2026", "comentário")
    """

    BASE = "https://app.advbox.com.br"

    def __init__(
        self,
        email: str,
        password: str,
        imap_user: Optional[str] = None,
        imap_password: Optional[str] = None,
        imap_host: str = "imap.gmail.com",
    ):
        """Cliente ADVBOX. Se imap_user e imap_password forem fornecidos,
        completa 2FA automaticamente lendo o código no email."""
        self.email = email
        self.password = password
        self.imap_user = imap_user
        self.imap_password = imap_password
        self.imap_host = imap_host
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self.opener.addheaders = [
            ("User-Agent", UA),
            ("Accept-Encoding", "gzip"),
            ("Accept-Language", "pt-BR,pt;q=0.9"),
        ]
        self.csrf: Optional[str] = None

    # ------------------------------------------------------------------
    #  Helpers HTTP
    # ------------------------------------------------------------------

    @staticmethod
    def _gunzip(data: bytes) -> bytes:
        return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data

    def _request(
        self,
        url: str,
        data: Optional[bytes] = None,
        headers: Optional[dict] = None,
        method: Optional[str] = None,
    ) -> Tuple[int, dict, bytes]:
        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            r = self.opener.open(req, timeout=60)
            return r.status, dict(r.headers), self._gunzip(r.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), self._gunzip(e.read())

    # ------------------------------------------------------------------
    #  Login
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Autentica. Lança AdvboxLoginError se falhar.

        Códigos de erro:
            - 'credentials'   : email/senha rejeitados
            - '2fa_required'  : ADVBOX exigiu código 2FA (dispositivo não confiável)
            - 'session_parse' : não conseguiu extrair CSRF da sessão autenticada
        """
        # 1) GET /login -> CSRF do form
        status, _, body = self._request(f"{self.BASE}/login")
        html = body.decode("utf-8", "replace")
        m = re.search(r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']', html)
        if not m:
            raise AdvboxLoginError("session_parse", "CSRF do form de login não encontrado")
        csrf_login = m.group(1)

        # 2) POST /login
        form = urllib.parse.urlencode(
            [
                ("_token", csrf_login),
                ("email", self.email),
                ("password", self.password),
                ("remember", ""),
                ("_device", ""),
            ]
        ).encode()
        status, _, body = self._request(
            f"{self.BASE}/login",
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{self.BASE}/login",
            },
        )
        html = body.decode("utf-8", "replace")

        # 2FA?
        if "Autentica" in html or "two_factor" in html.lower():
            # Se tem credenciais IMAP, tenta completar 2FA via email automaticamente
            if self.imap_user and self.imap_password:
                self._complete_2fa_via_email(html)
                # Após 2FA bem-sucedido, segue pra extrair CSRF da sessão (passo 3 abaixo)
            else:
                raise AdvboxLoginError(
                    "2fa_required",
                    "ADVBOX exigiu 2FA e ADVBOX_IMAP_USER/PASSWORD não configurados.",
                )
        else:
            title_m = re.search(r"<title>([^<]+)", html)
            title = title_m.group(1).strip() if title_m else ""
            if "Login" in title:
                raise AdvboxLoginError("credentials", "Email/senha rejeitados pelo ADVBOX")

        # 3) GET / -> CSRF da sessão autenticada (meta tag)
        status, _, body = self._request(f"{self.BASE}/")
        html = body.decode("utf-8", "replace")
        m = re.search(r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']', html)
        if not m:
            cands = re.findall(r"\b[A-Za-z0-9]{40}\b", html)
            self.csrf = cands[0] if cands else None
        else:
            self.csrf = m.group(1)
        if not self.csrf:
            raise AdvboxLoginError("session_parse", "Meta tag csrf-token não encontrada após login")

    # ------------------------------------------------------------------
    #  2FA via email (IMAP)
    # ------------------------------------------------------------------

    def _complete_2fa_via_email(self, html_2fa_page: str) -> None:
        """Lê a página de 2FA, dispara envio do código por email, lê IMAP, submete.

        Lança AdvboxLoginError se algum passo falhar.
        """
        # Extrai os tokens da página de 2FA
        m = re.search(r'<input[^>]*name=["\']token["\'][^>]*value=["\']([^"\']+)', html_2fa_page)
        if not m:
            raise AdvboxLoginError("2fa_required", "Não achei o token 2FA na página")
        token_2fa = m.group(1)
        m = re.search(r'<input[^>]*name=["\']_token["\'][^>]*value=["\']([^"\']+)', html_2fa_page)
        if not m:
            raise AdvboxLoginError("2fa_required", "Não achei o CSRF da página 2FA")
        csrf_2fa = m.group(1)

        # Marca o instante ANTES de pedir o código (pra ignorar emails antigos)
        request_time = time.time()

        # Solicita envio por email (POST /invite/validation)
        form = urllib.parse.urlencode(
            [
                ("_token", csrf_2fa),
                ("two_factor_type", "email"),
                ("email", self.email),
                ("ev__item", "two_factor"),
                ("_device", ""),
                ("token", token_2fa),
            ]
        ).encode()
        status, _, body = self._request(
            f"{self.BASE}/invite/validation",
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{self.BASE}/login",
            },
        )
        if status != 200:
            raise AdvboxLoginError(
                "2fa_required",
                f"POST /invite/validation retornou HTTP {status}",
            )

        # Lê o código no email (poll IMAP por até 60s)
        code = self._poll_2fa_code(min_received_at=request_time, max_wait_sec=60)
        if not code:
            raise AdvboxLoginError(
                "2fa_required",
                "Não achei email do código 2FA em 60s. Verificar caixa de entrada.",
            )

        # Submete código via POST /login
        form = urllib.parse.urlencode(
            [
                ("_token", csrf_2fa),
                ("email", self.email),
                ("password", self.password),
                ("two_factor_code", code),
                ("token", token_2fa),
                ("_device", ""),
            ]
        ).encode()
        status, _, body = self._request(
            f"{self.BASE}/login",
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": f"{self.BASE}/login",
            },
        )
        html = body.decode("utf-8", "replace")
        if "Autentica" in html or "two_factor" in html.lower():
            raise AdvboxLoginError("2fa_required", "Código 2FA rejeitado pelo ADVBOX")
        title_m = re.search(r"<title>([^<]+)", html)
        title = title_m.group(1).strip() if title_m else ""
        if "Login" in title:
            raise AdvboxLoginError("2fa_required", "Sessão voltou pra login após 2FA")

    def _poll_2fa_code(self, min_received_at: float, max_wait_sec: int = 60) -> Optional[str]:
        """Conecta no Gmail via IMAP e procura código de 6 dígitos em email
        do ADVBOX recebido após `min_received_at` (epoch seconds).
        Retorna o código string ou None se não achar dentro do timeout.
        """
        deadline = time.time() + max_wait_sec
        sleep_sec = 5
        # ADVBOX pode demorar uns segundos pra mandar
        time.sleep(8)
        while time.time() < deadline:
            try:
                with imaplib.IMAP4_SSL(self.imap_host, 993) as M:
                    M.login(self.imap_user, self.imap_password)
                    M.select("INBOX")
                    # Procura emails do ADVBOX (pode estar SEEN ou UNSEEN)
                    typ, ids = M.search(None, '(FROM "no-reply@advboxmail.com.br")')
                    if typ != "OK":
                        time.sleep(sleep_sec)
                        continue
                    id_list = ids[0].split()
                    if not id_list:
                        time.sleep(sleep_sec)
                        continue
                    # Vai do mais recente pro mais antigo
                    for msg_id in reversed(id_list[-10:]):  # checa últimos 10 emails
                        typ, data = M.fetch(msg_id, "(RFC822)")
                        if typ != "OK" or not data or not data[0]:
                            continue
                        raw = data[0][1]
                        msg = email_mod.message_from_bytes(raw)
                        date_str = msg.get("Date", "")
                        try:
                            msg_time = email_mod.utils.parsedate_to_datetime(date_str).timestamp()
                        except Exception:
                            msg_time = 0
                        # Ignora emails recebidos ANTES da nossa requisição
                        if msg_time < min_received_at - 30:
                            continue
                        # Extrai corpo
                        body_text = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                ct = part.get_content_type()
                                if ct in ("text/plain", "text/html"):
                                    payload = part.get_payload(decode=True)
                                    if payload:
                                        charset = part.get_content_charset() or "utf-8"
                                        body_text += payload.decode(charset, errors="replace")
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                body_text = payload.decode("utf-8", errors="replace")
                        # Procura código de 6 dígitos
                        # Estratégia: pega o primeiro 6-dig isolado depois de "código de validação"
                        # ou só o primeiro 6-dig isolado
                        m = re.search(
                            r"(?:c[óo]digo[^0-9]*?)(\d{6})",
                            body_text,
                            re.IGNORECASE,
                        )
                        if not m:
                            # Fallback: qualquer 6 dígitos isolados
                            m = re.search(r"\b(\d{6})\b", body_text)
                        if m:
                            return m.group(1)
            except Exception as e:
                # Loga e continua tentando
                print(f"IMAP poll error: {e}")
            time.sleep(sleep_sec)
        return None

    # ------------------------------------------------------------------
    #  Upload de arquivo (vai pra pasta temp)
    # ------------------------------------------------------------------

    def upload_file(
        self,
        filename: str,
        content: bytes,
        mime_type: str,
        user_id: int,
    ) -> str:
        """Sobe arquivo pra files/temp/{user_id}/. Retorna file_id (string numérica)."""
        if not self.csrf:
            raise AdvboxUploadError("Cliente não autenticado (chame login() antes)")

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
        parts: list[bytes] = []
        for n, v in [
            ("root", "posts"),
            ("folder", f"files/temp/{user_id}"),
            ("path_filter", ""),
        ]:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode()
            )
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file[]"; filename="{filename}"\r\nContent-Type: {mime_type}\r\n\r\n'.encode()
            + content
            + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())

        status, _, body = self._request(
            f"{self.BASE}/s3",
            data=b"".join(parts),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Csrf-Token": self.csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": self.BASE,
                "Referer": f"{self.BASE}/0",
                "Accept": "*/*",
            },
        )
        if status != 200:
            raise AdvboxUploadError(
                f"POST /s3 retornou HTTP {status}: {body[:300].decode('utf-8', 'replace')}"
            )
        file_id = body.decode("utf-8", "replace").strip()
        if not file_id.isdigit():
            raise AdvboxUploadError(f"Resposta /s3 inesperada: {file_id[:200]}")
        return file_id

    # ------------------------------------------------------------------
    #  Cria tarefa (auto-anexa files da pasta temp)
    # ------------------------------------------------------------------

    def create_post(
        self,
        lawsuits_id: int,
        tasks_id: int,
        user_id: int,
        date_br: str,           # DD/MM/YYYY
        deadline_br: str,        # DD/MM/YYYY (pode ser "" se sem prazo)
        comments: str,
    ) -> Optional[int]:
        """Cria nova tarefa. Files na pasta temp/{user_id} são auto-anexados.

        Retorna o post_id criado (ou None se não conseguir parsear).
        """
        if not self.csrf:
            raise AdvboxUploadError("Cliente não autenticado (chame login() antes)")

        fields = [
            ("_token", self.csrf),
            ("lawsuits_id", str(lawsuits_id)),
            ("user", ""),
            ("squad", ""),
            ("guests[]", str(user_id)),
            ("has_partner", "0"),
            ("tasks_id", str(tasks_id)),
            ("workflow_id", "0"),
            ("workflow_sequence", "1"),
            ("workflow_limit", "0"),
            ("workflow", ""),
            ("steps_id", ""),
            ("date", date_br),
            ("hour", ""),
            ("date_deadline", deadline_br),
            ("date_end", ""),
            ("hour_end", ""),
            ("local", ""),
            ("comments", comments),
            ("recurrence", ""),
            ("repeat_on_week", "all"),
            ("date_completed", ""),
            ("create", "1"),
            ("ai_suggestion", ""),
            ("create_token", ""),
            ("editing", ""),
            ("v2", "1"),
        ]
        form = urllib.parse.urlencode(fields).encode()
        status, _, body = self._request(
            f"{self.BASE}/posts",
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Csrf-Token": self.csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Origin": self.BASE,
                "Referer": f"{self.BASE}/0",
                "Accept": "application/json, text/plain, */*",
            },
        )
        text = body.decode("utf-8", "replace")
        if status != 200:
            raise AdvboxUploadError(f"POST /posts retornou HTTP {status}: {text[:300]}")

        # Parse post_id da resposta (ex: {"kanban":{"add":221644142}})
        m = re.search(r'"add":\s*(\d+)', text)
        if m:
            return int(m.group(1))
        m = re.search(r"posts/(\d+)/edit", text)
        return int(m.group(1)) if m else None
