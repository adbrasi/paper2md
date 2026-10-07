import time
import httpx
from urllib.parse import urlparse


class PaperError(ValueError):
    pass


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise PaperError("URL inválida: forneça HTTP(S) sem credenciais embutidas.")
    return url


class Transport:
    def __init__(self, client=None, max_bytes=200 * 1024 * 1024):
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=20), follow_redirects=True,
                                             max_redirects=5, headers={"User-Agent": "paper2md/0.1 (personal paper retrieval)"})
        self.owned = client is None
        self.max_bytes = max_bytes

    def close(self):
        if self.owned:
            self.client.close()

    def _status(self, response, service):
        if response.is_success:
            return
        status = response.status_code
        detail = {401: "autenticação inválida", 403: "acesso bloqueado; use um PDF local se tiver acesso",
                  404: "documento não encontrado", 429: "limite de requisições/orçamento atingido",
                  402: "créditos insuficientes"}.get(status, "requisição recusada")
        raise PaperError(f"{service}: HTTP {status}, {detail}.")

    def get(self, url, params=None, headers=None, service="Fonte", limit=None):
        public_url(url)
        bound = limit if limit is not None else self.max_bytes
        for attempt in range(3):
            try:
                with self.client.stream("GET", url, params=params, headers=headers) as response:
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        retry = response.headers.get("retry-after", "")
                        delay = min(float(retry), 5) if retry.replace(".", "", 1).isdigit() else 2 ** attempt
                        time.sleep(delay)
                        continue
                    self._status(response, service)
                    chunks, size = [], 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > bound:
                            raise PaperError(f"{service}: download excede limite de {bound // 1024 // 1024} MiB.")
                        chunks.append(chunk)
                    return b"".join(chunks), str(response.url), response.headers
            except httpx.HTTPError:
                if attempt == 2:
                    raise PaperError(f"{service}: falha de conexão ou timeout.") from None
                time.sleep(2 ** attempt)
        raise PaperError(f"{service}: tentativas esgotadas.")

    def json_get(self, url, **kwargs):
        import json
        content, _, _ = self.get(url, **kwargs)
        try:
            return json.loads(content)
        except (ValueError, UnicodeDecodeError):
            raise PaperError("Fonte retornou JSON inválido.") from None

    def post_json(self, url, payload, key, service="Mistral"):
        try:
            response = self.client.post(url, json=payload, headers={"Authorization": f"Bearer {key}"})
            self._status(response, service)
            return response.json()
        except httpx.HTTPError:
            raise PaperError(f"{service}: falha de conexão/timeout; chamada paga não repetida automaticamente.") from None
        except (ValueError, UnicodeDecodeError) as exc:
            if isinstance(exc, PaperError):
                raise
            raise PaperError(f"{service}: resposta JSON inválida.") from None
