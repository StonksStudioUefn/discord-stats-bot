"""
formatting.py
=============
Conversión entre la notación abreviada del juego (K, M, B, T, Qa, Qi, ...)
y enteros normales, y al revés.

Las abreviaciones vienen del propio juego:
    STRING_Abbrev : []string = array{
        "", "K", "M", "B", "T",
        "Qa", "Qi", "Sx", "Sp", "Oc",
        "No", "Dc", "Un", "Du", "Tr",
        "Qt", "Qn", "Se", "St", "Og",
        "Nn", "Vg", "UVg"
    }

Cada sufijo representa una potencia de 1000:
    ""=10^0, "K"=10^3, "M"=10^6, ..., "UVg"=10^66

Como algunos valores exceden BIGINT (10^18), trabajamos con `int` de
Python (precisión arbitraria) y los guardamos en Supabase como NUMERIC.
"""

from decimal import Decimal, InvalidOperation

# Orden EXACTO del juego. NO reordenar: la posición es la magnitud.
ABBREV: list[str] = [
    "", "K", "M", "B", "T",
    "Qa", "Qt", "Sx", "Sp", "Oc",
    "No", "Dc", "UDc", "DDc", "TDc",
    "QaDc", "QtDc", "SxDc", "SpDc", "ODc",
    "NDc", "Vg", "UVg", "DVg", "TVg",
    "QaVg", "QtVg", "SxVg", "SpVg", "OVg",
    "NVg", "Tg", "UTg", "DTg", "TTg",
    "QaTg", "QtTg", "SxTg", "SpTg", "OTg",
    "NTg", "Qd", "UQd", "DQd", "TQd",
    "QaQd", "QtQd", "SxQd", "SpQd", "OQd",
    "NQd", "Qi", "UQi", "DQi", "TQi",
    "QaQi", "QtQi", "SxQi", "SpQi", "OQi",
    "NQi", "Se", "USe", "DSe", "TSe",
    "QaSe", "QtSe", "SxSe", "SpSe", "OSe",
    "NSe", "St", "USt", "DSt", "TSt",
    "QaSt", "QtSt", "SxSt", "SpSt", "OSt",
    "NSt", "Og", "UOg", "DOg", "TOg",
    "QaOg", "QtOg", "SxOg", "SpOg", "OOg",
    "NOg", "Nn", "UNn", "DNn", "TNn",
    "QaNn", "QtNn", "SxNn", "SpNn", "ONn",
    "NNn", "Dd", "DDd",
]

# Diccionario sufijo -> exponente (mil^i = 10^(3*i)).
# Las claves se normalizan a minúsculas para ser tolerantes.
_SUFIJO_A_EXP: dict[str, int] = {
    abbr.lower(): 3 * i for i, abbr in enumerate(ABBREV)
}


def parse_abbrev(texto: str) -> int:
    """
    Convierte '$1.2Qa/s' o '45.7M' o '1,234' en un entero exacto.

    Es TOLERANTE a propósito:
      - Quita '$' y '/s' y espacios.
      - Acepta coma o punto como separador decimal.
      - Si no hay sufijo conocido, asume número plano.
      - Si no puede interpretarlo, devuelve 0 (mejor 0 que reventar).
    """
    if texto is None:
        return 0

    s = str(texto).strip()
    if not s:
        return 0

    # Limpiar símbolos típicos.
    s = s.replace("$", "").replace("/s", "").replace(" ", "")

    # Separar parte numérica de sufijo alfabético.
    i = 0
    while i < len(s) and (s[i].isdigit() or s[i] in ".,"):
        i += 1
    parte_num = s[:i]
    sufijo = s[i:].lower()

    if not parte_num:
        return 0

    # En el juego la coma es separador de MILES, no decimal ('1,234' = 1234).
    # El punto SÍ es decimal ('1.2K').
    parte_num = parte_num.replace(",", "")

    try:
        # Decimal -> precisión arbitraria. Float fallaría con UVg (10^66).
        valor = Decimal(parte_num)
    except InvalidOperation:
        return 0

    exp = _SUFIJO_A_EXP.get(sufijo)
    if exp is None:
        # Sufijo desconocido -> tratamos como número plano.
        exp = 0

    # Multiplicación exacta sin pérdida de precisión.
    return int(valor * (Decimal(10) ** exp))


