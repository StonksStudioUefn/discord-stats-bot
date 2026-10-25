"""
widget_site.py
==============
Genera el archivo docs/widgets.json que alimenta la página web de
GitHub Pages. Contiene, por cada juego y stat, el top (nombre, valor
formateado, VIP) y los metadatos para mostrarlo bien en la web (título,
color, emoji, fecha), más los datos públicos del mapa (nombre oficial,
enlace a fortnite.gg e imagen, del servicio común de islas; ver fortnite_gg.py).

El bot llama a generar_widgets_json() al final de cada actualización;
el workflow de GitHub Actions hace luego commit+push de este archivo,
y GitHub Pages lo sirve.
"""

import json
import os
from datetime import datetime, timezone

from formatting import format_value
from fortnite_gg import info_islas, normalizar_codigo, url_isla
from games import GAMES, game_enabled, stat_lower_is_better

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


def _islas_anteriores() -> dict[str, dict]:
    """La 'island' de cada juego en el widgets.json actual (si lo hay)."""
    try:
        with open(WIDGETS_JSON_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        return {
            g["key"]: g["island"]
            for g in doc.get("games", [])
            if isinstance(g.get("island"), dict)
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


async def _islas(juegos: dict[str, dict]) -> dict[str, dict]:
    """
    Nombre, enlace e imagen del mapa de cada juego (fortnite_gg.py). Lo que
    no se pueda sacar ahora se conserva de la última vez, para que un fallo
    puntual del servicio de islas no deje la web sin imágenes.
    """
    codigos = {
        k: normalizar_codigo(cfg.get("island_code", ""))
        for k, cfg in juegos.items()
    }
    codigos = {k: c for k, c in codigos.items() if c}
    try:
        nuevas = await info_islas(codigos)
    except Exception as e:  # la web no debe caerse por el servicio de islas
        print(f"[WEB] No pude consultar las islas: {e}")
        nuevas = {}
    anteriores = _islas_anteriores()

    islas = {}
    for k, codigo in codigos.items():
        isla = {"code": codigo, "url": url_isla(codigo)}
        previa = anteriores.get(k, {})
        if previa.get("code") != codigo:
            previa = {}  # cambió el código: lo de antes es de otra isla
        nueva = nuevas.get(k, {})
        for campo in ("name", "creator", "released", "icon", "thumb"):
            isla[campo] = nueva.get(campo) or previa.get(campo)
        islas[k] = isla
    return islas


async def generar_widgets_json(obtener_top) -> None:
    """
    Construye docs/widgets.json con los leaderboards de todos los juegos.

    obtener_top:  async (game_key, stat_key, limit, ascending) -> lista de filas
                  con username / best_value / is_vip.
    """
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    juegos = []
    activos = {k: cfg for k, cfg in GAMES.items() if game_enabled(cfg)}
    islas = await _islas(activos)

    # Los juegos desactivados (enabled: False) no aparecen en la web.
    for game_key, game_config in activos.items():
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
            stats.append(
                {
                    "key": stat_key,
                    "title": stat_info.get("title", stat_key.upper()),
                    "emoji": stat_info.get("emoji", ""),
                    "color": _color_hex(stat_info.get("widget_color")),
                    "rows": filas,
                    "updated": ahora,
                }
            )

        juegos.append(
            {
                "key": game_key,
                "name": game_config["display_name"],
                "emoji": game_config.get("emoji", "🎮"),
                "color": _color_juego(game_config),
                "island": islas.get(game_key),
                "stats": stats,
            }
        )

    documento = {"updated": ahora, "games": juegos}

    os.makedirs(os.path.dirname(WIDGETS_JSON_PATH), exist_ok=True)
    with open(WIDGETS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(documento, f, ensure_ascii=False, indent=2)

    print(f"[WEB] Escrito {WIDGETS_JSON_PATH} ({len(juegos)} juegos).")
