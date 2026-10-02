"""
games.py
========
CONFIGURACIÓN DE JUEGOS.

Este es el ÚNICO archivo que tienes que tocar para añadir o quitar juegos.

ARQUITECTURA DE CANALES (única para todos los juegos):
  - SUBMIT_CHANNEL:    canal compartido donde los jugadores suben todas
                       las capturas. El bot identifica el juego por el
                       CÓDIGO DE ISLA que lea en la imagen.
  - LEADERBOARD_CHANNEL: canal público de solo lectura donde el bot
                       publica/edita un embed por juego con sus rankings.
  - SUMMARY_CHANNEL:   canal privado de moderadores con los .json de
                       respaldo (un archivo adjunto por juego).

Cada juego se describe con:
  - display_name:  cómo aparece en los mensajes del bot.
  - island_code:   código de isla esperado (sirve para identificar el
                   juego al recibir una captura).
  - color:         entero RGB para el borde del embed (ej. 0xFF3355).
  - player_name_description: pista para Gemini sobre el nombre del jugador.
  - stats:         diccionario {clave_interna: {desc, format, emoji, title}}.
  - top_size:      cuántos jugadores muestra cada ranking.

Para añadir un juego nuevo: copia un bloque y modifícalo.
"""

# ---------------------------------------------------------------------
# Canales (nombres EXACTOS de Discord; copia y pega desde Discord si
# llevan caracteres especiales como '︱' U+FE31).
# ---------------------------------------------------------------------
SUBMIT_CHANNEL = "📤︱submit-stats"
LEADERBOARD_CHANNEL = "🏆︱leaderboards"
SUMMARY_CHANNEL = "📊︱leaderboard-data"


# ---------------------------------------------------------------------
# Proyecto UEFN de la PLANTILLA del widget.
# La plantilla (widget_templates/leaderboard_widget.t3d) se copió desde
# este proyecto, así que sus rutas internas (ExportPath) contienen este
# nombre. El bot lo reemplaza por el 'uefn_project' de cada juego al
# generar su widget, para que las rutas apunten al proyecto correcto.
# Si algún día rehaces la plantilla desde otro proyecto, cambia esto.
# ---------------------------------------------------------------------
TEMPLATE_UEFN_PROJECT = "MT_LasersForBrainrots"


# ---------------------------------------------------------------------
# Sufijos del juego (Verse: STRING_Abbrev). Se derivan automáticamente
# de formatting.ABBREV para que SIEMPRE estén sincronizados: si cambias
# la lista en formatting.py, esto se actualiza solo.
# ---------------------------------------------------------------------
from formatting import ABBREV as _ABBREV

# Todos los sufijos reales (sin el primero, que es "" = unidades).
SUFIJOS_DEL_JUEGO = ", ".join(s for s in _ABBREV if s)

