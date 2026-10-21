# libreta

Un cuaderno de Python centrado en la prosa. Es una hoja en blanco en la que se escribe
Markdown y, cuando hace falta, se mete un bloque de Python que se ejecuta y muestra su
salida en el sitio: texto, tablas, figuras de matplotlib, errores.

Viene de RMarkdown y knitr, no de Jupyter: sirve para escribir un documento en el que los
números salen del código, no para explorar. El fichero es Markdown estándar, así que
GitHub, Obsidian y Pandoc lo leen sin saber que libreta existe, y git lo compara línea a
línea.

````markdown
# Edad media de la muestra

```python
import pandas as pd
df = pd.read_csv("padron.csv")
df.head()
```

La edad media es `py round(df.edad.mean(), 1)` años.
````

## Instalación

Hace falta Python 3.12 o posterior, en Linux o macOS.

```sh
uv tool install git+https://github.com/danielgccr/libreta
```

o con pip, `pip install git+https://github.com/danielgccr/libreta`.

Opcionales:

- [Pandoc](https://pandoc.org), para exportar a HTML o PDF.
- WeasyPrint o typst, para el PDF.
- matplotlib, pandas, etc. no van incluidos: se usan los que tenga instalados el entorno
  del documento.

## Uso

```sh
libreta                     # lista los .md de la carpeta actual en el navegador
libreta edit informe.md     # abre un documento (si no existe, se crea al guardar)
libreta edit carpeta/       # lista los .md de otra carpeta
libreta run informe.md      # lo ejecuta de arriba abajo, sin navegador
libreta export informe.md   # informe.html (con --to pdf, informe.pdf)
```

El servidor escucha solo en `127.0.0.1` y exige un token aleatorio en la URL, porque
ejecuta código arbitrario. Se detiene con Ctrl+C en la terminal.

### El entorno de Python

El código del documento se ejecuta con el Python de su proyecto, sin configurar nada: el
`.venv` más cercano subiendo desde la carpeta del documento; si no hay, el entorno
activado (`VIRTUAL_ENV`); si no, el de libreta. Para usar pandas en un documento basta con
tenerlo en el `.venv` de ese proyecto (`uv add pandas`). libreta indica qué Python usa al
arrancar.

### Escribir

Todo es Markdown en crudo: no hay modo edición y modo render. Un bloque de Python es un
fence ` ```python ` de primer nivel; cualquier otro fence es texto y no se ejecuta.

| Atajo | Efecto |
|---|---|
| Ctrl+Alt+I | Inserta un bloque de Python (parte el párrafo por el cursor) |
| Ctrl+Enter | Ejecuta el bloque y pasa al texto siguiente; en Markdown, evalúa sus `` `py …` `` |
| Escape | Interrumpe la ejecución en curso |
| Ctrl+Shift+F10 | Reinicia Python con el namespace vacío |
| Ctrl+Espacio | Autocompletado (también salta solo al escribir) |
| Ctrl+Alt+F | Inserta una nota al pie `[^n]` con su definición |
| Ctrl+/ | Comenta o descomenta líneas de Python |
| Ctrl+A / Ctrl+C | Selecciona y copia el documento entero como Markdown |
| Ctrl+S | Guarda |

El título y la fecha van en el front matter YAML (`title`, `date`) y se editan encima del
documento; la fecha se pone sola al guardar.

### Ejecutar

- El documento se ejecuta de arriba abajo, como en knitr: si se ejecuta el bloque 5 y ha
  cambiado el 2, libreta reinicia Python y ejecuta del 1 al 5. Si solo ha cambiado el 5,
  lo reejecuta sobre el estado actual. Los bloques posteriores quedan marcados como
  obsoletos.
- La última expresión de un bloque se muestra (salvo si acaba en `;`). Cualquier objeto
  con `_repr_html_`, `_repr_png_`, `_repr_svg_`… se ve bien: DataFrames de pandas y
  polars, sympy, Altair. `display(obj)` muestra en mitad del bloque.
- Las figuras de matplotlib aparecen solas, sin `plt.show()`.
- `await` funciona en el nivel superior.
- `` `py expr` `` dentro del texto es una expresión que se evalúa; su valor aparece en el
  margen derecho y, al exportar, sustituye a la expresión.

### Caché

Las salidas no se guardan en el `.md`: viven en `.libreta/<documento>/`, junto al
documento, indexadas por un hash encadenado de los bloques. Al abrir un documento se ven
las salidas de la última ejecución sin ejecutar nada; cambiar un bloque invalida ese y
los siguientes. Es una carpeta desechable: se puede añadir a `.gitignore` o versionar.

### `libreta run`

Ejecuta el documento en un proceso nuevo, actualiza la caché e informa de los errores con
la línea del `.md`. Sale con código distinto de cero si falla algún bloque, así que sirve
en cron o en CI.

### `libreta export`

```sh
libreta export informe.md                 # informe.html, autocontenido
libreta export informe.md --to pdf        # informe.pdf
libreta export informe.md --css mio.css   # retoques de estilo encima del de libreta
libreta export informe.md --keep-md       # conserva el Markdown intermedio
```

Teje el documento con su caché (si falta algo, lo ejecuta antes) y lo convierte con
Pandoc. Sin Pandoc, deja `informe.knit.md`, Markdown con las salidas incrustadas.

## Desarrollo

```sh
uv sync
uv run libreta edit ejemplos/demo.md
uv run pytest
uv run ruff check . && uv run ruff format .
```

El backend es Starlette, uvicorn, Jinja2 y jedi. El editor es JavaScript sin
dependencias ni paso de build: textareas con un overlay resaltado por un tokenizador
propio. El diseño completo, con sus razones, está en [docs/DESIGN.md](docs/DESIGN.md).
