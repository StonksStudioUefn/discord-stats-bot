# 🤖 Discord Stats Bot

Bot de Discord que lee capturas de pantalla de partidas, extrae el
**nombre del jugador, la puntuación y las bajas** usando **Gemini**
(Structured Output) y mantiene una tabla de clasificación en **Supabase**.

## 🧱 Estructura del proyecto

```
discord-stats-bot/
├── main.py              # Punto de entrada (bot de Discord)
├── requirements.txt     # Dependencias
├── .env.example         # Plantilla de variables de entorno
├── .env                 # TUS secretos (NO se sube a git)
├── .gitignore
├── schema.sql           # Tabla de Supabase
└── src/
    ├── __init__.py
    ├── config.py        # Carga y valida los secretos (1 solo sitio)
    ├── gemini_service.py# Extracción con Gemini + esquema Pydantic
    └── database.py      # Lógica de Supabase (mejor puntuación)
```

## 🚀 Puesta en marcha

1. **Clona e instala dependencias** (usa un entorno virtual):

   ```bash
   python -m venv .venv
   source .venv/bin/activate      # En Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configura tus secretos**:

   ```bash
   cp .env.example .env
   ```
   Rellena `.env` con tu token de Discord, API key de Gemini y
   credenciales de Supabase.

3. **Crea la tabla** en Supabase ejecutando el contenido de
   `schema.sql` en el *SQL Editor*.

4. **Activa los Intents** en el portal de desarrolladores de Discord:
   *Tu App → Bot → Privileged Gateway Intents → **MESSAGE CONTENT INTENT***.

5. **Arranca el bot**:

   ```bash
   python main.py
   ```

## ☁️ Hosting

Sube el repositorio a GitHub (el `.gitignore` ya protege el `.env`).
En tu proveedor de hosting (Railway, Render, Fly.io, un VPS...),
configura las **variables de entorno** desde su panel —**no** subas
nunca el archivo `.env`— y usa `python main.py` como comando de inicio.

## 🛡️ Notas de seguridad

- Los secretos solo se leen en `src/config.py`.
- El `.env` está excluido de git; solo se versiona `.env.example`.
- Para el backend del bot se recomienda la clave `service_role` de
  Supabase (manténla privada; nunca la uses en código de cliente).

## 🏝️ Miniaturas y fotos para el servicio de islas (`islas-jina.yml`)

El servicio común de islas de STONKS (`islas.stonksstudio.com`, en
`stonks-ecosistema/ecosistema`, carpeta `islas/`) saca la miniatura de cada
isla y la foto de cada creador de fortnite.gg por `r.jina.ai`. Jina sin clave
limita por IP: desde Cloudflare casi todo es 429 (comparte su IP de salida) y
desde los runners de GitHub contesta bien. Una clave de pago no es opción, así
que lo que falta lo lee cada día este flujo, que va aquí porque el repo es
público y los minutos de Actions son gratis.

- **Cuándo**: a las 05:17 UTC (después de la pasada del día del servicio, desde
  las 04:00) y a mano con «Run workflow».
- **Qué hace** `herramientas/islas_jina.mjs` (Node, sin dependencias):
  1. Pide al servicio los pendientes (`POST /publico/github/pendientes`): las
     islas sin miniatura buena hoy y los creadores que tocan.
  2. Lee cada página por Jina, 15 por minuto como mucho (Jina deja 20). Un 429
     espera su `Retry-After` (o 60 s) y se repite una vez; si no, se salta y
     se queda para mañana. 30 s por página como mucho, y nada nuevo pasados 11
     minutos.
  3. Manda lo leído (`POST /publico/github/resultados`) en lotes de 10 y menos
     de 600 KB, con cada página recortada a 64 KB. El servicio saca la
     miniatura o la foto con sus mismas reglas (solo URLs del CDN de Epic).
- **Quién puede escribir**: el pase OIDC de GitHub (`id-token: write`), sin
  ningún secreto. El servicio solo acepta el de este repo, en `main`, de
  `.github/workflows/islas-jina.yml`, programado o lanzado a mano. **Si se
  cambia el nombre del flujo, la rama o el repo, deja de poder escribir** hasta
  que se cambie `PASE` en `islas/src/github.ts` del ecosistema.
- **Los logs son públicos**: el script solo imprime cuentas y tiempos, nunca
  códigos de isla, creadores, direcciones, lo que contesta Jina ni el pase.
- **Cuándo falla**: si el servicio no contesta, no acepta el pase o no está
  (exit 1, para que se note). Que Jina no dé alguna página no es un fallo: se
  vuelve a pedir mañana.
- **Probar en local**: `node --test herramientas/islas_jina.test.mjs`. Con
  `SECO=1` pide los pendientes y lee a Jina, pero no manda nada; con
  `ISLAS_URL=http://localhost:<puerto>` y `JINA_URL=<un Jina de mentira>`, va
  contra un servicio en local (el pase solo se manda al de verdad o a
  `localhost`).
- GitHub apaga los flujos programados de un repo público tras 60 días sin
  actividad: si pasa, se vuelve a activar en la pestaña Actions.
