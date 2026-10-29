"""
batch_update.py
================
Bot por LOTES, multi-juego y multi-servidor: un canal de envío por
servidor de Discord (SERVIDORES en games.py).

Cada ejecución (manual desde GitHub Actions o por cron):

  1. Conecta a Discord y, en cada servidor dado de alta, localiza sus
     canales de envío y de leaderboards. Un servidor al que le falte
     alguno se salta; los demás siguen.
  2. Lee de cada canal de envío los mensajes nuevos desde su puntero.
  3. Por cada captura nueva:
       - Pasa la imagen a Gemini (esquema universal).
       - Identifica el juego por el código de isla.
       - Si no coincide con ningún juego configurado o no se puede leer:
         rechaza con mensaje al jugador.
       - Si coincide: guarda en BD las stats del juego, responde al
         jugador con la confirmación.
     Antes, si un moderador lo pide (input 'quitar'), saca de la
     leaderboard al autor de una captura falsa y lo bloquea.
  4. Refresca un EMBED por juego en el canal de leaderboards de su
     servidor.

Al terminar cierra la conexión.
"""

import asyncio
import os
from datetime import datetime

import discord

from config import DISCORD_TOKEN
from database import (
    bloquear_jugador,
    borrar_jugador,
    guardar_stat,
    guardar_ultimo_mensaje,
    guardar_id_embed,
    obtener_id_embed,
    obtener_top,
    obtener_ultimo_mensaje,
    añadir_pendiente,
    listar_bloqueados,
    listar_pendientes,
    quitar_pendiente,
)
from formatting import format_value, parse_value
from games import (
    GAMES,
    SERVIDORES,
    canal_envio,
    canal_leaderboards,
    game_enabled,
    get_game_by_island_code,
    stat_field,
    stat_lower_is_better,
)
from gemini_service import GeminiTransientError, extract_stats_from_image
from widget_site import generar_widgets_json


# Mensajes a mirar en la primera ejecución (cuando no hay puntero previo).
BACKFILL_PRIMERA_VEZ = 25
# Tope por ejecución, evita tandas inesperadas.
MAX_POR_EJECUCION = 200


# Motivos de rechazo. Cada uno explica al jugador EXACTAMENTE qué falló
# para que sepa qué arreglar antes de reenviar.
REJECT_REASONS = {
    "not_a_stats_card": (
        "The image doesn't look like a valid stats card. "
        "Make sure the screenshot clearly shows the **lifetime stats card** "
        "from the game."
    ),
    "island_code_unreadable": (
        "I couldn't read the **island code** at the bottom of the card. "
        "It must be visible, in parentheses, and not cut off "
        "(example: `(2943-6452-4033)`)."
    ),
    "island_code_unknown": (
        "The island code I read doesn't match any registered game. "
        "Either the screenshot is from another island or the code was "
        "misread — please resubmit a clear screenshot."
    ),
    "name_unreadable": (
        "I couldn't read your **player name** properly — the stats card "
        "appears to be cut off in the screenshot. Make sure the whole "
        "card is visible, including your name below the avatar."
    ),
    "stats_unreadable": (
        "I detected the card but couldn't read any of the statistics. "
        "Make sure the **stats** on the card are clearly visible "
        "and not blurry."
    ),
    "gemini_error": (
        "There was a temporary error analyzing the image. "
        "Please try uploading it again in a few seconds."
    ),
}


def _build_rejection(message: "discord.Message", reason_key: str) -> tuple[str, "discord.AllowedMentions"]:
    """
    Construye el texto del rechazo con mención (PING) al autor y el
    motivo concreto. Devuelve (contenido, allowed_mentions) para pasar
    a message.reply directamente.
    """
    motivo = REJECT_REASONS.get(reason_key, REJECT_REASONS["not_a_stats_card"])
    contenido = (
        f"{message.author.mention} ❌ **Image rejected — please resubmit.**\n"
        f"**Reason:** {motivo}"
    )
    # allowed_mentions explícito: garantizamos que SÍ se notifica al usuario.
    return contenido, discord.AllowedMentions(users=True, roles=False, everyone=False)


