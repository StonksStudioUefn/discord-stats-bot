"""
widget_site.py
==============
Genera el archivo docs/widgets.json que alimenta la página web de
GitHub Pages. Contiene, por cada juego y stat, el T3D del widget ya
rellenado (listo para copiar y pegar en UEFN), más metadatos para
mostrarlo bien en la web (título, color, emoji, top 10, fecha).

El bot llama a generar_widgets_json() al final de cada actualización;
el workflow de GitHub Actions hace luego commit+push de este archivo,
y GitHub Pages lo sirve.
"""

import json
import os
from datetime import datetime, timezone

from formatting import format_value
from games import GAMES, TEMPLATE_UEFN_PROJECT, game_enabled, stat_lower_is_better
from widget_export import build_widget_t3d

_DIR = os.path.dirname(os.path.abspath(__file__))
WIDGETS_JSON_PATH = os.path.join(_DIR, "docs", "widgets.json")


def _color_hex(color_rgb) -> str | None:
    """(r,g,b) en 0-1 -> '#rrggbb' para usarlo como acento en la web."""
    if not color_rgb:
        return None
    r, g, b = color_rgb
    return "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )


def _color_juego(game_config: dict) -> str | None:
    """
    Color de acento del juego para sus tabs. Usa game_config['color']
    (entero 0xRRGGBB) si existe; si no, el color de su primera stat.
    """
    c = game_config.get("color")
    if isinstance(c, int):
        return "#{:06x}".format(c & 0xFFFFFF)
    for stat_info in game_config["stats"].values():
        col = stat_info.get("widget_color")
        if col:
            return _color_hex(col)
    return None


async def generar_widgets_json(plantilla: str | None, obtener_top) -> bool:
    """
    Construye docs/widgets.json con los widgets de todos los juegos.

    plantilla:    contenido T3D de la plantilla (o None si falta).
    obtener_top:  async (game_key, stat_key, limit, ascending) -> lista de filas
                  con username / best_value / is_vip.

    Devuelve True si se escribió el archivo, False si no había plantilla.
    """
    if plantilla is None:
        print("[WEB] No hay plantilla del widget; no genero widgets.json.")
        return False

    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    juegos = []

    for game_key, game_config in GAMES.items():
        # Saltar juegos desactivados (enabled: False): no aparecen en la web.
        if not game_enabled(game_config):
            continue
        stats = []
        for stat_key, stat_info in game_config["stats"].items():
            top = await obtener_top(
                game_key, stat_key, limit=game_config["top_size"],
                ascending=stat_lower_is_better(stat_info),
            )
            fmt = stat_info.get("format", "raw")
            filas = [
                {
                    "name": fila["username"],
                    "value": format_value(int(fila["best_value"]), fmt),
                    "isVip": bool(fila.get("is_vip", False)),
                }
                for fila in top
            ]
            titulo = stat_info.get("title", stat_key.upper())
            color = stat_info.get("widget_color")

            t3d = build_widget_t3d(
                template_t3d=plantilla,
                rows=filas,
                title=titulo,
                color_rgb=color,
                rows_count=game_config["top_size"],
                template_project=TEMPLATE_UEFN_PROJECT,
                target_project=game_config.get("uefn_project"),
            )

            stats.append(
                {
                    "key": stat_key,
                    "title": titulo,
                    "emoji": stat_info.get("emoji", ""),
                    "color": _color_hex(color),
                    "rows": filas,        # para la vista previa
                    "t3d": t3d,           # lo que se copia a UEFN
                    "updated": ahora,
                }
            )

        juegos.append(
            {
                "key": game_key,
                "name": game_config["display_name"],
                "emoji": game_config.get("emoji", "🎮"),
                "color": _color_juego(game_config),
                "stats": stats,
            }
        )

    documento = {"updated": ahora, "games": juegos}

    os.makedirs(os.path.dirname(WIDGETS_JSON_PATH), exist_ok=True)
    with open(WIDGETS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(documento, f, ensure_ascii=False, indent=2)

    print(f"[WEB] Escrito {WIDGETS_JSON_PATH} ({len(juegos)} juegos).")
    return True
