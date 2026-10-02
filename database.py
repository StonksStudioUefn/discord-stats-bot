"""
database.py
===========
Acceso a Supabase.

Tablas:
  leaderboard(game, discord_id, stat, best_value, username, updated_at)
    PK: (game, discord_id, stat)
    -> Una fila por (juego, jugador, estadística). Permite que cada stat
       tenga su récord independiente.

  bot_state(key, value)
    -> Almacén clave/valor para datos sueltos. Lo usamos para:
         last_message:<game>   -> ID del último mensaje procesado en ese canal
         pinned:<game>:<stat>  -> ID del mensaje fijado del Top 10 de esa stat
"""

import asyncio
from datetime import datetime, timezone

from supabase import Client, create_client

from config import SUPABASE_KEY, SUPABASE_URL

LEADERBOARD = "leaderboard"
STATE = "bot_state"

_supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# =====================================================================
#  PUNTUACIONES
# =====================================================================
def _guardar_stat_sync(
    game: str, discord_id: str, username: str, stat: str, value: int,
    is_vip: bool = False, lower_is_better: bool = False,
) -> dict:
    """
    Guarda la mejor marca del jugador en UNA stat de UN juego.

    Regla del nombre: el username se CONGELA al primero registrado
    para este discord_id (en cualquier juego, en cualquier stat). Si
    el jugador ya existe en la BD, ignoramos el username que venga
    y reutilizamos el que ya tenía guardado. Solo se respeta el
    'username' parámetro cuando es la PRIMERA vez que vemos ese
    discord_id. Para cambiar el nombre, edita la BD a mano.

    Si lower_is_better=True (p. ej. tiempos), el récord es el valor
    MÁS BAJO en vez del más alto.

    Nota técnica: el valor se envía como STRING para que NUMERIC en
    Postgres lo reciba con precisión arbitraria.
    """
    # ¿Conocemos ya a este jugador? Buscamos cualquier fila suya, en
    # cualquier juego/stat, para reutilizar su nombre congelado.
    existente = (
        _supabase.table(LEADERBOARD)
        .select("username")
        .eq("discord_id", discord_id)
        .limit(1)
        .execute()
    )
    if existente.data:
        username = existente.data[0]["username"]  # nombre congelado

    # Buscamos la fila exacta (juego, jugador, stat).
    consulta = (
        _supabase.table(LEADERBOARD)
        .select("*")
        .eq("game", game)
        .eq("discord_id", discord_id)
        .eq("stat", stat)
        .execute()
    )
    actual = consulta.data[0] if consulta.data else None

    ahora = datetime.now(timezone.utc).isoformat()
    fila = {
        "game": game,
        "discord_id": discord_id,
        "stat": stat,
        "best_value": str(value),  # NUMERIC acepta string directo
        "username": username,
        "is_vip": is_vip,
        "updated_at": ahora,
    }

    if actual is None:
        _supabase.table(LEADERBOARD).insert(fila).execute()
        return {"estado": "creado", "valor": value}

    # Convertimos lo que devuelve Supabase a int de Python (precisión arbitraria).
    record_previo = int(str(actual.get("best_value", 0)).split(".")[0])
    mejora = value < record_previo if lower_is_better else value > record_previo
    if mejora:
        # Importante: NO incluimos 'username' en este update aunque esté
        # en 'fila', porque la fila trae el nombre congelado y queremos
        # que se respete el que está en la BD si tú lo editaste a mano.
        update_fila = {k: v for k, v in fila.items() if k != "username"}
        (
            _supabase.table(LEADERBOARD)
            .update(update_fila)
            .eq("game", game)
            .eq("discord_id", discord_id)
            .eq("stat", stat)
            .execute()
        )
        return {"estado": "actualizado", "valor": value, "record_previo": record_previo}

    # Aunque no supere el récord, refrescamos is_vip por si cambió.
    # El username NO se toca: respeta lo que haya en la BD.
    (
        _supabase.table(LEADERBOARD)
        .update({"is_vip": is_vip})
        .eq("game", game)
        .eq("discord_id", discord_id)
        .eq("stat", stat)
        .execute()
    )
    return {"estado": "sin_cambios", "valor": record_previo}


async def guardar_stat(
    game: str, discord_id: str, username: str, stat: str, value: int,
    is_vip: bool = False, lower_is_better: bool = False,
) -> dict:
    return await asyncio.to_thread(
        _guardar_stat_sync, game, discord_id, username, stat, value, is_vip,
        lower_is_better,
    )


def _obtener_record_previo_sync(
    game: str, discord_id: str, stat: str
) -> int | None:
    """Consulta el récord actual del jugador en una stat (sin modificar nada)."""
    consulta = (
        _supabase.table(LEADERBOARD)
        .select("best_value")
        .eq("game", game)
        .eq("discord_id", discord_id)
        .eq("stat", stat)
        .execute()
    )
    if not consulta.data:
        return None
    return int(str(consulta.data[0]["best_value"]).split(".")[0])


