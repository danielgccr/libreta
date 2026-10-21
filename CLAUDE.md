# libreta

Cuaderno de Python minimalista centrado en la prosa: una hoja en blanco donde se escribe
Markdown y, cuando hace falta, se invoca un bloque de Python que se ejecuta y muestra su
salida en el sitio. El linaje es RMarkdown/knitr, no Jupyter.

El diseño completo está aquí; léelo antes de tocar el editor, el motor de ejecución,
el formato de fichero o la caché:

@docs/DESIGN.md

## Principios (filtro para cualquier decisión)

- La prosa está en el centro. El código es un inciso del texto, como una figura o una cita.
- El fichero es Markdown estándar. Lo que se ve en el editor es literalmente el fichero;
  GitHub, Obsidian y Pandoc deben poder leerlo sin saber que libreta existe.
- Escribir y probar, no explorar. La exploración interactiva ocurre en la terminal.
  Esto no es una REPL ni un generador de apps.
- Ante cualquier funcionalidad nueva, la pregunta es: ¿hace el documento mejor para
  escribir y leer, o lo está convirtiendo en otra herramienta?

## Fuera de alcance (no implementar ni proponer salvo petición expresa)

- Widgets interactivos, reactividad o grafo de dependencias entre bloques, modo app, layouts.
- Opciones de chunk al estilo knitr (`echo`, `eval`, `fig.width`...).
- Modo edición/render para el Markdown: el Markdown se edita siempre en crudo.
- Kernels de Jupyter, `ipykernel`, `jupyter_client`.

## Stack

- Backend: Python >= 3.12, Starlette, uvicorn, Jinja2, jedi. Ninguna dependencia más sin preguntar.
- Frontend: HTMX 2 vendorizado en `static/` (sin CDN, funciona offline) y JavaScript vanilla
  en módulos ES nativos. CSS escrito a mano.
- Sin paso de build, sin npm, sin frameworks. No usar CodeMirror, Monaco, Prism,
  highlight.js, React ni similares: el editor y el resaltado son propios y ese es el punto.
- Pandoc es una dependencia externa opcional, solo para `libreta export`.
- matplotlib, pandas, etc. no son dependencias del paquete: se integran si el usuario
  los tiene instalados en su entorno.

## Comandos

- Entorno: `uv sync`
- Editor: `uv run libreta` (lista de documentos) o `uv run libreta edit ejemplos/demo.md`
- Ejecución sin navegador: `uv run libreta run ejemplos/demo.md`
- Exportación: `uv run libreta export ejemplos/demo.md [--to pdf]`
- Tests: `uv run pytest`
- Lint y formato: `uv run ruff check . && uv run ruff format .`

## Estructura

```
src/libreta/
  cli.py         # edit | run | export
  app.py         # Starlette: rutas, SSE, plantillas
  document.py    # .md <-> lista de bloques (parser y serializador)
  worker.py      # proceso hijo: namespace, exec/eval, interrupción, completado (jedi)
  display.py     # protocolo _repr_*_, última expresión, captura de stdout/stderr
  _mpl.py        # backend de matplotlib propio (MPLBACKEND=module://libreta._mpl)
  cache.py       # hashes encadenados, lectura/escritura de salidas
  knit.py        # Markdown "tejido" + llamada opcional a pandoc
  templates/
  static/
    htmx.min.js
    js/          # editor.js, blocks.js, keys.js, py-highlight.js, md-highlight.js, complete.js, api.js
    css/         # tokens.css, editor.css, export.css
tests/
ejemplos/
docs/DESIGN.md
```

## Reglas de trabajo

- Pregunta antes de añadir cualquier dependencia, de Python o de JS.
- Código, identificadores y comentarios en inglés; documentación en español.
- El motor (parser, worker, display, caché, knit) se desarrolla con tests en pytest.
  El parser debe garantizar ida y vuelta exacta: `serialize(parse(texto)) == texto`.
- El editor no se puede probar desde aquí: al terminar una tarea de frontend, da una lista
  concreta de pasos de prueba manual en el navegador. No declares que funciona sin eso.
- Respeta los invariantes del editor de DESIGN.md: el overlay solo cambia colores, nunca
  métrica; toda inserción programática de texto pasa por `document.execCommand('insertText')`.
- El servidor escucha solo en 127.0.0.1, exige token y valida la cabecera Host (ejecuta código arbitrario).
- Trabaja por hitos (hoja de ruta en DESIGN.md). No adelantes trabajo de hitos posteriores.

## Git

- Nunca incluyas `.env` ni ningún secreto en commits ni pushes. `.env` está en `.gitignore`;
  no lo quites ni lo fuerces con `git add -f`.
- No firmes los commits: nada de `Co-Authored-By`, "Generated with Claude Code" ni ninguna
  otra atribución tuya en mensajes de commit, PRs o código.
- Commits pequeños, uno por paso lógico, con mensaje descriptivo.

## Estado

Hoja de ruta de DESIGN.md completa (M0–M7): v1 terminada. Ahora, mejoras sobre la marcha,
cada una con sus tests, su commit y su nota en DESIGN.md.
