# Diseño de libreta

## 1. Por qué existe

Los notebooks de Python descienden de IPython, es decir, de una REPL mejorada: la pregunta
de origen era "¿cómo exploro interactivamente?" y la prosa llegó después, como un tipo de
celda más. RMarkdown desciende de Sweave y knitr, de estadísticos que escribían informes:
la pregunta era "¿cómo escribo un documento en el que los números salen del código?".

- Jupyter: el centro es la celda; el Markdown tiene modo edición y modo render; el fichero
  es un JSON ilegible e imposible de diffear.
- Marimo: el centro es el programa; la prosa vive en strings `mo.md("...")`.
- Streamlit: es una app que reejecuta el script entero; no es un documento.
- Quarto: trae el modelo de RMarkdown, pero ejecuta Python a través de un kernel de Jupyter
  con Pandoc y Deno debajo. Pesado.

libreta recupera la segunda pregunta: un texto con cálculos. La exploración queda fuera
(para eso está la terminal). El caso de uso es escribir y probar código dentro de un documento.

Precedentes que conviene estudiar: Livebook (Elixir, ficheros `.livemd`), Observable
Framework (JS), Clerk (Clojure), knitr con `cache=TRUE`. En Python hay ejecutores de bloques
en Markdown por lotes (markdown-exec, Pweave, Codebraid, Jupytext en formato `.md`), pero
no un editor interactivo, ligero y centrado en la prosa.

## 2. Experiencia de uso

Una página en blanco con una sola columna de lectura centrada. Se empieza escribiendo
Markdown. Nada de celdas visibles: el documento parece una hoja continua.

| Atajo | Efecto |
|---|---|
| Ctrl+Alt+I | Inserta un bloque de Python. A mitad de un bloque de Markdown, lo parte por el cursor e inserta el de Python en medio. (Mismo atajo que "insertar chunk" en RStudio.) |
| Ctrl+Alt+F | En Markdown, inserta una nota al pie: `[^n]` en el cursor (`n`, el primer número libre del documento) y su definición `[^n]: ` tras el párrafo y las definiciones que ya tenga debajo, donde queda el cursor. (Mismo atajo que en Word.) |
| Ctrl+Enter | En un bloque de Python: lo ejecuta, pinta la salida y lleva el foco al bloque de Markdown siguiente, creándolo si no existe. En Markdown: evalúa sus expresiones `py` (§4.7). |
| ArrowUp / ArrowDown | En la primera o última línea de un bloque, saltan al bloque anterior o siguiente. La salida de un bloque nunca recibe foco. |
| Backspace / Supr | Backspace al inicio de un bloque de Python vacío, o Supr dentro de él o al final del Markdown que lo precede, lo elimina y fusiona los bloques de Markdown adyacentes. |
| Ctrl+A / Ctrl+C | Seleccionan y copian el documento completo como Markdown (con sus fences), no solo el bloque activo. En un bloque de Python, el primer Ctrl+A selecciona su código; el segundo, el documento. |
| Ctrl+S | Guarda. |
| Ctrl+Espacio | Autocompletado (además del disparo automático, ver §6.6). |
| Escape | Con un bloque en ejecución, lo interrumpe (`KeyboardInterrupt`). |
| Ctrl+Shift+F10 | Reinicia el worker con el namespace vacío (mismo atajo que "restart R" en RStudio). |

Los bloques de Python son una franja gris (`--code-bg`). Dentro van el código y, debajo,
su salida: texto, tablas HTML, figuras de matplotlib, errores. El bloque gris es la unidad
completa de "código y lo que produce".

## 3. Formato de fichero

El fichero es Markdown estándar (CommonMark). Reglas:

