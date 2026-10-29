"""Ícone do app nas abas do navegador e na tela inicial do celular (favicon)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

BASE = Path(__file__).resolve().parent
router = APIRouter()
HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(BASE / "gepeto.ico", media_type="image/x-icon", headers=HEADERS)


@router.get("/icone-192.png", include_in_schema=False)
def icon_192():
    return FileResponse(BASE / "web" / "icone-192.png", media_type="image/png", headers=HEADERS)


@router.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(BASE / "web" / "apple-touch-icon.png", media_type="image/png", headers=HEADERS)