# Modo silencioso (input 'silencioso' del workflow -> SILENCIOSO=true):
# los rechazos/errores NO se publican en Discord, solo se ven en el log.
# Las confirmaciones de capturas procesadas bien sí se publican.
SILENCIOSO = os.environ.get("SILENCIOSO", "").strip().lower() in ("1", "true", "yes", "si", "sí")


async def _rechazar(message: "discord.Message", reason_key: str) -> None:
    """Responde al jugador con el motivo del rechazo (salvo en modo silencioso)."""
    if SILENCIOSO:
        print(f"[SILENCIO] msg {message.id}: rechazo '{reason_key}' no publicado.")
        return
    contenido, am = _build_rejection(message, reason_key)
    await message.reply(contenido, allowed_mentions=am)

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


# =====================================================================
#  UTILIDADES
# =====================================================================
def _es_imagen(att: discord.Attachment) -> bool:
    return (att.content_type or "").startswith("image/")


def _tiene_parentesis(texto: str) -> bool:
    """True si el texto contiene '(...)' con al menos un dígito dentro."""
    s = str(texto or "")
    a = s.find("(")
    c = s.find(")", a + 1)
    if a == -1 or c == -1:
        return False
    return any(ch.isdigit() for ch in s[a + 1 : c])


def _resolver_canal(
    guild: discord.Guild, nombre: str
) -> tuple[discord.TextChannel | None, str | None]:
    """Localiza un canal por nombre dentro de un servidor. Detecta duplicados."""
    coincidencias = [ch for ch in guild.text_channels if ch.name == nombre]
    if len(coincidencias) == 0:
        return None, None
    if len(coincidencias) > 1:
        ids = ", ".join(str(ch.id) for ch in coincidencias)
        return None, f"Hay {len(coincidencias)} canales llamados #{nombre} (IDs: {ids})."
    return coincidencias[0], None