- Un bloque de Python ejecutable es un fence de primer nivel con info string exactamente
  `python`: ` ```python `. Todo lo demás (incluidos fences de otros lenguajes o de Python
  anidados en listas o citas) es texto Markdown y no se ejecuta.
- El código inline `` `py expr` `` dentro del Markdown es una expresión que se evalúa (§4.7).
  En GitHub o en cualquier visor se ve la expresión, que sigue siendo legible.
- Las salidas no se guardan en el `.md`. Viven en la caché (§5).
- Front matter YAML opcional al principio (`---` … `---`), el de Pandoc, Obsidian y GitHub.
  libreta solo lee y escribe `title` y `date`; el resto de claves se conserva tal cual.
  Al guardar, `title` es el del editor (se borra si queda vacío) y `date` el día del
  guardado (ISO, sin comillas: una fecha YAML). Un documento sin front matter solo lo
  recibe cuando se le pone título. Valores de una línea: no hay parser de YAML.
- Garantía de ida y vuelta: `serialize(parse(texto)) == texto`, byte a byte, incluidos
  espacios finales, líneas en blanco y finales de línea. Es un test obligatorio con
  ficheros de ejemplo variados.

Ejemplo:

````markdown
# Edad media de la muestra

Cargamos los datos del padrón.

```python
import pandas as pd
df = pd.read_csv("padron.csv")
df.head()
```

La edad media es `py round(df.edad.mean(), 1)` años.
````

El parser es propio y basado en líneas (no hace falta una librería de Markdown para dividir
en bloques). Debe respetar las reglas de CommonMark para fences: longitud del fence de
cierre >= apertura, mismo carácter, indentación de hasta 3 espacios.

## 4. Modelo de ejecución

### 4.1 Worker

Un proceso hijo por documento con un namespace persistente (`dict`) donde se hace `exec`.
Comunicación con el servidor por un socket con el protocolo de `multiprocessing.connection`
(mensajes serializados). Nada de kernels de Jupyter.

- Entorno: el worker es un subproceso del Python del proyecto del documento, sin
  configurar nada: el `.venv` más cercano subiendo desde su carpeta (PEP 704), si no el
  entorno activado (`VIRTUAL_ENV`), si no el Python de libreta. Corre con ese entorno
  "activado" (`VIRTUAL_ENV`, `PATH`). Un *finder* de importación le presta `libreta`,
  `jedi` y `parso` desde la instalación de libreta; nada más de ella se cuela. Un entorno
  con Python anterior a 3.12 no sirve (se avisa y se usa el de libreta). La lista de
  módulos importables del editor (§6.3) se pide a ese mismo Python. Solo POSIX.

- Interrupción: SIGINT al worker (`KeyboardInterrupt` dentro del bloque en curso).
- Reinicio: matar y crear un worker nuevo con namespace vacío.
- Un solo worker a la vez. Nace la primera vez que un documento ejecuta código o pide
  completado (abrir un documento o la lista no arranca ninguno). Cuando otro documento lo
  hace, el worker del anterior se cierra; y cuando la página del documento se va (pestaña
  cerrada, recarga, ir a la lista u a otro fichero), avisa con `sendBeacon` a `.../restart`
  y su worker se cierra también. La caché sigue mostrando las salidas; la siguiente
  ejecución aplica §4.5.
- El worker arranca con `MPLBACKEND=module://libreta._mpl` en su entorno (§4.4) y no importa
  matplotlib ni pandas por su cuenta: solo si el usuario lo hace.

### 4.2 Ejecución de un bloque

1. `ast.parse` del código. Si la última sentencia es una expresión (`ast.Expr`), se ejecuta
   el resto con `exec` y la última con `eval`, y su valor se muestra (como en Jupyter).
   Si la línea termina en `;`, no se muestra.
2. Se compila con `filename` igual a la ruta del `.md` y los números de línea desplazados
   (el código se rellena con saltos de línea delante, lo que también cubre los
   `SyntaxError`) para que los tracebacks apunten a la línea real del fichero.