async def obtener_record_previo(
    game: str, discord_id: str, stat: str
) -> int | None:
    return await asyncio.to_thread(
        _obtener_record_previo_sync, game, discord_id, stat
    )


def _top_sync(
    game: str, stat: str, limit: int, ascending: bool = False
) -> list[dict]:
    """
    Top N de una stat concreta de un juego. Por defecto de mayor a
    menor; con ascending=True de menor a mayor (p. ej. tiempos).
    """
    consulta = (
        _supabase.table(LEADERBOARD)
        .select("username,best_value,is_vip,updated_at")
        .eq("game", game)
        .eq("stat", stat)
        .order("best_value", desc=not ascending)
        .limit(limit)
        .execute()
    )
    filas = consulta.data or []
    # Normalizamos best_value a int de Python (precisión arbitraria),
    # porque Supabase devuelve NUMERIC como string o float.
    for fila in filas:
        fila["best_value"] = int(str(fila.get("best_value", 0)).split(".")[0])
    return filas


async def obtener_top(
    game: str, stat: str, limit: int = 10, ascending: bool = False
) -> list[dict]:
    return await asyncio.to_thread(_top_sync, game, stat, limit, ascending)


# =====================================================================
#  ESTADO (almacén clave/valor)
# =====================================================================
def _state_get_sync(key: str) -> str | None:
    consulta = (
        _supabase.table(STATE).select("value").eq("key", key).execute()
    )
    return consulta.data[0]["value"] if consulta.data else None


def _state_set_sync(key: str, value: str) -> None:
    _supabase.table(STATE).upsert({"key": key, "value": str(value)}).execute()


async def state_get(key: str) -> str | None:
    return await asyncio.to_thread(_state_get_sync, key)


async def state_set(key: str, value: str) -> None:
    return await asyncio.to_thread(_state_set_sync, key, value)


def _state_list_sync(prefix: str) -> list[dict]:
    """Devuelve [{key, value}, ...] de todas las filas cuya key empieza por prefix."""
    consulta = (
        _supabase.table(STATE)
        .select("key, value")
        .like("key", f"{prefix}%")
        .execute()
    )
    return consulta.data or []


def _state_delete_sync(key: str) -> None:
    _supabase.table(STATE).delete().eq("key", key).execute()


async def state_list(prefix: str) -> list[dict]:
    return await asyncio.to_thread(_state_list_sync, prefix)


async def state_delete(key: str) -> None:
    return await asyncio.to_thread(_state_delete_sync, key)


# ---------------------------------------------------------------------
# Cola de capturas PENDIENTES por reintentar.
# Cuando Gemini falla con un error transitorio (sobrecarga, timeout), en
# vez de avisar al usuario, guardamos la captura aquí y la reintentamos
# en la siguiente ejecución del bot. Clave: pending:<message_id>.
# El valor es el número de intentos ya realizados (como string).
# ---------------------------------------------------------------------
_PENDING_PREFIX = "pending:"


async def añadir_pendiente(message_id: str, intentos: int = 1) -> None:
    """Guarda/actualiza una captura pendiente con su contador de intentos."""
    await state_set(f"{_PENDING_PREFIX}{message_id}", str(intentos))


async def listar_pendientes() -> list[tuple[str, int]]:
    """
    Devuelve [(message_id, intentos), ...] de todas las capturas en cola.
    """
    filas = await state_list(_PENDING_PREFIX)
    salida = []
    for fila in filas:
        mid = fila["key"][len(_PENDING_PREFIX):]
        try:
            intentos = int(fila["value"])
        except (ValueError, TypeError):
            intentos = 1
        salida.append((mid, intentos))
    return salida


async def quitar_pendiente(message_id: str) -> None:
    """Saca una captura de la cola (se procesó bien o se agotó)."""
    await state_delete(f"{_PENDING_PREFIX}{message_id}")


# Helpers semánticos para que batch_update.py se lea mejor.
# Ahora SOLO hay un canal de envío, así que el "último mensaje
# procesado" es un único valor global (no por juego).
async def obtener_ultimo_mensaje_global() -> str | None:
    return await state_get("last_message:submit")


async def guardar_ultimo_mensaje_global(message_id: str) -> None:
    return await state_set("last_message:submit", message_id)


# Mensaje (embed) del juego en el canal de leaderboards. No está fijado,
# simplemente se edita. Hay UNO por juego.
async def obtener_id_embed(game: str) -> str | None:
    return await state_get(f"embed:{game}")


async def guardar_id_embed(game: str, message_id: str) -> None:
    return await state_set(f"embed:{game}", message_id)


async def obtener_id_resumen(game: str) -> str | None:
    """ID del mensaje (con .json adjunto) en el canal de moderadores."""
    return await state_get(f"summary:{game}")


async def guardar_id_resumen(game: str, message_id: str) -> None:
    return await state_set(f"summary:{game}", message_id)
