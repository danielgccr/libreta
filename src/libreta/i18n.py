"""Spanish and English. The Spanish text is the key: ``tr(text, **values)`` gives it in the
language of the environment, as gettext would without its toolchain. The editor's pages get
the same catalog (MESSAGES) for their scripts: one place for every translation.

The language: LIBRETA_LANG, else the first of LANGUAGE, LC_ALL, LC_MESSAGES and LANG that
is set; Spanish if it starts with "es", English otherwise (C and POSIX included).
"""

import os


def _language() -> str:
    for name in ("LIBRETA_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        if value := os.environ.get(name):
            return "es" if value.startswith("es") else "en"
    return "en"


LANG = _language()

EN = {
    # Command line
    "libreta: {path} no es un fichero .md": "libreta: {path} is not a .md file",
    "libreta: no existe {path}": "libreta: {path} does not exist",
    "libreta: -p {item}: el documento no tiene ese parámetro (tiene: {known})": (
        "libreta: -p {item}: the document has no such param (it has: {known})"
    ),
    "ninguno": "none",
    "libreta: la caché no está completa; se ejecuta {path}": (
        "libreta: the cache is incomplete; running {path}"
    ),
    "libreta: sin Pandoc; el Markdown tejido está en {path}": (
        "libreta: no Pandoc; the knitted Markdown is in {path}"
    ),
    "libreta: {path} en {url}": "libreta: {path} at {url}",
    "libreta: Python de {python}": "libreta: Python from {python}",
    "libreta: línea {line}: {elapsed}": "libreta: line {line}: {elapsed}",
    "libreta: {python} es anterior a Python 3.12; se usa el de libreta": (
        "libreta: {python} is older than Python 3.12; using libreta's"
    ),
    # Export and purl
    "sin valor en la caché": "no value in the cache",
    "línea {line}: el bloque no tiene salida en la caché": (
        "line {line}: the block has no output in the cache"
    ),
    "línea {line}: el bloque falla": "line {line}: the block fails",
    "línea {line}: error de sintaxis": "line {line}: syntax error",
    "línea {line}: «{name}» no está definido en ese punto": (
        "line {line}: '{name}' is not defined at that point"
    ),
    "línea {line}: «{name}» solo existe dentro de libreta": (
        "line {line}: '{name}' only exists inside libreta"
    ),
    "línea {line}: «{name}» no está instalado en el entorno del documento": (
        "line {line}: '{name}' is not installed in the document's environment"
    ),
    # Running
    "El proceso del worker ha terminado.\n": "The worker process has ended.\n",
    "No se ha ejecutado: interrumpido.\n": "Not run: interrupted.\n",
    "No hay un bloque de Python en esa línea.": "There is no Python block at that line.",
    "… {count} líneas anteriores omitidas\n": "… {count} earlier lines omitted\n",
    # The list of documents
    "{count} documento": "{count} document",
    "{count} documentos": "{count} documents",
    "No hay ficheros Markdown en esta carpeta.": "There are no Markdown files in this folder.",
    "Nuevo documento: nombre.md": "New document: name.md",
    "Nombre del nuevo documento": "Name of the new document",
    "Crear": "Create",
    "Escribe un nombre para el documento.": "Type a name for the document.",
    "El documento tiene que quedar dentro de esta carpeta.": (
        "The document has to stay inside this folder."
    ),
    "No se pudo crear: {reason}.": "Could not create it: {reason}.",
    "hoy, {time}": "today, {time}",
    "ayer, {time}": "yesterday, {time}",
    "ene feb mar abr may jun jul ago sep oct nov dic": (
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec"
    ),
    # The editor
    ": volver a todos los documentos": ": back to all the documents",
    "Sin título": "Untitled",
    "Título": "Title",
    "Python, bloque {n} de {total}": "Python, block {n} of {total}",
    "Guardado": "Saved",
    "No se ha podido guardar: {error}": "Could not save: {error}",
    "Valores actualizados": "Values updated",
    "Bloque {n}: error": "Block {n}: error",
    "Bloque {n} ejecutado": "Block {n} run",
    "Bloque {n} ejecutado, con errores en bloques anteriores": (
        "Block {n} run, with errors in earlier blocks"
    ),
    "No se ha podido ejecutar: {error}": "Could not run: {error}",
    "Ha cambiado su código": "Its code has changed",
    "Ha cambiado o se ha vuelto a ejecutar un bloque anterior": (
        "An earlier block has changed or run again"
    ),
    "Ha cambiado {file}": "{file} has changed",
}

MESSAGES = EN if LANG == "en" else {}  # what the pages translate with


def tr(text: str, **values: object) -> str:
    """`text` (Spanish) in the environment's language, with its {placeholders} filled."""
    text = MESSAGES.get(text, text)
    return text.format(**values) if values else text


def number(n: int) -> str:
    """An integer with thousands grouped: 12.345 in Spanish, 12,345 in English."""
    grouped = f"{n:,}"
    return grouped if LANG == "en" else grouped.replace(",", ".")