3. stdout y stderr se capturan y se emiten en streaming, intercalados en orden con las
   figuras y los valores mostrados. La salida de un bloque es una lista ordenada de
   elementos `(mime, contenido)`. Un retorno de carro (`\r`) reescribe su línea, como en
   una terminal: las barras de progreso (tqdm) muestran y guardan en caché una sola línea,
   no cada fotograma. Las escrituras seguidas a un mismo flujo se guardan juntas. Un flujo
   que pasa de 4.000 líneas se queda con las 2.000 últimas, tras una línea "… N líneas
   anteriores omitidas" (en el editor y en la caché): un bucle que imprime mucho no pesa.
4. `await` en el nivel superior, como en Jupyter: el código se compila con
   `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT` y, si espera algo, corre en un bucle de eventos que el
   worker conserva entre bloques (una sesión de `httpx` creada en un bloque sirve en el
   siguiente). El código que no espera no lo toca, así que `asyncio.run()` sigue valiendo.
   Vale también en las expresiones `py`. Escape con el bucle esperando cancela la tarea
   (`call_soon_threadsafe`) en vez de lanzar la excepción entre dos pasos de asyncio, que
   puede dejarlo roto; dentro de un paso se lanza `KeyboardInterrupt`, que asyncio deja
   pasar.
5. Errores: traceback recortado a los frames del código del usuario, mostrado dentro del
   bloque gris con un tono rojo apagado.

### 4.3 Protocolo de display

Para mostrar un valor, se prueba en este orden: `_repr_html_`, `_repr_svg_`, `_repr_png_`,
`_repr_jpeg_`, `_repr_latex_` (texto en el editor, fórmula en el export si va entre `$`),
`_repr_markdown_` (en v1 se muestra como texto), `repr()`. Para cada tipo, lo que dé
`_repr_mimebundle_` (Altair, plotly, sympy) va antes que el método suelto; su `text/plain`
sustituye a `repr()`. Con esto pandas, polars, sympy y similares funcionan sin integración
específica.

`display(*objetos)` es un builtin del worker, como en Jupyter: muestra cada objeto en ese
punto de la salida. Una variable `display` del usuario lo tapa.

### 4.4 matplotlib

Backend propio basado en Agg, cargado con `MPLBACKEND=module://libreta._mpl` (consultar la API
de backends de la versión de matplotlib instalada). Su `show()` emite las figuras abiertas
en ese punto del stream y las cierra. Al terminar el bloque se emiten las figuras que queden
abiertas sin `plt.show()`.

- Formato por defecto SVG; PNG con dpi alto como alternativa, y automáticamente cuando el
  SVG pasaría de 1 MB (unos 10.000 puntos), que como PNG ocupa unos 50 KB.
- `figsize` por defecto acorde con el ancho de la columna.
- Figura transparente (o `facecolor` igual a `--code-bg`) para que el gráfico parezca
  impreso sobre el bloque gris.
- En el cliente, las figuras se muestran al 100% del ancho del bloque, nunca más. El SVG
  conserva el tamaño de la figura (sin `bbox_inches="tight"`, con `constrained_layout`) y
  se dibuja a la escala en la que el `figsize` por defecto (6,8 pulgadas) llena el bloque:
  una figura más estrecha ocupa su parte proporcional en vez de estirarse.

### 4.5 Orden y estado

La semántica de referencia es knitr: el documento se ejecuta de arriba abajo, cada bloque
sobre el estado que dejan los anteriores.

- `libreta run` es la reproducción canónica: proceso nuevo, de arriba abajo, siempre.
- El editor es pragmático: el worker recuerda hasta qué hash encadenado (§5) refleja su
  estado. Si se pide ejecutar el bloque N y algún bloque anterior ha cambiado desde la
  última ejecución, se reinicia el worker y se ejecuta 1..N. Si solo ha cambiado el propio
  bloque N, se reejecuta sobre el estado actual (impuro, como en Jupyter, y aceptado).
- Los bloques posteriores a uno modificado o reejecutado se marcan como obsoletos.

### 4.6 Petición de ejecución

El cliente envía el documento completo junto con la línea donde abre el fence del bloque
a ejecutar (no su índice: el editor añade bloques de Markdown vacíos que no existen en el
fichero). El servidor lo reparsea, calcula los hashes encadenados y decide qué ejecutar.
Así no hace falta sincronizar ids de bloque entre cliente y servidor.

