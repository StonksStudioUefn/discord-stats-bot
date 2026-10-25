"""
fortnite_gg.py
==============
El código de isla de cada juego y su enlace a fortnite.gg.

El nombre, el creador, la miniatura y los jugadores no se guardan en el bot:
son del servicio común de islas de STONKS (Oscar, 25/10/2026), y la web los
lee al abrirse de https://islas.stonksstudio.com/publico/islas.json. Las
islas tienen que estar registradas como públicas en el servicio
(islas.registrar del conector STONKS, app «bot»).
"""

import re


def normalizar_codigo(texto: str) -> str:
    """'(2943-6452-4033)' -> '2943-6452-4033'; '' si no es un código."""
    m = re.search(r"(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})", str(texto or ""))
    return f"{m[1]}-{m[2]}-{m[3]}" if m else ""


def url_isla(codigo: str) -> str:
    return f"https://fortnite.gg/island?code={codigo}"
