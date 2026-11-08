# Referencia rápida de GIULI

## Navegación del gráfico

| Acción | Control |
| --- | --- |
| Ganancia vertical | Rueda del ratón |
| Desplazamiento horizontal | `Shift` + rueda |
| Zoom horizontal | `Ctrl` + rueda |
| Desplazamiento horizontal directo | Arrastre sobre el gráfico |
| Centrar señal individual en Y | Arrastre sobre el eje Y |
| Zoom rectangular X e Y | `Z`, luego clic y arrastre |
| Mostrar todo | `F` |
| Crosshair | `C` |

El zoom rectangular está deshabilitado en la vista apilada para conservar la
altura y posición fija de los carriles. En esa vista, la rueda cambia únicamente
la ganancia de intensidad de las trazas.

## Atajos

| Función | Atajo |
| --- | --- |
| Guardar | `Ctrl+S` |
| Guardar como | `Ctrl+Shift+S` |
| Deshacer / rehacer | `Ctrl+Z` / `Ctrl+Y` |
| Eliminar selección o región activa | `Del` |
| Corrección automática de fase | `P` |
| Corrección automática de línea de base | `B` |
| Referenciado químico | `R` |
| Zonas ciegas | `X` |
| Normalización | `N` |
| Integración | `I` |
| Crear conjunto | `Ctrl+Shift+G` |
| Duplicar conjunto | `Ctrl+D` |

Los atajos de una sola letra se suspenden mientras una herramienta de selección o
edición de texto necesita esas teclas.

## Formatos

- Entrada: experimentos Bruker 1D con FID y metadatos de adquisición y procesado.
- Proyecto: `.giu`.
- Matriz espectral: `.csv` o `.txt` tabulado.
- Integrales: `.csv` o `.txt` tabulado.
- Plantillas de regiones: JSON de alineación o de integración; no son
  intercambiables.

## Orden de trabajo recomendado

1. Cargar FID y revisar el procesado reconstruido.
2. Corregir fase y línea de base si es necesario.
3. Referenciar los espectros.
4. Crear un conjunto y definir zonas ciegas.
5. Alinear y revisar visualmente.
6. Duplicar el conjunto si se necesitan ramas de análisis distintas.
7. Normalizar, integrar o deconvolucionar según el objetivo.
8. Exportar y guardar el proyecto.