# =====================================================================
#  PROCESADO DE UNA CAPTURA
# =====================================================================
async def _procesar_mensaje(message: discord.Message, servidor: str) -> str | None:
    """
    Procesa UN mensaje con imagen del canal de envío del servidor dado.
    Devuelve la clave del juego al que se asignó (para saber qué embeds
    refrescar al final), o None si se rechazó.
    """
    # Jugador bloqueado por captura falsa: se ignora en silencio.
    if str(message.author.id) in BLOQUEADOS:
        print(f"[INFO] msg {message.id}: autor {message.author.id} bloqueado; ignoro la captura.")
        return None

    # Datos puestos a mano (input 'manual'): no se lee la captura, así que
    # vale aunque la imagen esté tapada o Gemini la lea mal.
    manual = DATOS_MANUALES.get(str(message.id))
    if manual is not None:
        # Sin player=..., el nombre de Discord (el de la BD manda si ya existe).
        stats = {"player_name": message.author.display_name, **manual}
        print(f"[INFO] msg {message.id}: datos a mano, sin Gemini -> {stats}")
    else:
        attachment = message.attachments[0]
        if not _es_imagen(attachment):
            return None
        stats = None

    # 1) Gemini lee la captura con el esquema universal.
    try:
        if stats is None:
            image_bytes = await attachment.read()
            stats = await extract_stats_from_image(image_bytes, attachment.content_type)
            print(f"[DEBUG] msg {message.id}: {stats}")
    except GeminiTransientError:
        # Error transitorio (sobrecarga/timeout): NO avisamos al usuario.
        # Se propaga para que el orquestador lo encole y lo reintente en
        # la siguiente pasada.
        raise
    except Exception as error:
        print(f"[WARN] msg {message.id}: error definitivo en Gemini: {error}")
        await _rechazar(message, "gemini_error")
        return None

    # Juego forzado a mano (reprocesar 'ID=juego'): se salta la
    # comprobación de tarjeta/código de isla, pensada para capturas que
    # se enviaron sin el código visible.
    forzado = JUEGO_FORZADO.get(str(message.id))
    if forzado:
        if GAMES[forzado]["servidor"] != servidor:
            print(
                f"[WARN] msg {message.id}: el juego forzado '{forzado}' es del "
                f"servidor '{GAMES[forzado]['servidor']}' y la captura de "
                f"'{servidor}'. La ignoro."
            )
            return None
        print(f"[INFO] msg {message.id}: juego forzado a mano -> '{forzado}'.")
        juego = (forzado, GAMES[forzado])
    else:
        if not stats.get("stats_detected"):
            await _rechazar(message, "not_a_stats_card")
            return None

        # 2) Identificar el juego por el código de isla.
        codigo_leido = stats.get("island_code", "")
        if not _tiene_parentesis(codigo_leido):
            print(f"[INFO] msg {message.id}: código sin paréntesis ('{codigo_leido}'). Rechazada.")
            await _rechazar(message, "island_code_unreadable")
            return None

        juego = get_game_by_island_code(codigo_leido)
        if juego is None:
            print(f"[INFO] msg {message.id}: código '{codigo_leido}' no corresponde a ningún juego configurado.")
            await _rechazar(message, "island_code_unknown")
            return None
        if juego[1]["servidor"] != servidor:
            # Juego de otro servidor: aquí no tiene leaderboard.
            print(
                f"[INFO] msg {message.id}: código '{codigo_leido}' es de "
                f"'{juego[0]}', del servidor '{juego[1]['servidor']}', no de '{servidor}'."
            )
            await _rechazar(message, "island_code_unknown")
            return None

    game_key, game_config = juego

    # 2.4) Si el juego está DESACTIVADO (enabled: False en games.py),
    #       ignoramos la captura en silencio: ni se procesa, ni se guarda,
    #       ni se responde al usuario.
    if not game_enabled(game_config):
        print(
            f"[INFO] msg {message.id}: juego '{game_key}' desactivado; "
            f"ignoro la captura en silencio."
        )
        return None

    # 2.5) Verificar que el NOMBRE del jugador se ve completo en la
    #      captura. Sin esto, se nos colaría como username el que dice
    #      Discord (correcto), pero el record quedaría asociado a una
    #      lectura recortada en la imagen, lo cual confunde si el bot
    #      muestra player_name en otros sitios. Comprobamos:
    #        - el flag que pedimos a Gemini ('name_fully_visible')
    #        - señales obvias de truncado en el propio texto leído
    nombre_leido = (stats.get("player_name") or "").strip()
    nombre_truncado = nombre_leido.endswith(("...", "…")) or nombre_leido == ""
    nombre_visible = bool(stats.get("name_fully_visible", True))
    if nombre_truncado or not nombre_visible:
        print(
            f"[INFO] msg {message.id}: nombre no se ve completo "
            f"(leído '{nombre_leido}', "
            f"name_fully_visible={nombre_visible}). Rechazada."
        )
        await _rechazar(message, "name_unreadable")
        return None

    # 3) Guardar cada stat del juego que tenga valor leído.
    jugador = stats.get("player_name") or message.author.display_name
    es_vip = bool(stats.get("is_vip", False))
    lineas_resumen: list[str] = []

    for stat_key, stat_info in game_config["stats"].items():
        fmt = stat_info.get("format", "raw")
        valor_crudo = stats.get(stat_field(stat_key, stat_info), "")
        valor = parse_value(valor_crudo, fmt)
        if valor <= 0:
            continue

        try:
            resultado = await guardar_stat(
                game=game_key,
                discord_id=str(message.author.id),
                # Usamos el nombre que aparece en la CAPTURA (lo que el
                # jugador puso en el juego), no el nick de Discord.
                # 'jugador' ya viene saneado arriba: stats['player_name']
                # con fallback al display_name de Discord si vacío.
                username=jugador,
                stat=stat_key,
                value=valor,
                is_vip=es_vip,
                lower_is_better=stat_lower_is_better(stat_info),
            )
        except Exception as error:
            print(f"[ERROR] {game_key}/{stat_key}: fallo al guardar: {error}")
            continue

        emoji = stat_info.get("emoji", "📊")
        valor_fmt = format_value(valor, fmt)
        estado = resultado["estado"]

        if estado == "actualizado":
            previo_fmt = format_value(resultado["record_previo"], fmt)
            lineas_resumen.append(
                f"{emoji} **{stat_key}**: {valor_fmt} (previous {previo_fmt})"
            )
        elif estado == "creado":
            lineas_resumen.append(
                f"{emoji} **{stat_key}**: {valor_fmt} (first record)"
            )
        else:
            tu_record_fmt = format_value(resultado["valor"], fmt)
            lineas_resumen.append(
                f"{emoji} **{stat_key}**: {valor_fmt} "
                f"(your record stays at {tu_record_fmt})"
            )

    if not lineas_resumen:
        await _rechazar(message, "stats_unreadable")
        return None

    cabecera = (
        f"🎯 **{jugador}**'s screenshot processed "
        f"— **{game_config['display_name']}**"
    )
    await message.reply(
        cabecera + "\n" + "\n".join(lineas_resumen),
        mention_author=False,
    )
    return game_key


