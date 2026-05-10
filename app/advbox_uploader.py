"""
Cliente para upload de anexos no ADVBOX via endpoints web (não-públicos).

Mecanismo descoberto via reverse-engineering em 2026-05-09:
  1. POST /login            -> autentica (sem 2FA se device confiável)
  2. POST /s3               -> file vai pra files/temp/{user_id}/
  3. POST /posts            -> cria tarefa + AUTO-ANEXA arquivos da pasta temp do user

A API pública /api/v1/posts NÃO suporta upload. Por isso usamos os endpoints web.
"""
from __future__ import annotations

import gzip
import http.cookiejar
import re
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

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
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
            raise AdvboxLoginError(
                "2fa_required",
                "ADVBOX exigiu 2FA. Faça login manual no painel pra renovar trust de 30 dias.",
            )

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
