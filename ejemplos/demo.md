---
title: Es buena demo
date: 2026-10-21
---
# Demo de libreta

Me está encantando esto, es comodísimo. Resaltemos expresiones matemáticas
```python
def f(x):
    return x**2

f(3)
```
Sigamos, leyuendo
```python
# los amanuenses saltan
ran = [1, 2, 3]
[i+10 for i in ran]
```
Un párrafo de prosa. El código es un inciso del texto, como una figura o una cita. ¿Cómo se ve `py [i + 10 for i in ran]` o `py [i + 11 for i in ran]`.

```python
datos = [3, 1, 4, 1, 5, 9, 2, 6, 2, 10]
sum(datos) / len(datos)
```
La media es `py sum(datos) / len(datos)`. me gusta que hablemos de cómo puede ser Nicanor un mierdas, `py 4 + 3`,  `py 5 + 5` ó `py 4 + 1`

# Matplotlib

Vamos con el análisis gráfico
```python
import numpy as np
import matplotlib.pyplot as plt

x = np.linspace(0, 2 * np.pi, 200)
fig, ax = plt.subplots()
ax.plot(x, np.sin(x), label="seno")
ax.plot(x, np.cos(x), label="coseno")
ax.legend()
plt.show()

plt.hist(np.random.default_rng(1).normal(size=500), bins=30);
```
## Lo que no se ejecuta

Un fence de otro lenguaje es texto:

```bash
# esto no es un título
echo hola
```

Ni un bloque de Python dentro de una lista:

- Por ejemplo este:

  ```python
  print("no se ejecuta")
  ```
Es que el amanuense eléctrico me ha hablado de cómo proceder.
## Fin

```python
max(datos)
datos.index
```

Es que el máximo es `py max(datos)`, no se dude.
```python
import pandas as pd

pd.read_csv("https://support.staffbase.com/hc/en-us/article_attachments/360009197031/username.csv", sep=";")
```
Me gusta cómo es.
```python
from bs4 import BeautifulSoup
```