### 4.7 Código inline `py`

- Se evalúa con `eval` (solo expresiones, no sentencias) sobre el estado del namespace en
  ese punto del documento: después de los bloques anteriores y antes de los siguientes.
- No hay sintaxis de formato propia: `py round(x, 1)` o `` `py f"{x:.1f}"` `` ya son Python.
  El valor se muestra con `str()`, no con `repr()`: es prosa.
- Se evalúan al ejecutar el bloque que las precede (las anteriores al primer bloque, cuando
  el worker arranca) y con Ctrl+Enter en el Markdown: si el worker está justo en ese punto
  del documento solo se evalúan; si no, se aplica §4.5 hasta el bloque anterior.
- Son las mismas que colorea el editor: spans de código de una línea fuera de fences cuyo
  contenido empieza por `py` y un espacio.
- En el editor, el valor aparece en el margen derecho a la altura de su línea, como nota al
  margen (ver §6.5). En la exportación se sustituye en línea.
- Si la caché queda obsoleta, el valor se atenúa hasta la siguiente ejecución.

## 5. Caché

- Clave de cada bloque: hash encadenado `h_i = sha256(h_{i-1} + código_i)`. Cambiar un
  bloque invalida ese y todos los posteriores.
- Contenido: la lista ordenada de salidas del bloque, los valores de las expresiones `py`
  inline del Markdown que lo sigue, y las figuras como ficheros aparte.
- Ubicación: un directorio oculto junto al documento, `.libreta/<nombre-del-doc>/`:
  `<hash>.json` con la lista de salidas y `<hash>-<n>.<ext>` por figura.
- Cada ejecución (del editor o de `libreta run`) borra las entradas cuyo hash no está en la
  cadena del documento que se ejecuta, así que la caché no crece con las ediciones.
- Al abrir un documento, cada bloque con caché válida muestra su salida sin ejecutar nada.
- La caché sirve para mostrar, no restaura el namespace. Tras abrir un documento, el worker
  está vacío y la primera ejecución en el editor aplica la regla de §4.5.

## 6. Editor

### 6.1 Arquitectura

El documento es una secuencia de bloques; cada uno es un `<textarea>` autoajustable con un
`<pre>` resaltado debajo (técnica de overlay). El textarea es transparente
(`color: transparent; caret-color: var(--text)`) y recibe la escritura, así que el
navegador aporta cursor, selección, undo/redo, IME y portapapeles. El `<pre>` se repinta en
cada evento `input`, con un `\n` final para igualar la última línea vacía. El scroll de
ambas capas se sincroniza.

Bloques de Markdown: fuente de texto del documento. Bloques de Python: monoespaciada, dentro
del contenedor gris junto a su `<div>` de salida.

Encima de los bloques, el título del front matter (§3) en un `<input>` con el aspecto del
título exportado, y debajo la fecha del último guardado, que no se escribe. Es la excepción
a "lo que se ve es el fichero": el YAML no se muestra; Enter o ↓ bajan del título al
documento, ↑ desde la primera línea sube al título.

El historial de deshacer es el nativo de cada textarea y no cruza bloques. Partir un
bloque (Ctrl+Alt+I) o unir dos (Backspace o Supr sobre un bloque de Python vacío) cambia el
texto de un solo textarea con `execCommand` y se anota: cuando el deshacer o rehacer de ese
textarea devuelve su texto al otro lado del cambio, los bloques añadidos o quitados lo
siguen. Si esos bloques se han editado desde entonces, el deshacer se rechaza en vez de
duplicar o perder texto. Quitar o añadir un bloque de Python vacío sin mover texto no se
deshace con Ctrl+Z.

Cada título de Markdown (`#`, `##`...) abre un bloque nuevo, de modo que el bloque puede
recibir el margen superior correspondiente al título y el ritmo vertical del editor se
parece al del documento exportado. Para el usuario sigue siendo una hoja continua: sin
bordes ni separaciones visibles entre bloques de Markdown.

