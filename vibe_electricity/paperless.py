"""Minimal read-only Paperless-ngx API client (this app never writes to Paperless)."""

from __future__ import annotations

import httpx

from .config import get_settings


class PaperlessError(RuntimeError):
    pass


class Paperless:
    def __init__(self, url: str | None = None, token: str | None = None, timeout: float = 30.0):
        s = get_settings()
        self.url = (url or s.paperless_url).rstrip("/")
        token = token if token is not None else s.paperless_token
        self.client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _get(self, path: str, **params) -> dict:
        try:
            r = self.client.get(self.url + path, params=params or None)
        except httpx.HTTPError as exc:
            raise PaperlessError(f"Paperless δεν απαντά ({self.url}): {exc}") from exc
        if r.status_code in (401, 403):
            raise PaperlessError("Paperless: λάθος ή χωρίς δικαιώματα token")
        if r.status_code == 404:
            raise PaperlessError(f"Paperless: δεν βρέθηκε {path}")
        if r.status_code >= 400:
            raise PaperlessError(f"Paperless: HTTP {r.status_code} για {path}")
        return r.json()

    def tag_id(self, name: str) -> int | None:
        data = self._get("/api/tags/", name__iexact=name)
        for t in data.get("results", []):
            if t["name"].lower() == name.lower():
                return t["id"]
        return None

    def tagged_documents(self, tag_id: int) -> list[dict]:
        out, page = [], 1
        while True:
            data = self._get("/api/documents/", tags__id__all=tag_id, page=page, page_size=100,
                             fields="id,title,modified,tags", ordering="id")
            out.extend(data.get("results", []))
            if not data.get("next"):
                return out
            page += 1

    def document(self, doc_id: int) -> dict:
        return self._get(f"/api/documents/{doc_id}/")

    def checksum(self, doc_id: int) -> str | None:
        return self._get(f"/api/documents/{doc_id}/metadata/").get("original_checksum")

    def ping(self) -> dict:
        return self._get("/api/documents/", page_size=1, fields="id")


def document_link(doc_id: int) -> str:
    return f"{get_settings().public_paperless}/documents/{doc_id}/details"