# {message_id: game_key} de las capturas reprocesadas con juego forzado.
JUEGO_FORZADO: dict[str, str] = {}

# {message_id: stats} de las capturas con los datos puestos a mano
# (input 'manual'): sustituyen a lo que leería Gemini.
DATOS_MANUALES: dict[str, dict] = {}

# IDs de Discord de los jugadores bloqueados (input 'quitar').
BLOQUEADOS: set[str] = set()

# Mensajes ya procesados por la cola en esta ejecución: la tanda de
# mensajes nuevos se los salta para no responder dos veces.
PROCESADOS_EN_COLA: set[str] = set()


def _datos_manuales() -> list[tuple[str, str, dict]]:
    """
    Capturas con los datos puestos a mano (input 'manual' del workflow ->
    variable MANUAL). Una por línea o separadas por ';':
        ID_o_enlace=clave_juego | player=Nombre | vip=1 | wins=97 | hay=840 K
    Las stats van con su clave de games.py y el mismo texto que leería
    Gemini ('840 K', '14:20'...); las que no se pongan no se tocan.
    player y vip son opcionales: sin player, el nombre de Discord; sin vip, no VIP.
    Devuelve [(message_id, game_key, stats), ...].
    """
    crudo = os.environ.get("MANUAL", "")
    salida = []
    for linea in crudo.replace(";", "\n").splitlines():
        if not linea.strip():
            continue
        partes = [p.strip() for p in linea.split("|")]
        ref, _, juego = partes[0].partition("=")
        mid = ref.strip().rstrip("/").split("/")[-1]
        juego = juego.strip()
        if not mid.isdigit() or juego not in GAMES:
            print(
                f"[WARN] manual: no entiendo '{partes[0]}' (hace falta "
                f"ID=juego). Juegos: {sorted(GAMES)}. Lo ignoro."
            )
            continue
        stats: dict = {"stats_detected": True, "name_fully_visible": True}
        # Se acepta la clave de la stat ('wins') o su campo de Gemini ('card_wins').
        campos_validos = {}
        for k, info in GAMES[juego]["stats"].items():
            campos_validos[k] = campos_validos[stat_field(k, info)] = stat_field(k, info)
        for parte in partes[1:]:
            clave, _, valor = parte.partition("=")
            clave, valor = clave.strip().lower(), valor.strip()
            if clave == "player":
                stats["player_name"] = valor
            elif clave == "vip":
                stats["is_vip"] = valor.lower() in ("1", "true", "yes", "si", "sí")
            elif clave in campos_validos:
                stats[campos_validos[clave]] = valor
            else:
                print(
                    f"[WARN] manual {mid}: campo '{clave}' desconocido para "
                    f"'{juego}' (válidos: player, vip, {sorted(campos_validos)})."
                )
        salida.append((mid, juego, stats))
    return salida


def _ids_a_reprocesar() -> list[tuple[str, str | None]]:
    """
    Mensajes que un moderador pide reprocesar a mano (input
    'reprocesar' del workflow -> variable REPROCESAR). Acepta IDs o
    enlaces de Discord separados por comas, espacios o saltos de línea;
    de cada enlace se queda con el último número (el ID del mensaje).

    Opcionalmente se puede forzar el juego con 'ID=clave_juego' (p. ej.
    '1552744445101871205=color_the_meme') para capturas sin código de
    isla. Devuelve [(message_id, game_key o None), ...].
    """
    crudo = os.environ.get("REPROCESAR", "")
    salida = []
    for trozo in crudo.replace(",", " ").split():
        ref, _, juego = trozo.partition("=")
        ultimo = ref.rstrip("/").split("/")[-1]
        if not ultimo.isdigit():
            print(f"[WARN] reprocesar: no entiendo '{trozo}'; lo ignoro.")
            continue
        juego = juego.strip() or None
        if juego is not None and juego not in GAMES:
            print(
                f"[WARN] reprocesar: juego '{juego}' desconocido para "
                f"{ultimo}; lo ignoro. Juegos: {sorted(GAMES)}"
            )
            continue
        salida.append((ultimo, juego))
    return salida