### 6.2 Invariantes (romperlos desalinea cursor y texto)

- El overlay solo cambia colores. Nunca tamaño, peso (`bold`), estilo (`italic`), familia
  ni espaciado, porque cambian el ancho de los glifos.
- Textarea y `<pre>` comparten exactamente: `font` (el textarea necesita `font: inherit`,
  los controles de formulario no heredan), `letter-spacing`, `line-height`, `tab-size`,
  `white-space: pre-wrap`, `overflow-wrap`, `padding`, `border`, `font-kerning`,
  `font-variant-ligatures` y `text-rendering`.
- Nada de `text-wrap: pretty`, `hyphens` ni `optimizeLegibility` en las capas del editor:
  el textarea parte líneas de forma voraz y el `<pre>` debe hacer lo mismo.
- Toda inserción programática de texto usa `document.execCommand('insertText', false, s)`.
  Asignar `textarea.value` destruye el historial de undo nativo.

### 6.3 Edición de Python

- Tab inserta 4 espacios; Shift+Tab desindenta; ambos funcionan sobre selecciones de varias líneas.
- Enter conserva la indentación y la aumenta tras una línea terminada en `:`.
- Dedent automático tras `return`, `pass`, `break`, `continue`, `raise`.
- Backspace en zona de indentación borra hasta la tabulación anterior.
- Ctrl+/ comenta y descomenta.
- `spellcheck="false"`, `autocapitalize="off"`, `autocorrect="off"`.

Tokenizador propio en JS, solo para Python: keywords (incluidas las soft keywords `match`,
`case`, `type`), builtins, números (`1_000`, `0x1F`, `1e-3`, `2j`), comentarios, decoradores,
nombres tras `def` y `class`, y strings con prefijos (`r`, `b`, `f`, `rb`, `fr`...). Los
módulos importados que el entorno no tiene (`import pandas` sin pandas instalado) van en
gris: el servidor manda al cargar la página los módulos importables (`pkgutil` sobre la
carpeta del documento y `sys.path`, más los de las distribuciones instaladas) y el
tokenizador mira el primer nombre de cada `import`/`from`. La lista se pide de
nuevo (`GET /modules`) cuando la ventana recupera el foco: tras un `uv add` en la terminal. Los
triple-quoted abarcan varias líneas, así que el tokenizador arrastra estado entre líneas.
En v1 un f-string se colorea entero como string.

### 6.4 Coloreado del Markdown

