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
