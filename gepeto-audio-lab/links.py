"""Links salvos do Gepeto Audio Lab: cola um link, o app guarda o nome e o ícone do site.

Módulo independente: o app.py só precisa de `app.include_router(links.router)`
e a página de `<script src="/links.js" defer></script>`.
"""
from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("GEPETO_DADOS", BASE / "dados"))
LINKS_FILE = DATA / "links.json"
ICONS_DIR = DATA / "links_icones"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) GepetoAudioLab/1.0"
MAX_HTML = 512 * 1024
MAX_ICON = 256 * 1024
MAX_LINKS = 200
ICON_TYPES = {"image/png": "png", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
              "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "image/svg+xml": "svg"}
ICON_MEDIA = {value: key for key, value in ICON_TYPES.items() if key != "image/vnd.microsoft.icon"}

router = APIRouter()
lock = threading.Lock()


class LinkRequest(BaseModel):
    url: str


# ---------------------------------------------------------------- dados

def read_links() -> list[dict]:
    try:
        return json.loads(LINKS_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return []


def write_links(links: list[dict]) -> None:
    tmp = LINKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(links, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, LINKS_FILE)


def public(entry: dict) -> dict:
    return {"id": entry["id"], "name": entry["name"], "url": entry["url"], "host": entry["host"],
            "icon": f"/api/links/{entry['id']}/icon" if entry.get("icon") else None,
            "created": entry["created"]}


# ---------------------------------------------------------------- busca do site

def normalize(raw: str) -> str:
    raw = raw.strip()
    if not raw or len(raw) > 2000 or re.search(r"\s", raw):
        raise HTTPException(400, "Cole um link válido.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname or ("." not in parts.hostname and parts.hostname != "localhost"):
        raise HTTPException(400, "Cole um link válido, começando com http:// ou https://.")
    return urllib.parse.urlunsplit(parts)


def is_public_host(host: str) -> bool:
    """Só busca nome e ícone de sites da internet, nunca de endereços da rede local."""
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%")[0])
        if not ip.is_global:
            return False
    return bool(addresses)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).hostname or ""
        if not newurl.lower().startswith(("http://", "https://")) or not is_public_host(host):
            raise urllib.error.URLError("redirecionamento bloqueado")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = urllib.request.build_opener(SafeRedirect)


def fetch(url: str, limit: int, timeout: float = 6.0) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5"})
    with opener.open(request, timeout=timeout) as response:
        body = response.read(limit)
        return body, response.headers.get_content_type(), response.headers.get_content_charset() or "utf-8"


def attribute(tag: str, name: str) -> str | None:
    match = re.search(rf"""\b{name}\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", tag, re.I)
    return html.unescape(next(group for group in match.groups() if group is not None)).strip() if match else None


def parse_page(page: str, base_url: str) -> tuple[str | None, list[str]]:
    name = None
    for tag in re.findall(r"<meta\b[^>]*>", page, re.I):
        if (attribute(tag, "property") or "").lower() == "og:site_name" and attribute(tag, "content"):
            name = attribute(tag, "content")
            break
    if not name:
        title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        if title:
            name = re.sub(r"\s+", " ", html.unescape(title.group(1))).strip() or None
    icons: list[tuple[int, str]] = []
    for tag in re.findall(r"<link\b[^>]*>", page, re.I):
        rel = (attribute(tag, "rel") or "").lower()
        href = attribute(tag, "href")
        if href and "icon" in rel and "mask-icon" not in rel:
            score = 2 if "apple-touch" in rel else 1
            icons.append((score, urllib.parse.urljoin(base_url, href)))
    ordered = [href for _, href in sorted(icons, key=lambda item: -item[0])]
    return (name[:80] if name else None), ordered


def look_up(url: str, link_id: str) -> tuple[str | None, str | None]:
    """Devolve (nome do site, arquivo do ícone). Falhas viram None: o link é salvo mesmo assim."""
    parts = urllib.parse.urlsplit(url)
    if not is_public_host(parts.hostname or ""):
        return None, None
    name, candidates = None, []
    try:
        body, kind, charset = fetch(url, MAX_HTML)
        if "html" in kind:
            name, candidates = parse_page(body.decode(charset, errors="replace"), url)
    except Exception:  # noqa: BLE001 - site fora do ar, bloqueio etc.
        pass
    candidates.append(f"{parts.scheme}://{parts.netloc}/favicon.ico")
    for candidate in candidates[:4]:
        try:
            body, kind, _ = fetch(candidate, MAX_ICON, timeout=5.0)
        except Exception:  # noqa: BLE001
            continue
        extension = ICON_TYPES.get(kind)
        if not extension and candidate.lower().split("?")[0].endswith(".ico"):
            extension = "ico"
        if extension and 16 < len(body) < MAX_ICON:
            filename = f"{link_id}.{extension}"
            (ICONS_DIR / filename).write_bytes(body)
            return name, filename
    return name, None


def host_label(host: str) -> str:
    return re.sub(r"^www\.", "", host.lower())


# ---------------------------------------------------------------- rotas

@router.get("/api/links")
def list_links():
    return [public(entry) for entry in read_links()]


@router.post("/api/links")
def add_link(body: LinkRequest):
    url = normalize(body.url)
    host = urllib.parse.urlsplit(url).hostname or ""
    with lock:
        links = read_links()
        if len(links) >= MAX_LINKS:
            raise HTTPException(400, "Você chegou ao limite de 200 links salvos. Apague algum para continuar.")
        if any(entry["url"].rstrip("/") == url.rstrip("/") for entry in links):
            raise HTTPException(409, "Esse link já está salvo.")
    link_id = uuid.uuid4().hex[:12]
    name, icon = look_up(url, link_id)
    entry = {"id": link_id, "name": name or host_label(host), "url": url, "host": host_label(host),
             "icon": icon, "created": time.time()}
    with lock:
        links = read_links()
        links.insert(0, entry)
        write_links(links)
    return public(entry)


@router.delete("/api/links/{link_id}")
def delete_link(link_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", link_id):
        raise HTTPException(404, "Link não encontrado.")
    with lock:
        links = read_links()
        entry = next((item for item in links if item["id"] == link_id), None)
        if not entry:
            raise HTTPException(404, "Link não encontrado.")
        write_links([item for item in links if item["id"] != link_id])
    if entry.get("icon"):
        (ICONS_DIR / Path(entry["icon"]).name).unlink(missing_ok=True)
    return {"ok": True}


@router.get("/api/links/{link_id}/icon")
def link_icon(link_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", link_id):
        raise HTTPException(404, "Ícone não encontrado.")
    entry = next((item for item in read_links() if item["id"] == link_id), None)
    path = ICONS_DIR / Path(entry["icon"]).name if entry and entry.get("icon") else None
    if not path or not path.is_file():
        raise HTTPException(404, "Ícone não encontrado.")
    media = ICON_MEDIA.get(path.suffix.lstrip(".").lower(), "application/octet-stream")
    # sandbox + nosniff: um SVG de terceiros nunca roda scripts dentro do app
    return FileResponse(path, media_type=media, headers={
        "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
        "Cache-Control": "public, max-age=86400"})


@router.get("/links.js")
def links_script():
    return FileResponse(BASE / "web" / "links.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})