Sin cambiar métrica (§6.2): títulos en un tono más oscuro que el cuerpo; marcadores de
sintaxis (`#`, `*`, `_`, `>`, `-`, `` ` ``) en `--text-muted` para que se retiren; código
inline con su fondo; enlaces en `--accent`; expresiones `` `py ...` `` en un color propio.
Matemáticas TeX entre dólares, como las lee Pandoc (`tex_math_dollars`): `$...$` en línea
(sin espacio junto a los dólares de dentro ni dígito tras el de cierre, así que `$20 y $30`
es texto) y `$$...$$`, también en varias líneas si el `$$` abre al principio de una.
Los dólares en `--text-muted` y la fórmula en `--hl-math`. No se renderiza (sin KaTeX).
Mientras se escribe, un `$` sin cierre en su línea colorea el resto de la línea como fórmula,
salvo si le sigue un espacio o un dígito (`$20` sigue siendo texto).
Notas al pie con referencia, `[^1]` en el texto y `[^1]: …` al principio de línea: los
corchetes, el `^` y el `[^1]:` de la definición en `--text-muted`, la etiqueta de la
referencia en `--accent`. La etiqueta admite espacios (`[^la nota]`) y, mientras se
escribe, un `[^` sin cierre en su línea colorea el resto como etiqueta. Las notas en línea `^[…]` no: GitHub no las lee y el lector
`commonmark_x` de Pandoc tampoco. En el editor la nota se queda donde se escribe; el margen
es de los valores `py` (§6.5). Pandoc numera las notas por orden de aparición, así que el número
que pone Ctrl+Alt+F (§2) es solo una etiqueta: no hay que renumerar al mover texto.

### 6.5 Valores inline al margen

Los valores de las expresiones `py` no pueden insertarse en el overlay (romperían la
correspondencia carácter a carácter). Se muestran en el margen derecho de la columna, a la
altura de su línea. Para obtener la posición vertical: un `<span>` marcador en el `<pre>`
y `getBoundingClientRect()`. Solo se miden los bloques con expresiones `py`, y al llegar
los valores de un bloque, o al insertarlo o borrarlo, solo se repinta el Markdown de alrededor:
en un documento de cientos de bloques, cada medición fuerza una maquetación.

### 6.6 Autocompletado

- En el worker, con `jedi.Interpreter(código, namespaces=[ns])`, que combina análisis
  estático con los objetos vivos: completa columnas de un DataFrame ya cargado y también
  imports que aún no se han ejecutado. Firmas con `get_signatures()`.
- El código que se pasa a jedi es el de todos los bloques de Python hasta el actual.
- Disparo: al empezar a escribir un nombre, al escribir `.` o `["`, y con Ctrl+Espacio;
  con debounce. En comentarios no hay lista. La lista llega una
  vez y el cliente la filtra mientras se sigue escribiendo el nombre; los nombres con `_`
  inicial solo aparecen si se ha escrito `_`. Las firmas se piden al escribir `(` y `,`.
- Mientras se ejecuta un bloque no hay ayuda: el worker está ocupado.
- Funciona también dentro de `` `py ...` `` en el Markdown.
- Transporte: `fetch` con JSON (no HTMX).
- Posición del desplegable: `<span>` marcador en la posición del cursor dentro del `<pre>`.
- Flechas para navegar, Tab o Enter para aceptar (vía `execCommand`), Escape para cerrar.
  Shift+Enter cierra la lista y salta de línea (con la indentación de Enter). Ctrl+Enter
  sigue ejecutando.

### 6.7 Accesibilidad

- Los bloques de Python se anuncian numerados ("Python, bloque 2 de 5"); se renumeran en
  cada cambio de estructura.
- Los valores `py` del margen describen el bloque de Markdown (`aria-describedby`): "media =
  44.0". La expresión va como texto oculto; a la vista no cambia nada.
- Una región `aria-live="polite"` anuncia cómo acaba cada ejecución ("Bloque 2 ejecutado",
  "Bloque 3: error"), los valores actualizados y el guardado. Solo el final: las
  ejecuciones rápidas no llenan de avisos.
- La decoración generada con CSS (la flecha hacia la lista, el "·" entre valores) lleva
  texto alternativo propio en `content`.

### 6.8 Limitación asumida

No se puede seleccionar con el ratón texto que abarque dos bloques. Se mitiga con el
Ctrl+A / Ctrl+C sobre el documento completo (§2).

## 7. Servidor

Starlette con uvicorn. El cliente usa `fetch` en vanilla para todo (`api.js`): el
documento llega como JSON incrustado en la página y el JS construye los bloques, así que
hasta ahora no ha hecho falta intercambiar fragmentos HTML y HTMX no se usa.

El servidor sirve una carpeta (la raíz): un worker por documento abierto, creado al usarlo.
Solo documentos `.md` dentro de la raíz; las rutas con `..` que salen de ella dan 404.

Endpoints:

- `GET /` la lista de los `.md` de la raíz y sus subcarpetas (sin carpetas ocultas,
  `node_modules` ni `.knit.md`), del más reciente al más antiguo: la ruta a la izquierda,
  la fecha de la última edición a la derecha ("hoy, 20:41", "21 oct", "3 mar 2025").
  Encima, una fila para crear un documento: se escribe su nombre (`.md` opcional, con
  carpetas si se quiere) y `POST /new` crea el fichero vacío y abre el editor; si ya
  existe, solo lo abre. Un nombre que no puede crear (sale de la carpeta, vacío, choca con
  una carpeta) vuelve a la lista con el nombre escrito, la fila en rojo y el motivo debajo.
- `GET /edit/<ruta>` el editor del documento. Las demás llamadas cuelgan de esa misma URL
  (`/edit/<ruta>/run`...), así que `api.js` solo necesita `location.pathname`. Encima del
  título, la ruta del documento enlaza a la lista.
- `PUT /doc` `{text, title}` guardar (escritura atómica, conserva CRLF). Pone el título y
  la fecha en el front matter y responde `{text, front, date}`: lo que quedó en disco.
- `POST /run` `{text, line}`: documento completo y línea donde abre el fence del bloque.
  Responde en streaming con NDJSON, un elemento `{mime, content}` (o `{mime, base64}`)
  por línea, en orden. Antes de la salida de cada bloque que se ejecuta llega `{start: línea}`:
  si hay que reejecutar 1..N (§4.5), cada bloque recibe la suya. Un error en un bloque
  anterior no detiene la reejecución (cada bloque muestra el suyo); Escape sí, y el N recibe
  un error que lo explica. Los valores `py` del Markdown que sigue a un bloque llegan como
  `{values: {expr: {text} | {error}}, line}` (`line` 0: antes del primer bloque). Con
  `inline: true`, `line` es la de un bloque de Markdown y se evalúan sus expresiones.
  Una sola petición: ni id de ejecución ni `EventSource`.
- `POST /interrupt`, `POST /restart`.
- `POST /complete`, `POST /signature` `{text, line, column}` (cursor en el documento):
  `[{name, complete, type}]` (`complete` es lo que se inserta en el cursor) y
  `[{name, params, index}]`.

## 8. CLI

- `libreta` a secas sirve la carpeta actual y abre la lista de sus documentos;
  `libreta edit carpeta/` hace lo mismo con otra carpeta.
- `libreta edit doc.md` sirve la carpeta del documento y abre el navegador en él.
- `libreta run doc.md` ejecuta de arriba abajo en un proceso nuevo, actualiza la caché e
  informa de errores con línea del `.md`. Código de salida distinto de cero si falla algún
  bloque. Pensado para terminal, cron y CI.
- `libreta export doc.md [--to html|pdf] [--css ...]` genera el Markdown tejido (§10) y, si
  Pandoc está instalado, lo convierte. Si a la caché le falta algo, ejecuta antes el
  documento entero; a diferencia de `run`, sigue tras un error, que queda en el documento
  como en el editor. El código de salida es 1 si el documento exportado contiene errores.
  `--css` añade hojas detrás de `tokens.css` y `export.css` (sirve para retocar).

## 9. Estilo

Dos capas sobre los mismos tokens:

- `tokens.css`: paleta, medida, tamaños base, `--code-bg`, `--accent`. Incluye la paleta
  oscura bajo `@media (prefers-color-scheme: dark)`. Si se declara `color-scheme: light dark`,
  la paleta oscura es obligatoria (si no, los controles nativos se pintan oscuros sobre
  fondo claro). En oscuro, las figuras SVG se invierten (`invert(1) hue-rotate(180deg)`):
  matplotlib dibuja en negro sobre transparente.
- `export.css`: la hoja editorial para Pandoc HTML (títulos con tamaño y peso, ligaduras en
  la prosa, `text-wrap`, etc.).
- `editor.css`: misma columna, fondo, paleta, interlineado y bloque gris; sin variaciones
  de métrica en el texto (§6.2). El editor debe sentirse como una prueba de imprenta del
  documento exportado.

Notas sobre la hoja editorial existente:

- `font-variant-ligatures: none` va en `code, pre`, no en `html`.
- `main` con `max-width: var(--measure); margin-inline: auto; padding-inline: ...` en vez de
  `width`, para no desbordar en pantallas estrechas.
- Ritmo vertical en una sola unidad (`lh` o `em`, no ambas).
- Los enlaces usan `var(--accent)`; el código inline se selecciona con `:not(pre) > code`.
- La medida se mide en `ch` de la fuente de texto: con código a 0.875em en monoespaciada,
  una columna de 68ch admite unos 65-70 caracteres de código antes del scroll horizontal.

## 10. Exportación

Mismo esquema que RMarkdown: libreta produce un Markdown "tejido" a partir del `.md` fuente y
la caché (valores `py` sustituidos, figuras como ficheros enlazados, salida de texto en
fences, HTML de tablas incrustado), y Pandoc lo convierte con `export.css`. Sin Pandoc,
`libreta export` deja el Markdown tejido.

- Ficheros junto al documento: `doc.html` (o `doc.pdf`). El Markdown tejido `doc.knit.md` y
  sus figuras en `doc_files/` se borran tras convertir (el HTML las lleva dentro); se
  quedan sin Pandoc, si Pandoc falla o con `--keep-md`. De `doc_files/` solo se borran las
  figuras de libreta, y la carpeta si queda vacía.
- Cada bloque de Python con su salida va en un div `::: {.chunk}`: el bloque gris del
  editor. Texto en fences `{.output}` (`.stderr`, `.error`), HTML como bloque crudo
  `{=html}`, `_repr_markdown_` tal cual, figuras con `{width=NN%}` a la escala del editor.
  El Markdown tejido es entrada de Pandoc (`commonmark_x`), no un documento para GitHub.
- El título y la fecha del front matter encabezan el HTML (Pandoc los lee del YAML).
- HTML autocontenido (`--embed-resources`), matemáticas en MathML (sin JavaScript) y una
  plantilla propia (`templates/export.html`) sin el CSS de resaltado de Pandoc: `export.css`
  colorea sus clases con la paleta del editor.
- PDF: con WeasyPrint si está (respeta `export.css`); si no, typst, que maqueta a su manera
  y omite el HTML crudo (tablas).

## 11. Seguridad

El servidor ejecuta código arbitrario: escucha solo en 127.0.0.1, genera un token aleatorio
por sesión (en la URL que abre el CLI, luego en cookie) y rechaza peticiones cuya cabecera
Host no sea localhost/127.0.0.1 (protección frente a DNS rebinding).

## 12. Hoja de ruta

Cada hito termina con tests en verde y, si toca frontend, pasos de prueba manual.

- M0. Esqueleto: `pyproject.toml` con uv, ruff, pytest; `libreta edit` sirve una página vacía
  con la columna; `document.py` con parser/serializador y tests de ida y vuelta.
- M1. Motor sin navegador: worker, ejecución de bloques, última expresión, protocolo de
  display, captura ordenada de stdout, tracebacks con línea del `.md`, backend de
  matplotlib. `libreta run` funcional.
- M2. Editor: bloques textarea+overlay, tokenizador de Python, coloreado de Markdown,
  atajos de §2, navegación entre bloques, guardado.
- M3. Ejecución desde el editor: Ctrl+Enter, salida en el bloque gris por SSE, figuras,
  interrupción y reinicio.
- M4. Caché y obsolescencia (§4.5, §5).
- M5. `py` inline y valores al margen.
- M6. Autocompletado y firmas con jedi.
- M7. Exportación con Pandoc, modo oscuro, pulido de `editor.css` y `export.css`.

## 13. Decisiones abiertas

- Medida de la columna: el diseño inicial habló de 80ch; la hoja editorial usa 68ch.
- ¿El bloque gris puede ser más ancho que la prosa (recurso editorial para código y figuras)?
- ¿La caché se versiona en git o va en `.gitignore`?
- Guardado: explícito con Ctrl+S, automático con debounce, o ambos.
- Cambios externos al fichero mientras está abierto en el editor (fuera de alcance en v1).
- Servidor con la biblioteca estándar en vez de Starlette y uvicorn: ver
  `docs/servidor-stdlib.md`.
- Optimización futura del reinicio en §4.5: snapshots del worker con `os.fork` tras cada
  bloque (copy-on-write, solo Linux/macOS) para no reejecutar bloques caros.