def _ids_a_quitar() -> list[str]:
    """
    Capturas falsas (input 'quitar' del workflow -> variable QUITAR).
    Mismo formato que 'reprocesar': IDs o enlaces de Discord separados
    por comas, espacios o saltos de línea. También vale el ID de
    Discord del jugador, por si el mensaje ya se borró al banearlo.
    """
    crudo = os.environ.get("QUITAR", "")
    salida = []
    for trozo in crudo.replace(",", " ").split():
        ultimo = trozo.rstrip("/").split("/")[-1]
        if not ultimo.isdigit():
            print(f"[WARN] quitar: no entiendo '{trozo}'; lo ignoro.")
            continue
        salida.append(ultimo)
    return salida


async def _buscar_mensaje(
    envios: dict[str, discord.TextChannel], message_id: str
) -> tuple[str, discord.Message] | None:
    """
    Busca un mensaje en los canales de envío de todos los servidores.
    Devuelve (servidor, mensaje), o None si no está en ninguno. Un error
    que no sea "no existe" se propaga para no darlo por borrado.
    """
    error = None
    for servidor, canal in envios.items():
        try:
            return servidor, await canal.fetch_message(int(message_id))
        except discord.NotFound:
            continue
        except discord.HTTPException as e:
            error = e
    if error is not None:
        raise error
    return None


async def _quitar_jugadores(envios: dict[str, discord.TextChannel]) -> None:
    """
    Por cada captura falsa pedida: saca a su autor de la leaderboard
    (todos los juegos y stats, de todos los servidores) y lo bloquea
    para que sus capturas se ignoren siempre. No responde nada en Discord.
    """
    for ref in _ids_a_quitar():
        try:
            encontrado = await _buscar_mensaje(envios, ref)
            if encontrado is None:
                # El mensaje no está (borrado al banear) o es un ID de usuario.
                discord_id = ref
                print(f"[QUITAR] {ref} no es un mensaje de ningún canal de envío; lo trato como ID de jugador.")
            else:
                servidor, message = encontrado
                # Enlace a la respuesta del bot en vez de a la captura: vamos
                # al mensaje original al que respondió.
                if message.author == client.user and message.reference:
                    message = await envios[servidor].fetch_message(message.reference.message_id)
                discord_id = str(message.author.id)
                print(f"[QUITAR] msg {ref} ({servidor}): autor {message.author} ({discord_id}).")
        except discord.HTTPException as e:
            print(f"[WARN] quitar: no pude recuperar {ref}: {e}. Lo salto.")
            continue

        borradas = await borrar_jugador(discord_id)
        for fila in borradas:
            print(
                f"[QUITAR]   borrado {fila['game']}/{fila['stat']} = "
                f"{fila['best_value']} ({fila['username']})"
            )
        if not borradas:
            print(f"[QUITAR]   {discord_id} no tenía nada en la leaderboard.")

        await bloquear_jugador(discord_id, f"captura falsa: {ref}")
        BLOQUEADOS.add(discord_id)
        print(f"[QUITAR]   {discord_id} bloqueado: sus capturas se ignorarán.")


# Nº máximo de pasadas (ejecuciones) que reintentamos una captura en cola
# antes de rendirnos y avisar al usuario.
MAX_PASADAS_PENDIENTE = 5


