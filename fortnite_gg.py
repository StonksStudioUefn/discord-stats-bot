"""
fortnite_gg.py
==============
Datos públicos de la isla de cada juego para la web de widgets: nombre
oficial del mapa, creador, enlace a fortnite.gg y su miniatura.

Todo sale del servicio común de islas de STONKS (stonks-islas), que lo lee
para todas las apps (Oscar, 25/10/2026): el nombre y el creador, de la API
pública de Epic una vez al día; la miniatura, de la ficha de fortnite.gg
una vez al día (Epic no da imágenes); los jugadores, de Epic cada 10 min.
El bot no habla ni con Epic ni con fortnite.gg: lee
    https://islas.stonksstudio.com/publico/islas.json
Las islas tienen que estar registradas como públicas en el servicio
(islas.registrar del conector STONKS, app «bot»).

Todo lo que viene de aquí es texto de terceros: se limpia y se acota, y la
web lo escapa al pintarlo. Las imágenes solo se aceptan del CDN de Epic.
Nada de esto lanza: si algo falla se devuelve lo que se haya podido sacar.
"""

import asyncio
import re

import aiohttp

ISLAS_JSON = "https://islas.stonksstudio.com/publico/islas.json"
ESPERA_S = 25
MAX_NOMBRE = 120

# Controles, formato (marcas de dirección, anchura cero), uso privado y
# selectores de variante: en un nombre no pintan nada y pueden desordenar
# lo que se enseña (igual que limpiarNombre en FINANZAS).
_CONTROLES = re.compile(
    "[\u0000-\u001f\u007f-\u009f­​-‏ -‮"
    "⁠-⁯︀-️﻿-]"
)
_IMG_EPIC = re.compile(
    r"https://cdn-\d+\.qstv\.on\.epicgames\.com/[A-Za-z0-9_/.-]+?\.(?:png|jpe?g|webp)"
)


def normalizar_codigo(texto: str) -> str:
    """'(2943-6452-4033)' -> '2943-6452-4033'; '' si no es un código."""
    m = re.search(r"(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})", str(texto or ""))
    return f"{m[1]}-{m[2]}-{m[3]}" if m else ""


def url_isla(codigo: str) -> str:
    return f"https://fortnite.gg/island?code={codigo}"


def limpiar_nombre(valor) -> str:
    t = _CONTROLES.sub(" ", str(valor or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_NOMBRE].strip()


def miniatura(url) -> str | None:
    """La URL solo si es del CDN de Epic: va tal cual a un src de la web."""
    u = str(url or "")
    return u if len(u) <= 400 and _IMG_EPIC.fullmatch(u) else None


async def _json(sesion: aiohttp.ClientSession, url: str, **kw):
    try:
        async with sesion.get(url, **kw) as r:
            if r.status != 200:
                print(f"[FNGG] {url} respondió {r.status}")
                return None
            return await r.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        print(f"[FNGG] {url}: {type(e).__name__} {e}")
        return None


async def info_islas(codigos: dict[str, str]) -> dict[str, dict]:
    """
    {clave_juego: código} -> {clave_juego: {code, url, name, creator, thumb}}.
    Los campos que el servicio aún no tenga van a None; las islas que no
    salgan en el JSON (no registradas o sin leer), no aparecen.
    """
    timeout = aiohttp.ClientTimeout(total=ESPERA_S)
    async with aiohttp.ClientSession(timeout=timeout) as sesion:
        doc = await _json(sesion, ISLAS_JSON)
    por_codigo = {
        normalizar_codigo(i.get("code")): i
        for i in (doc or {}).get("islands") or []
        if isinstance(i, dict)
    }
    islas = {}
    for clave, crudo in codigos.items():
        codigo = normalizar_codigo(crudo)
        isla = por_codigo.get(codigo) if codigo else None
        if not isla:
            continue
        islas[clave] = {
            "code": codigo,
            "url": url_isla(codigo),
            "name": limpiar_nombre(isla.get("name")) or None,
            "creator": limpiar_nombre(isla.get("creator")) or None,
            "thumb": miniatura(isla.get("thumb_url")),
        }
    return islas
