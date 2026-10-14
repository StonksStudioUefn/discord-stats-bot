"""
fortnite_gg.py
==============
Datos públicos de la isla de cada juego para la web de widgets: nombre
oficial del mapa, creador, enlace a fortnite.gg y su imagen.

De dónde sale cada cosa (como en la app de FINANZAS, js/services/fortniteGg.js):
  - Nombre y creador: la API pública de Epic
      https://api.fortnite.com/ecosystem/v1/islands/<código>
    Si falla, el nombre se recorta del <title> de la ficha de fortnite.gg.
  - Imagen: la ficha de fortnite.gg, leída a través de r.jina.ai
    (fortnite.gg bloquea las peticiones automáticas). Epic no da imágenes
    en su API pública.

Icono vs miniatura
------------------
Epic ha añadido el «island name logo» (PNG transparente de 1440x608), pero
a día de hoy ni su API pública ni fortnite.gg lo enseñan: solo la miniatura
apaisada (landscape_comp*.jpeg). Si alguna vez aparece en la ficha una
imagen de Epic que parezca el logo (logo/icon/title/name en el nombre del
archivo) se guarda en 'icon'; la miniatura se guarda siempre en 'thumb' y
la web la usa cuando no hay icono.

Todo lo que viene de aquí es texto de terceros: se limpia y se acota, y la
web lo escapa al pintarlo. Las imágenes solo se aceptan del CDN de Epic.
Nada de esto lanza: si algo falla se devuelve lo que se haya podido sacar.
"""

import asyncio
import re

import aiohttp

EPIC_API = "https://api.fortnite.com/ecosystem/v1/islands/"
LECTOR = "https://r.jina.ai/"
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
_PARECE_ICONO = re.compile(r"(logo|icon|title|name)", re.IGNORECASE)


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


def _nombre_de_titulo(titulo, codigo: str) -> str:
    """
    «NOMBRE CODIGO by autor - Fortnite Creative Map Code» -> «NOMBRE».
    Solo vale un título que lleve el código: si la isla no existe o salta
    el reto de Cloudflare, el lector contesta 200 con «Page Not Found» o
    «Just a moment...», y eso no es un nombre.
    """
    t = str(titulo or "")
    i = t.find(codigo)
    return limpiar_nombre(t[:i]) if i > 0 else ""


def _creador_de_titulo(titulo, codigo: str) -> str:
    """«NOMBRE CODIGO by autor - Fortnite Creative Map Code» -> «autor»."""
    m = re.search(re.escape(codigo) + r" by (.+?) - Fortnite", str(titulo or ""))
    return limpiar_nombre(m[1]) if m else ""


def _elegir_imagenes(contenido: str) -> dict:
    """De las imágenes de Epic que trae la ficha: el icono (si lo hay) y la miniatura."""
    urls = list(dict.fromkeys(_IMG_EPIC.findall(contenido or "")))
    nombre = lambda u: u.rsplit("/", 1)[-1]
    icono = next((u for u in urls if _PARECE_ICONO.search(nombre(u))), None)
    apaisadas = [u for u in urls if nombre(u).startswith("landscape")]
    # La pequeña (480x270) basta para la web; si no está, la grande.
    miniatura = next(
        (u for u in apaisadas if "_comp_s" in nombre(u)),
        apaisadas[0] if apaisadas else None,
    )
    return {"icon": icono, "thumb": miniatura}


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


async def info_isla(sesion: aiohttp.ClientSession, codigo_crudo: str) -> dict | None:
    """
    {code, url, name, creator, icon, thumb} de la isla. Los campos que no
    se hayan podido sacar van a None. None si el código no es válido.
    """
    codigo = normalizar_codigo(codigo_crudo)
    if not codigo:
        return None

    epic, gg = await asyncio.gather(
        _json(sesion, EPIC_API + codigo),
        _json(
            sesion,
            LECTOR + url_isla(codigo),
            headers={"Accept": "application/json"},
        ),
    )

    nombre = limpiar_nombre((epic or {}).get("title"))
    creador = limpiar_nombre((epic or {}).get("creatorCode"))

    datos_gg = (gg or {}).get("data") or {}
    if datos_gg.get("warning") or (gg or {}).get("warning"):
        datos_gg = {}
    if not nombre:
        nombre = _nombre_de_titulo(datos_gg.get("title"), codigo)
    if not creador:
        creador = _creador_de_titulo(datos_gg.get("title"), codigo)

    return {
        "code": codigo,
        "url": url_isla(codigo),
        "name": nombre or None,
        "creator": creador or None,
        **_elegir_imagenes(datos_gg.get("content", "")),
    }


async def info_islas(codigos: dict[str, str]) -> dict[str, dict]:
    """{clave_juego: código} -> {clave_juego: info_isla}, todas a la vez."""
    timeout = aiohttp.ClientTimeout(total=ESPERA_S)
    async with aiohttp.ClientSession(timeout=timeout) as sesion:
        claves = list(codigos)
        resultados = await asyncio.gather(
            *(info_isla(sesion, codigos[k]) for k in claves)
        )
    return {k: r for k, r in zip(claves, resultados) if r}