async def _procesar_cola_pendientes(
    envios: dict[str, discord.TextChannel], juegos_tocados: set[str]
) -> None:
    """
    Reintenta las capturas que quedaron en cola por errores transitorios
    de Gemini en pasadas anteriores. Por cada una:
      - La busca por su ID en los canales de envío de los servidores.
      - Intenta procesarla de nuevo.
      - Si funciona: la quita de la cola y marca el juego para refrescar.
      - Si vuelve a fallar por Gemini: incrementa su contador; si llega a
        MAX_PASADAS_PENDIENTE, avisa al usuario y la quita de la cola.
      - Si el mensaje ya no existe (borrado): la quita de la cola.
    """
    pendientes = await listar_pendientes()
    if not pendientes:
        return

    # Si algún servidor no está disponible en esta pasada, un mensaje que
    # no aparezca puede ser suyo: no se da por borrado.
    todos_los_servidores = len(envios) == len(SERVIDORES)

    print(f"[QUEUE] {len(pendientes)} captura(s) pendiente(s) por reintentar.")
    for message_id, intentos in pendientes:
        try:
            encontrado = await _buscar_mensaje(envios, message_id)
        except discord.HTTPException as e:
            print(f"[QUEUE] No pude recuperar msg {message_id}: {e}. Lo dejo en cola.")
            continue
        if encontrado is None:
            if todos_los_servidores:
                print(f"[QUEUE] msg {message_id} ya no existe; lo saco de la cola.")
                await quitar_pendiente(message_id)
            else:
                print(f"[QUEUE] msg {message_id} no aparece y falta algún servidor; lo dejo en cola.")
            continue
        servidor, message = encontrado

        if not message.attachments:
            await quitar_pendiente(message_id)
            continue

        try:
            game_key = await _procesar_mensaje(message, servidor)
        except GeminiTransientError as e:
            nuevos_intentos = intentos + 1
            if nuevos_intentos >= MAX_PASADAS_PENDIENTE:
                # Nos rendimos: ahora sí avisamos al usuario.
                print(
                    f"[QUEUE] msg {message_id} agotó {MAX_PASADAS_PENDIENTE} "
                    f"pasadas; aviso al usuario y lo saco de la cola."
                )
                try:
                    await _rechazar(message, "gemini_error")
                except discord.HTTPException:
                    pass
                await quitar_pendiente(message_id)
            else:
                print(
                    f"[QUEUE] msg {message_id} sigue fallando "
                    f"({nuevos_intentos}/{MAX_PASADAS_PENDIENTE}); lo dejo en cola."
                )
                await añadir_pendiente(message_id, intentos=nuevos_intentos)
            continue

        # Se procesó (bien o rechazada por otro motivo): sale de la cola.
        await quitar_pendiente(message_id)
        PROCESADOS_EN_COLA.add(str(message_id))
        if game_key:
            juegos_tocados.add(game_key)
            print(f"[QUEUE] msg {message_id} procesada con éxito en reintento.")


