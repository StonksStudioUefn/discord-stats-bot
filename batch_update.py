"""
batch_update.py
================
Bot por LOTES, multi-juego con UN único canal de envío.

Cada ejecución (manual desde GitHub Actions o por cron):

  1. Conecta a Discord y localiza los 3 canales (submit, leaderboards,
     summary). Aborta si falta alguno.
  2. Lee del canal de envío los mensajes nuevos desde el último puntero.
  3. Por cada captura nueva:
       - Pasa la imagen a Gemini (esquema universal).
       - Identifica el juego por el código de isla.
       - Si no coincide con ningún juego configurado o no se puede leer:
         rechaza con mensaje al jugador.
       - Si coincide: guarda en BD las stats del juego, responde al
         jugador con la confirmación.
  4. Refresca un EMBED por juego en el canal de leaderboards.
  5. Refresca un mensaje con .json adjunto por juego en el canal de
     resumen para moderadores.

Al terminar cierra la conexión.
"""

import asyncio
import os
from datetime import datetime

import discord

from config import DISCORD_TOKEN
from database import (
    guardar_stat,
    guardar_ultimo_mensaje_global,
    guardar_id_embed,
    obtener_id_embed,
    obtener_top,
    obtener_ultimo_mensaje_global,
    añadir_pendiente,
    listar_pendientes,
    quitar_pendiente,
)
from formatting import format_value, parse_value
from games import (
    GAMES,
    LEADERBOARD_CHANNEL,
    SUBMIT_CHANNEL,
    game_enabled,
    get_game_by_island_code,
    stat_field,
    stat_lower_is_better,
)
from gemini_service import GeminiTransientError, extract_stats_from_image
from widget_site import generar_widgets_json


# Ruta de la plantilla T3D del widget (la misma para todos los juegos;
# solo cambian título, color y los datos). Colócala en widget_templates/.
_DIR = os.path.dirname(os.path.abspath(__file__))
WIDGET_TEMPLATE_PATH = os.path.join(
    _DIR, "widget_templates", "leaderboard_widget.t3d"
)


def _cargar_plantilla_widget() -> str | None:
    """Lee la plantilla T3D del disco. Devuelve None si no existe."""
    try:
        with open(WIDGET_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(
            f"[WARN] No encontré la plantilla del widget en "
            f"{WIDGET_TEMPLATE_PATH}. No generaré los .txt del widget."
        )
        return None


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
    todos: list[discord.TextChannel], nombre: str
) -> tuple[discord.TextChannel | None, str | None]:
    """Localiza un canal por nombre. Detecta duplicados."""
    coincidencias = [ch for ch in todos if ch.name == nombre]
    if len(coincidencias) == 0:
        return None, None
    if len(coincidencias) > 1:
        ids = ", ".join(str(ch.id) for ch in coincidencias)
        return None, f"Hay {len(coincidencias)} canales llamados #{nombre} (IDs: {ids})."
    return coincidencias[0], None


# =====================================================================
#  PROCESADO DE UNA CAPTURA
# =====================================================================
async def _procesar_mensaje(message: discord.Message) -> str | None:
    """
    Procesa UN mensaje con imagen del canal de envío.
    Devuelve la clave del juego al que se asignó (para saber qué embeds
    refrescar al final), o None si se rechazó.
    """
    attachment = message.attachments[0]
    if not _es_imagen(attachment):
        return None

    # 1) Gemini lee la captura con el esquema universal.
    try:
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
        contenido, am = _build_rejection(message, "gemini_error")
        await message.reply(contenido, allowed_mentions=am)
        return None

    if not stats.get("stats_detected"):
        contenido, am = _build_rejection(message, "not_a_stats_card")
        await message.reply(contenido, allowed_mentions=am)
        return None

    # 2) Identificar el juego por el código de isla.
    codigo_leido = stats.get("island_code", "")
    if not _tiene_parentesis(codigo_leido):
        print(f"[INFO] msg {message.id}: código sin paréntesis ('{codigo_leido}'). Rechazada.")
        contenido, am = _build_rejection(message, "island_code_unreadable")
        await message.reply(contenido, allowed_mentions=am)
        return None

    juego = get_game_by_island_code(codigo_leido)
    if juego is None:
        print(f"[INFO] msg {message.id}: código '{codigo_leido}' no corresponde a ningún juego configurado.")
        contenido, am = _build_rejection(message, "island_code_unknown")
        await message.reply(contenido, allowed_mentions=am)
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
        contenido, am = _build_rejection(message, "name_unreadable")
        await message.reply(contenido, allowed_mentions=am)
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
        contenido, am = _build_rejection(message, "stats_unreadable")
        await message.reply(contenido, allowed_mentions=am)
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


# Nº máximo de pasadas (ejecuciones) que reintentamos una captura en cola
# antes de rendirnos y avisar al usuario.
MAX_PASADAS_PENDIENTE = 5


