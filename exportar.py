"""
exportar.py
===========
Saca de Supabase todo lo que necesita la app nueva de leaderboards
(stonks-ecosistema/leaderboards, en Cloudflare) para empezar donde lo deja
este bot: la tabla leaderboard entera y bot_state (punteros, embeds,
bloqueados). Lo escribe en export.json; el workflow «Exportar» lo sube como
artefacto y se importa en el panel (Estado → Importar del bot de GitHub).
"""

import json

from supabase import create_client

from config import SUPABASE_KEY, SUPABASE_URL

_supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def _todo(tabla: str, columnas: str) -> list[dict]:
    """Todas las filas, de 1000 en 1000 (el tope de Supabase por consulta)."""
    filas, desde = [], 0
    while True:
        lote = _supabase.table(tabla).select(columnas).range(desde, desde + 999).execute().data or []
        filas += lote
        if len(lote) < 1000:
            return filas
        desde += 1000


if __name__ == "__main__":
    datos = {
        "leaderboard": _todo("leaderboard", "game,discord_id,stat,best_value,username,is_vip,updated_at"),
        "bot_state": _todo("bot_state", "key,value"),
    }
    # NUMERIC llega como número o texto: siempre texto, sin perder cifras.
    for f in datos["leaderboard"]:
        f["best_value"] = str(f["best_value"]).split(".")[0]
    with open("export.json", "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False)
    print(f"[EXPORT] {len(datos['leaderboard'])} filas de leaderboard, {len(datos['bot_state'])} de bot_state.")