# =====================================================================
#  EMBED DEL CANAL DE LEADERBOARDS (1 por juego)
# =====================================================================
async def _construir_embed(game_key: str, game_config: dict) -> discord.Embed:
    """
    Embed con TODAS las stats del juego como campos.
    VIPs marcados con 👑 y nombre en negrita más fuerte.
    """
    emoji_juego = game_config.get("emoji", "🎮")
    embed = discord.Embed(
        title=f"{emoji_juego} {game_config['display_name']} {emoji_juego}",
        color=game_config.get("color", 0x808080),
    )

    medallas = ["🥇", "🥈", "🥉"] + ["🏅"] * 7

    for stat_key, stat_info in game_config["stats"].items():
        fmt = stat_info.get("format", "raw")
        emoji = stat_info.get("emoji", "📊")
        titulo = stat_info.get("title", stat_key.upper())

        top = await obtener_top(
            game_key, stat_key, limit=game_config["top_size"],
            ascending=stat_lower_is_better(stat_info),
        )
        if not top:
            cuerpo = "_No records yet._"
        else:
            lineas = []
            for i, fila in enumerate(top):
                medalla = medallas[i] if i < len(medallas) else "▫️"
                valor = format_value(int(fila["best_value"]), fmt)
                nombre = fila["username"]
                if bool(fila.get("is_vip", False)):
                    # VIP: corona + nombre en negrita (markdown estándar
                    # de Discord, compatible con todos los clientes).
                    nombre_render = f"👑 **{nombre}**"
                else:
                    nombre_render = nombre
                lineas.append(f"{medalla} {nombre_render} — {valor}")
            cuerpo = "\n".join(lineas)

        embed.add_field(
            name=f"{emoji} {titulo} {emoji}",
            value=cuerpo,
            inline=False,
        )

    embed.set_footer(
        text=f"Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )
    return embed


async def _actualizar_embed(
    canal: discord.TextChannel, game_key: str, game_config: dict
) -> None:
    """Crea o edita el embed del juego en el canal de leaderboards."""
    embed = await _construir_embed(game_key, game_config)
    msg_id = await obtener_id_embed(game_key)

    if msg_id is not None:
        try:
            mensaje = await canal.fetch_message(int(msg_id))
            await mensaje.edit(embed=embed)
            return
        except discord.NotFound:
            print(f"[INFO] Embed de {game_key} no existe. Lo recreo.")
        except discord.HTTPException as e:
            print(f"[WARN] Error editando embed de {game_key}: {e}")
            return

    try:
        nuevo = await canal.send(embed=embed)
        await guardar_id_embed(game_key, str(nuevo.id))
    except discord.HTTPException as e:
        print(f"[ERROR] No pude crear el embed de {game_key}: {e}")


# =====================================================================
# =====================================================================
#  ORQUESTADOR
# =====================================================================
@client.event
async def on_ready():
    print(f"[BATCH] Conectado como {client.user}")
    try:
        # --- Resolver los canales de cada servidor ---
        # envios / leaderboards: {servidor: canal} de los que están bien.
        envios: dict[str, discord.TextChannel] = {}
        leaderboards: dict[str, discord.TextChannel] = {}
        dados_de_alta = {cfg["guild_id"] for cfg in SERVIDORES.values()}
        for guild in client.guilds:
            if guild.id not in dados_de_alta:
                print(
                    f"[INFO] Servidor sin dar de alta: '{guild.name}' (ID {guild.id}). "
                    f"Lo ignoro; para usarlo, añádelo a SERVIDORES en games.py."
                )
        for servidor, cfg in SERVIDORES.items():
            guild = client.get_guild(cfg["guild_id"])
            if guild is None:
                print(f"[ERROR] {servidor}: el bot no está en el servidor {cfg['guild_id']}. Lo salto.")
                continue
            c_submit, err = _resolver_canal(guild, canal_envio(servidor))
            if err or c_submit is None:
                print(f"[ERROR] {servidor}: canal de envío #{canal_envio(servidor)}: {err or 'no encontrado'}. Lo salto.")
                continue
            c_leaderboard, err = _resolver_canal(guild, canal_leaderboards(servidor))
            if err or c_leaderboard is None:
                print(f"[ERROR] {servidor}: canal de leaderboards #{canal_leaderboards(servidor)}: {err or 'no encontrado'}. Lo salto.")
                continue
            if not c_leaderboard.permissions_for(guild.me).send_messages:
                print(f"[WARN] {servidor}: sin 'Send Messages' en #{c_leaderboard.name}.")
            envios[servidor] = c_submit
            leaderboards[servidor] = c_leaderboard
            print(f"[BATCH] {servidor}: '{guild.name}' listo.")

        if not envios:
            print("[FATAL] Ningún servidor tiene sus canales; no hago nada.")
            return

        # --- Capturas falsas: sacar y bloquear a sus autores ANTES de
        #     procesar nada, para que no se cuele ninguna otra suya.
        BLOQUEADOS.update(await listar_bloqueados())
        await _quitar_jugadores(envios)

        # --- Procesar la COLA de pendientes primero (capturas que
        #     fallaron por errores transitorios de Gemini en pasadas
        #     anteriores). Se reintentan hasta MAX_PASADAS_PENDIENTE veces.
        juegos_tocados: set[str] = set()
        # Capturas pedidas a mano (p. ej. rechazadas antes de configurar
        # su juego): se meten en la cola para procesarlas ahora mismo.
        for mid, juego in _ids_a_reprocesar():
            if juego:
                JUEGO_FORZADO[mid] = juego
            print(
                f"[QUEUE] msg {mid} añadida a mano para reprocesar"
                + (f" (juego forzado: {juego})." if juego else ".")
            )
            await añadir_pendiente(mid, intentos=1)
        for mid, juego, stats in _datos_manuales():
            JUEGO_FORZADO[mid] = juego
            DATOS_MANUALES[mid] = stats
            print(f"[QUEUE] msg {mid} añadida a mano con sus datos (juego: {juego}).")
            await añadir_pendiente(mid, intentos=1)
        await _procesar_cola_pendientes(envios, juegos_tocados)

        # --- Procesar cada captura NUEVA de cada servidor ---
        for servidor, c_submit in envios.items():
            ultimo_id = await obtener_ultimo_mensaje(servidor)
            if ultimo_id is None:
                print(f"[BATCH] {servidor}: primera ejecución, últimos {BACKFILL_PRIMERA_VEZ} mensajes.")
                recientes = [
                    m async for m in c_submit.history(
                        limit=BACKFILL_PRIMERA_VEZ, oldest_first=False
                    )
                ]
                mensajes = list(reversed(recientes))
            else:
                despues_de = discord.Object(id=int(ultimo_id))
                mensajes = [
                    m async for m in c_submit.history(
                        limit=MAX_POR_EJECUCION, after=despues_de, oldest_first=True
                    )
                ]

            if not mensajes:
                print(f"[BATCH] {servidor}: no hay mensajes nuevos.")
                continue

            for message in mensajes:
                if message.author == client.user:
                    continue
                if not message.attachments:
                    continue
                if str(message.id) in PROCESADOS_EN_COLA:
                    continue
                try:
                    game_key = await _procesar_mensaje(message, servidor)
                except GeminiTransientError as e:
                    # Gemini sobrecargado: encolar para la próxima pasada,
                    # sin avisar al usuario. El puntero igual avanza.
                    print(f"[QUEUE] msg {message.id} encolada (Gemini transitorio): {e}")
                    await añadir_pendiente(str(message.id), intentos=1)
                    continue
                if game_key:
                    juegos_tocados.add(game_key)

            id_mas_reciente = max(m.id for m in mensajes)
            await guardar_ultimo_mensaje(servidor, str(id_mas_reciente))
            print(f"[BATCH] {servidor}: {len(mensajes)} mensajes revisados. Puntero -> {id_mas_reciente}")

        # --- Refrescar embeds y resúmenes ---
        # Política:
        #   - Ejecución MANUAL (workflow_dispatch): refresca TODOS los
        #     juegos desde la base de datos. Útil tras editar nombres a
        #     mano en Supabase, o si alguien borró un embed.
        #   - Ejecución por CRON (schedule): solo los juegos que han
        #     cambiado en esta tanda (ahorra trabajo y llamadas).
        es_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

        if es_manual:
            a_refrescar = {k for k, cfg in GAMES.items() if cfg["servidor"] in leaderboards}
            print(
                "[BATCH] Ejecución MANUAL: refresco TODOS los embeds "
                f"desde la base de datos ({sorted(a_refrescar)})."
            )
        elif juegos_tocados:
            a_refrescar = juegos_tocados
            print(f"[BATCH] Refrescando embeds de: {sorted(juegos_tocados)}")
        else:
            a_refrescar = set()
            print("[BATCH] Ningún juego cambió. No se refrescan embeds.")

        # Excluir juegos desactivados (enabled: False): no se refrescan
        # sus embeds.
        desactivados = {
            k for k in a_refrescar if not game_enabled(GAMES[k])
        }
        if desactivados:
            print(f"[BATCH] Juegos desactivados (omitidos): {sorted(desactivados)}")
        a_refrescar = a_refrescar - desactivados

        for game_key in a_refrescar:
            game_config = GAMES[game_key]
            try:
                await _actualizar_embed(leaderboards[game_config["servidor"]], game_key, game_config)
            except Exception as e:
                print(f"[ERROR] Embed de '{game_key}': {e}")

        # --- Generar el JSON de widgets para la web ---
        # Se regenera siempre que haya habido algún refresco (manual o
        # con juegos cambiados), porque el JSON es global (todos los
        # juegos en un archivo). Si nada cambió, no hace falta tocarlo.
        if a_refrescar:
            try:
                await generar_widgets_json(obtener_top)
            except Exception as e:
                print(f"[ERROR] Generando widgets.json: {e}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(client.start(DISCORD_TOKEN))