async def _procesar_cola_pendientes(
    c_submit: discord.TextChannel, juegos_tocados: set[str]
) -> None:
    """
    Reintenta las capturas que quedaron en cola por errores transitorios
    de Gemini en pasadas anteriores. Por cada una:
      - La recupera del canal por su ID.
      - Intenta procesarla de nuevo.
      - Si funciona: la quita de la cola y marca el juego para refrescar.
      - Si vuelve a fallar por Gemini: incrementa su contador; si llega a
        MAX_PASADAS_PENDIENTE, avisa al usuario y la quita de la cola.
      - Si el mensaje ya no existe (borrado): la quita de la cola.
    """
    pendientes = await listar_pendientes()
    if not pendientes:
        return

    print(f"[QUEUE] {len(pendientes)} captura(s) pendiente(s) por reintentar.")
    for message_id, intentos in pendientes:
        try:
            message = await c_submit.fetch_message(int(message_id))
        except discord.NotFound:
            print(f"[QUEUE] msg {message_id} ya no existe; lo saco de la cola.")
            await quitar_pendiente(message_id)
            continue
        except discord.HTTPException as e:
            print(f"[QUEUE] No pude recuperar msg {message_id}: {e}. Lo dejo en cola.")
            continue

        if not message.attachments:
            await quitar_pendiente(message_id)
            continue

        try:
            game_key = await _procesar_mensaje(message)
        except GeminiTransientError as e:
            nuevos_intentos = intentos + 1
            if nuevos_intentos >= MAX_PASADAS_PENDIENTE:
                # Nos rendimos: ahora sí avisamos al usuario.
                print(
                    f"[QUEUE] msg {message_id} agotó {MAX_PASADAS_PENDIENTE} "
                    f"pasadas; aviso al usuario y lo saco de la cola."
                )
                contenido, am = _build_rejection(message, "gemini_error")
                try:
                    await message.reply(contenido, allowed_mentions=am)
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
        canales_texto = [
            ch for ch in client.get_all_channels()
            if isinstance(ch, discord.TextChannel)
        ]

        # --- Resolver los 3 canales ---
        c_submit, err = _resolver_canal(canales_texto, SUBMIT_CHANNEL)
        if err or c_submit is None:
            print(f"[FATAL] Canal de envío #{SUBMIT_CHANNEL}: {err or 'no encontrado'}.")
            return

        c_leaderboard, err = _resolver_canal(canales_texto, LEADERBOARD_CHANNEL)
        if err or c_leaderboard is None:
            print(f"[FATAL] Canal de leaderboards #{LEADERBOARD_CHANNEL}: {err or 'no encontrado'}.")
            return

        # --- Avisos de permisos ---
        p_lb = c_leaderboard.permissions_for(c_leaderboard.guild.me)
        if not p_lb.send_messages:
            print(f"[WARN] Sin 'Send Messages' en #{LEADERBOARD_CHANNEL}.")

        # --- Leer mensajes nuevos del canal de envío ---
        ultimo_id = await obtener_ultimo_mensaje_global()
        if ultimo_id is None:
            print(f"[BATCH] Primera ejecución: últimos {BACKFILL_PRIMERA_VEZ} mensajes.")
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

        # --- Procesar la COLA de pendientes primero (capturas que
        #     fallaron por errores transitorios de Gemini en pasadas
        #     anteriores). Se reintentan hasta MAX_PASADAS_PENDIENTE veces.
        juegos_tocados: set[str] = set()
        await _procesar_cola_pendientes(c_submit, juegos_tocados)

        # --- Procesar cada captura NUEVA y trackear qué juegos refrescar ---
        if mensajes:
            for message in mensajes:
                if message.author == client.user:
                    continue
                if not message.attachments:
                    continue
                try:
                    game_key = await _procesar_mensaje(message)
                except GeminiTransientError as e:
                    # Gemini sobrecargado: encolar para la próxima pasada,
                    # sin avisar al usuario. El puntero igual avanza.
                    print(f"[QUEUE] msg {message.id} encolada (Gemini transitorio): {e}")
                    await añadir_pendiente(str(message.id), intentos=1)
                    continue
                if game_key:
                    juegos_tocados.add(game_key)

            id_mas_reciente = max(m.id for m in mensajes)
            await guardar_ultimo_mensaje_global(str(id_mas_reciente))
            print(f"[BATCH] {len(mensajes)} mensajes revisados. Puntero -> {id_mas_reciente}")
        else:
            print("[BATCH] No hay mensajes nuevos.")

        # --- Refrescar embeds y resúmenes ---
        # Política:
        #   - Ejecución MANUAL (workflow_dispatch): refresca TODOS los
        #     juegos desde la base de datos. Útil tras editar nombres a
        #     mano en Supabase, o si alguien borró un embed.
        #   - Ejecución por CRON (schedule): solo los juegos que han
        #     cambiado en esta tanda (ahorra trabajo y llamadas).
        es_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"

        if es_manual:
            a_refrescar = set(GAMES.keys())
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
                await _actualizar_embed(c_leaderboard, game_key, game_config)
            except Exception as e:
                print(f"[ERROR] Embed de '{game_key}': {e}")

        # --- Generar el JSON de widgets para la web ---
        # Se regenera siempre que haya habido algún refresco (manual o
        # con juegos cambiados), porque el JSON es global (todos los
        # juegos en un archivo). Si nada cambió, no hace falta tocarlo.
        if a_refrescar:
            try:
                plantilla = _cargar_plantilla_widget()
                escrito = await generar_widgets_json(plantilla, obtener_top)
                if not escrito:
                    print(
                        "[WEB] No se generó widgets.json (falta la "
                        "plantilla en widget_templates/)."
                    )
            except Exception as e:
                print(f"[ERROR] Generando widgets.json: {e}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(client.start(DISCORD_TOKEN))
