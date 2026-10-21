# Propuesta: servidor con la biblioteca estándar

Estado: aparcada (octubre de 2026). Para sopesar en el futuro; contradice el stack fijado en
`CLAUDE.md` (Starlette + uvicorn), así que adoptarla exige cambiar antes esa decisión.

## La idea

Sustituir Starlette, uvicorn y Jinja2 por `http.server.ThreadingHTTPServer`, `json` y
`http.cookies`. jedi quedaría como única dependencia del paquete.

## Por qué encaja

libreta no aprovecha nada asíncrono:

- Hablar con el worker es bloqueante (pipe de `multiprocessing`).
- Starlette ya ejecuta `/run` y `/complete` en hilos (`run_in_threadpool`), y `/run`
  transmite su salida desde un generador síncrono, con un salto hilo ↔ bucle de eventos
  por cada línea NDJSON.

Con `ThreadingHTTPServer` cada petición es un hilo que escribe directamente en el socket:
el modelo que el código ya usa por debajo, sin la capa asíncrona en medio.

## Medidas

Medidas en el entorno de desarrollo (Python 3.13, Linux), mediana de tres arranques, con
`.venv/bin/python` directamente. Con `uv run` delante el pico de memoria sale inflado
(~42 MB), porque `uv` hace `exec` del intérprete en el mismo proceso y Linux conserva
`ru_maxrss` tras el `exec`.

| Al arrancar el servidor | Memoria | Importación | Paquetes |
|---|---|---|---|
| Python solo | 11,5 MB | — | — |
| `http.server`, `json`, `http.cookies` | 17,4 MB | 13 ms | 0 |
| Starlette + uvicorn + Jinja2 | 31,0 MB | 53 ms | 9 |

Las dependencias que desaparecerían: starlette, anyio, idna, typing-extensions, uvicorn,
click, h11, y jinja2 y markupsafe si la plantilla del editor pasa a ser un `str.replace`.

## Ganancias

- Unos 14 MB menos en el proceso del servidor.
- Unos 40 ms menos de arranque.
- Menos coste por línea de salida en `/run` (solo se notaría con bucles que imprimen mucho).
- Instalación más ligera.

En términos absolutos es poco: el worker con numpy, pandas, matplotlib y jedi ronda los
180 MB y una pestaña de Chromium con el editor, 50–70 MB. Ninguna espera del usuario
depende del servidor HTTP, sino de ejecutar Python, de jedi o de Pandoc.

## Costes

Unas 100 líneas propias en `app.py`, en lugar de lo que hoy da Starlette:

- Tabla de rutas `(método, ruta) → función`.
- Validación de la cabecera Host (hoy `TrustedHostMiddleware`).
- Token en la URL la primera vez y luego en cookie, con `secrets.compare_digest`.
- Servir `static/` con su tipo MIME (`mimetypes`) y `Cache-Control: no-cache`, sin
  permitir salir del directorio (`..`).
- Leer el cuerpo JSON (`Content-Length`).
- Respuesta en streaming de `/run`: con HTTP/1.0, cuerpo delimitado por el cierre de la
  conexión; detectar `BrokenPipeError` si el navegador se va y cerrar el generador (hoy
  Starlette lo abandona y el worker drena la salida pendiente).
- Escapar el JSON del documento dentro de `<script>` (`<` → `<`), lo que hace hoy el
  filtro `tojson` de Jinja2.
- Apagado: `server.shutdown()` y matar el worker en un `finally` (hoy, el `lifespan`).

Además:

- `tests/test_app.py` llama a la app ASGI sin sockets; habría que levantar un servidor
  real en un puerto libre o probar el manejador por separado.
- La documentación de `http.server` advierte que no es para producción y solo hace
  comprobaciones de seguridad básicas. Aquí importa poco (127.0.0.1, token, Host), pero
  esas comprobaciones pasan a ser código nuestro y hay que cubrirlas con tests.

## Veredicto

Más eficiente en proporción, despreciable en absoluto. El argumento de peso sería otro:
quedarse en «solo jedi» como dependencia, en el espíritu de no usar frameworks. Es un
cambio acotado (una o dos horas con los tests), sin efecto en el editor ni en el formato.