# Stats compartidas (income/cash). Si en el futuro un juego tiene stats
# distintas, defínelas en línea en su bloque y no uses esta plantilla.
STATS_INCOME_CASH = {
    "income": {
        "desc": (
            "Número AMARILLO etiquetado 'INCOME' DENTRO de la tarjeta "
            "negra titulada 'LIFETIME STATS' (la del medio, con borde "
            "arcoíris y el avatar del jugador a la izquierda). Tiene "
            "DOS partes separadas por un ESPACIO: dígitos y sufijo. "
            "Lleva el símbolo '$' delante y termina en '/s' "
            "(ejemplo: '$43.30 Qa/s', '$28 Oc/s'). "
            "IMPORTANTE: NO uses el valor parecido que aparece en el "
            "HUD lateral del juego (esquina izquierda con icono de "
            "rayo); ese es el income actual, NO el lifetime. SOLO el "
            "que está dentro de la tarjeta LIFETIME STATS. "
            "Si DENTRO de la tarjeta hubiera por error más de un "
            "valor candidato a 'INCOME', escoge el MÁS ALTO. "
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "income",
        "emoji": "💰",
        "title": "MOST INCOME",
        "widget_color": (1.0, 0.8705882, 0.1254902),  # amarillo
    },
    "cash": {
        "desc": (
            "Número VERDE etiquetado 'CASH' DENTRO de la tarjeta negra "
            "titulada 'LIFETIME STATS' (la del medio, con borde "
            "arcoíris y el avatar del jugador a la izquierda). Tiene "
            "DOS partes separadas por un ESPACIO: dígitos y sufijo. "
            "Lleva el símbolo '$' delante (ejemplo: '$117.5 Sx', "
            "'$1.2 Qa'). "
            "IMPORTANTE: NO uses el valor parecido que aparece en el "
            "HUD lateral del juego (esquina izquierda con icono de "
            "billetes); ese es el cash actual, NO el lifetime. SOLO "
            "el que está dentro de la tarjeta LIFETIME STATS. "
            "Si DENTRO de la tarjeta hubiera por error más de un "
            "valor candidato a 'CASH', escoge el MÁS ALTO. "
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "money",
        "emoji": "💵",
        "title": "MOST CASH",
        "widget_color": (0.0, 0.8823529, 0.0470588),  # verde
    },
}

# Stats del modo "Keyboard Escape": SPEED y WINS. No llevan '$' ni '/s'
# (no son dinero ni dinero/segundo), pero sí pueden tener sufijos del
# juego (8.2K, 1.5M, etc).
STATS_SPEED_WINS = {
    "speed": {
        "desc": (
            "Número en TEXTO ROJO etiquetado 'SPEED' DENTRO de la "
            "tarjeta negra titulada 'LIFETIME STATS' (la del medio, con "
            "borde arcoíris y el avatar del jugador a la izquierda). "
            "Tiene DOS partes separadas por un ESPACIO: dígitos y "
            "sufijo (ejemplo: '8.2 K', '1.5 M', '125'). NO lleva el "
            "símbolo '$' delante. Es la fila que está ENCIMA de 'WINS'.\n"
            "Si DENTRO de la tarjeta hubiera por error más de un valor "
            "candidato a 'SPEED', escoge el MÁS ALTO. "
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "plain",   # -> '8.2K' (sin símbolo monetario)
        "emoji": "🏃",
        "title": "MOST SPEED",
        "widget_color": (1.0, 0.0, 0.0),  # rojo
    },
    "wins": {
        "desc": (
            "Número en TEXTO AMARILLO etiquetado 'WINS' DENTRO de la "
            "tarjeta negra titulada 'LIFETIME STATS' (la del medio, con "
            "borde arcoíris y el avatar del jugador a la izquierda). "
            "Tiene DOS partes separadas por un ESPACIO: dígitos y "
            "sufijo (ejemplo: '1 K', '500', '2.5 M'). NO lleva el "
            "símbolo '$' delante. Es la fila que está DEBAJO de 'SPEED'.\n"
            "Si DENTRO de la tarjeta hubiera por error más de un valor "
            "candidato a 'WINS', escoge el MÁS ALTO. "
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "plain",
        "emoji": "🏆",
        "title": "MOST WINS",
        "widget_color": (1.0, 0.8705882, 0.1254902),  # amarillo
    },
}

# Stats para el modo "Find The Needle".
STATS_NEEDLE = {
    "wins": {
        "desc": (
            "Número en TEXTO AMARILLO etiquetado 'WINS' DENTRO de la "
            "tarjeta negra titulada 'LIFETIME STATS'. "
            "Tiene DOS partes separadas por un ESPACIO: dígitos y "
            "sufijo (ejemplo: '1 K', '500', '2.5 M'). NO lleva el "
            "símbolo '$' delante.\n"
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "plain",
        "emoji": "🏆",
        "title": "MOST WINS",
        "widget_color": (1.0, 0.8705882, 0.1254902),  # amarillo
    },
    "hay_collected": {
        "desc": (
            "Número en TEXTO NARANJA etiquetado como 'Hay Collected' "
            "DENTRO de la tarjeta negra titulada 'LIFETIME STATS'. "
            "Tiene DOS partes separadas por un ESPACIO: dígitos y "
            "sufijo (ejemplo: '117.5 Sx', '1.2 Qa', '800'). "
            "NO lleva el símbolo '$' delante.\n"
            f"Sufijos posibles: {SUFIJOS_DEL_JUEGO}."
        ),
        "format": "plain",  # Cambiado a 'plain' ya que no tiene el símbolo de dólar ($)
        "emoji": "🌾",
        "title": "MOST HAY COLLECTED",
        "widget_color": (1.0, 0.549, 0.0),  # naranja
    },
    "best_time": {
        "desc": (
            "Tiempo en TEXTO AZUL etiquetado 'BEST TIME' DENTRO de la "
            "tarjeta negra titulada 'LIFETIME STATS'. "
            "Representa el mejor tiempo de minijuego. "
            "Se muestra en formato de reloj usando dos puntos (ejemplo: '14:20' o '1:14:20'). "
            "Devuelve el tiempo EXACTAMENTE como aparece en pantalla."
        ),
        "format": "time", 
        "emoji": "⏱️",
        "title": "BEST TIME",
        "widget_color": (0.2, 0.6, 1.0),  # azul
    },
}

# Descripción común del nombre del jugador.
NOMBRE_JUGADOR_DESC = (
    "Texto blanco que aparece debajo de la imagen de perfil (avatar) "
    "del jugador."
)

# Descripción común del código de isla (en la captura).
ISLAND_CODE_DESC = (
    "Código de isla: texto BLANCO con BORDE NEGRO, en CURSIVA, ENTRE "
    "PARÉNTESIS, situado en la parte INFERIOR de la pantalla. Tiene el "
    "formato de tres grupos de dígitos separados por guiones dentro de "
    "paréntesis (ejemplo: '(2943-6452-4033)'). Devuélvelo TAL CUAL lo "
    "leas, incluyendo los paréntesis. Si no eres capaz de leerlo con "
    "certeza, o si no hay ningún código entre paréntesis visible, "
    "devuelve una cadena vacía."
)


GAMES: dict[str, dict] = {
    # ------------------------------------------------------------------
    # LASER FOR BRAINROTS
    # ------------------------------------------------------------------
    "laser_for_brainrots": {
        "display_name": "Laser For Brainrots",
        "emoji": "💥",
        "island_code": "2943-6452-4033",
        "color": 0xFF3355,  # rojo coral (laser)
        "uefn_project": "MT_LasersForBrainrots",
        "player_name_description": NOMBRE_JUGADOR_DESC,
        "stats": STATS_INCOME_CASH,
        "top_size": 10,
    },

    # ------------------------------------------------------------------
    # BE FLASH FOR BRAINROTS
    # ------------------------------------------------------------------
    "be_flash_for_brainrots": {
        "display_name": "Be Flash For Brainrots",
        "emoji": "⚡",
        "island_code": "7694-0608-3252",
        "color": 0xFFD93D,  # amarillo (flash/rayo)
        "uefn_project": "MT_BeFlashForBrainrots",
        "player_name_description": NOMBRE_JUGADOR_DESC,
        "stats": STATS_INCOME_CASH,
        "top_size": 10,
    },

    # ------------------------------------------------------------------
    # KICK FOR BRAINROTS
    # ------------------------------------------------------------------
    "kick_for_brainrots": {
        "display_name": "Kick For Brainrots",
        "emoji": "💪",
        "island_code": "4852-1373-7293",
        "color": 0x4ECDC4,  # verde turquesa (kick)
        "uefn_project": "brainrot_template",
        "player_name_description": NOMBRE_JUGADOR_DESC,
        "stats": STATS_INCOME_CASH,
        "top_size": 10,
    },

    # ------------------------------------------------------------------
    # KEYBOARD ESCAPE
    # ------------------------------------------------------------------
    "keyboard_escape": {
        "display_name": "Keyboard Escape",
        "emoji": "⌨️",
        "enabled": False,  # desactivado: ignora capturas y no se muestra
        "island_code": "1931-6763-0020",
        "color": 0x9966FF,  # morado (sin chocar con los otros tres)
        "uefn_project": "MT_KeyboardMusicParkour",
        "player_name_description": NOMBRE_JUGADOR_DESC,
        "stats": STATS_SPEED_WINS,
        "top_size": 10,
    },

    # ------------------------------------------------------------------
    # FIND THE NEEDLE
    # ------------------------------------------------------------------
    "find_the_needle": {
        "display_name": "Find The Needle",
        "emoji": "🪡",
        "island_code": "8541-5086-2780",
        "color": 0xFFA500,  # naranja
        "uefn_project": "MT_FindTheNeedle", # <-- RECUERDA: Cambiar esto por tu nombre de proyecto real
        "player_name_description": NOMBRE_JUGADOR_DESC,
        "stats": STATS_NEEDLE,
        "top_size": 10,
    },
}


# Inyecta automáticamente la descripción del código de isla en cada juego.
for _cfg in GAMES.values():
    _cfg.setdefault("island_code_description", ISLAND_CODE_DESC)


def _normalizar_codigo(texto: str) -> str:
    """Solo dígitos, para comparar códigos ignorando paréntesis/guiones."""
    return "".join(c for c in str(texto or "") if c.isdigit())


def get_game_by_island_code(island_code: str) -> tuple[str, dict] | None:
    """
    Devuelve (clave_interna, config) del juego cuyo código de isla
    coincide con el dado. La comparación es por dígitos (tolerante a
    paréntesis, guiones y espacios).
    """
    objetivo = _normalizar_codigo(island_code)
    if not objetivo:
        return None
    for key, cfg in GAMES.items():
        if _normalizar_codigo(cfg.get("island_code", "")) == objetivo:
            return key, cfg
    return None


def game_enabled(game_config: dict) -> bool:
    """
    True si el juego está activo. Un juego se desactiva poniendo
    'enabled': False en su config. Si el campo no existe, se considera
    activo (para no romper juegos que no lo declaren).
    """
    return game_config.get("enabled", True)