def format_abbrev(valor: int, decimales: int = 2) -> str:
    """
    Convierte 1200000000000000 en '1.2Qa'.

    - Elige el sufijo más alto que no haga que la cifra baje de 1.
    - Quita ceros decimales sobrantes ('1.00K' -> '1K', '1.20K' -> '1.2K').
    - Si el número es astronómicamente mayor que UVg, usa UVg como tope.
    """
    if valor is None:
        return "0"

    n = int(valor)
    if n < 0:
        return "-" + format_abbrev(-n, decimales)
    if n == 0:
        return "0"

    # Elegir el sufijo apropiado.
    idx = 0
    while idx + 1 < len(ABBREV) and n >= 1000 ** (idx + 1):
        idx += 1

    base = n / (1000 ** idx)
    texto = f"{base:.{decimales}f}".rstrip("0").rstrip(".")
    return f"{texto}{ABBREV[idx]}"


def format_money(valor: int) -> str:
    """'$1.2Qa' — para stats de tipo dinero acumulado (cash)."""
    return f"${format_abbrev(valor)}"


def format_income(valor: int) -> str:
    """'$1.2Qa/s' — para stats de tipo dinero por segundo (income)."""
    return f"${format_abbrev(valor)}/s"


def parse_time(texto: str) -> int:
    """
    Convierte un tiempo del juego en SEGUNDOS totales.

    El juego omite las partes que valen cero por la izquierda:
        '1:02:03' -> 3723   (horas:minutos:segundos)
        '14:20'   -> 860    (minutos:segundos)
        '45'      -> 45     (solo segundos)

    Si trae decimales en los segundos ('14:20.5') se descartan.
    Si no puede interpretarlo, devuelve 0 (igual que parse_abbrev).
    """
    if texto is None:
        return 0
    s = str(texto).strip().replace(" ", "")
    if not s:
        return 0

    partes = s.split(":")
    if len(partes) > 3:
        return 0

    total = 0
    for parte in partes:
        # Solo nos quedamos con la parte entera ('20.5' -> '20').
        entero = parte.split(".")[0].split(",")[0]
        if not entero.isdigit():
            return 0
        total = total * 60 + int(entero)
    return total


def format_time(segundos: int) -> str:
    """
    Segundos -> texto como en el juego: '1:02:03', '14:20'.
    Si solo hay segundos se muestra '0:45' (para que no parezca un
    número suelto en la leaderboard).
    """
    if segundos is None:
        return "0:00"
    n = max(int(segundos), 0)
    horas, resto = divmod(n, 3600)
    minutos, segs = divmod(resto, 60)
    if horas:
        return f"{horas}:{minutos:02d}:{segs:02d}"
    return f"{minutos}:{segs:02d}"


# Mapa de "formatters" disponibles por nombre, para usar desde games.py.
# Añade aquí nuevos formatos si en otro juego los necesitas.
FORMATTERS = {
    "money": format_money,      # $1.2Qa
    "income": format_income,    # $1.2Qa/s
    "plain": format_abbrev,     # 1.2Qa  (sin símbolo)
    "raw": lambda v: f"{int(v):,}",  # 1,200,000  (entero formateado)
    "integer": lambda v: str(int(v)),  # 1200000  (entero sin formato)
    "time": format_time,        # 1:02:03 / 14:20  (tiempo en segundos)
}

# Formatos cuyo valor NO usa los sufijos del juego al leerse.
# El resto se interpreta con parse_abbrev.
PARSERS = {
    "time": parse_time,
}


def parse_value(texto: str, formatter_name: str) -> int:
    """Interpreta el texto leído según el formato de la stat."""
    fn = PARSERS.get(formatter_name, parse_abbrev)
    return fn(texto)


def format_value(valor: int, formatter_name: str) -> str:
    """Aplica el formatter elegido en games.py. Si no existe, usa 'raw'."""
    fn = FORMATTERS.get(formatter_name, FORMATTERS["raw"])
    return fn(valor)
