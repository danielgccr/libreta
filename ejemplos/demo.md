---
title: Una muestra del padrón
date: 2026-10-21
---
Este documento es un ejemplo de libreta: un texto en Markdown en el que, cuando hace
falta, aparece un bloque de Python que se ejecuta y muestra su resultado en el sitio.
El código es un inciso del texto, como una figura o una cita.

## Los datos

La muestra está en `padron.csv`, junto a este documento: una fila por persona, con su
barrio, su edad y el número de personas con las que convive.

```python
import pandas as pd

df = pd.read_csv("padron.csv")
df.head()
```

La muestra tiene `py len(df)` personas repartidas en `py df.barrio.nunique()` barrios.

## La edad media

La media de una muestra de $n$ valores es $\bar x = \frac{1}{n}\sum_{i=1}^{n} x_i$.
En la nuestra:

```python
media = float(df.edad.mean())
mediana = df.edad.median()
print(f"de {df.edad.min()} a {df.edad.max()} años")
round(media, 1)
```

La edad media es de `py round(media, 1)` años y la mediana, de `py int(mediana)`: la
media queda por encima porque unas pocas personas muy mayores tiran de ella.

## Por barrio

```python
por_barrio = df.groupby("barrio").agg(
    personas=("edad", "size"),
    edad_media=("edad", "mean"),
    convivientes=("convivientes", "mean"),
).round(1)
por_barrio
```

El barrio más joven es `py por_barrio.edad_media.idxmin()`, con una edad media de
`py por_barrio.edad_media.min()` años, y también el de hogares más grandes:
`py por_barrio.convivientes.max()` personas de media.

## La distribución

```python
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.hist(df.edad, bins=range(0, 101, 10), edgecolor="white")
ax.axvline(media, color="black", linestyle="--", label="media")
ax.set_xlabel("edad")
ax.set_ylabel("personas")
ax.legend();
```

## Lo que no se ejecuta

Solo se ejecutan los bloques con la etiqueta exacta `python` al primer nivel del documento.
Un bloque de otro lenguaje es texto:

```bash
# esto no es un título
uv run libreta run ejemplos/demo.md
```

Y tampoco se ejecuta uno de Python dentro de una lista o de una cita:

- Por ejemplo, este:

  ```python
  print("no se ejecuta")
  ```

> ```python
> print("ni este")
> ```
