# Documentación científica de GIULI

## Alcance y principio de diseño

GIULI implementa un flujo trazable para RMN 1D: reconstrucción desde FID Bruker,
correcciones espectrales, referenciado, alineación, normalización, integración y
deconvolución supervisada. La interfaz separa vista previa de aplicación y evita
modificar los datos durante operaciones puramente visuales.

Esta documentación distingue tres niveles: funciones delegadas a bibliotecas
publicadas, reimplementaciones basadas en métodos científicos y decisiones
propias de GIULI. Que un algoritmo tenga antecedentes no valida automáticamente
su implementación en otro programa; por ello se documentan también pruebas,
controles y limitaciones.

## Modelo de datos y reproducibilidad

Una muestra contiene eje ppm, parte real y, cuando está disponible, parte
imaginaria. Un conjunto conserva nombres de miembros y metadatos compartidos sin
duplicar los arreglos. Los proyectos `.giu` almacenan el estado confirmado con
compresión sin pérdida y no conservan el historial de deshacer entre sesiones.

Las vistas superpuesta y apilada son transformaciones de representación. Los
offsets de carril, la decimación visual y el backend OpenGL o raster no se escriben
en intensidades ni participan en cálculos científicos.

## Reconstrucción de FID Bruker

GIULI usa nmrglue para leer datos y metadatos Bruker. La receta de procesado se
toma de `pdata/<procno>/procs`; `SI` determina el tamaño de transformación. El
flujo aplica los parámetros compatibles de ventana, relleno o truncamiento,
transformada de Fourier, eje ppm y fases guardadas. No importa `1r` como fuente
científica principal.

La equivalencia visual con TopSpin u otro software depende de reproducir la misma
receta y convenciones. Parámetros ausentes, operaciones propietarias o diferencias
de signo y pivote pueden producir resultados distintos y deben registrarse.

## Corrección de fase

Para un espectro complejo S(k), GIULI aplica

```text
S corregido(k) = S(k) exp(i phi(k))
phi(k) = phi0 + phi1 (k/N - pivote)
```

La corrección manual conserva control explícito sobre `phi0`, `phi1` y el pivote.
La corrección automática llama a ACME de nmrglue, que minimiza una función basada
en entropía de la derivada y penalización de intensidad negativa. La optimización
se efectúa sobre una copia centrada y, para controlar el costo, puede usar una
muestra uniforme de hasta 8192 puntos; las fases resultantes se aplican a la
resolución completa.

Las regiones excluidas se reemplazan por interpolación compleja sólo en la copia
de optimización. Esto reduce la influencia de agua suprimida u otros artefactos
sin borrar la región del espectro. ACME puede ser sensible a línea de base,
solapamiento, baja relación señal ruido y mínimos locales; el resultado requiere
inspección.

## Corrección de línea de base

La opción automática usa arPLS de pybaselines. El problema penalizado puede
escribirse como

```text
min_z  suma_i w_i (y_i - z_i)^2 + lambda ||D^d z||^2
```

donde los pesos se actualizan de forma asimétrica a partir de los residuos
negativos. `lambda` controla suavidad y `D^d` es una diferencia de orden `d`.
GIULI escala la señal antes del ajuste y revierte la escala al finalizar.

Las exclusiones se puentean linealmente sólo para estimar la base. Esta decisión
propia evita que una señal parcialmente negativa, por ejemplo agua suprimida,
atraiga la solución. La corrección final resta la línea estimada a los datos
originales. Si las exclusiones dejan menos de dos puntos utilizables se rechaza.

La opción manual estima nodos mediante ventanas locales y usa la interpolación
lineal de nmrglue, extendiendo los valores extremos para cubrir todo el dominio.

## Referenciado químico

El referenciado desplaza únicamente el eje:

```text
delta = ppm objetivo - ppm observado
ppm nuevo = ppm original + delta
```

No interpola intensidades. El modo cursor permite marcar el centro de un
multiplete; el modo máximo local selecciona la mayor intensidad positiva dentro
de una ventana.

## Alineación

La alineación global estima un corrimiento rígido por espectro mediante
correlación. La automática usa una reimplementación matricial inspirada en
icoshift: divide una grilla común en intervalos y busca corrimientos enteros que
maximizan la correlación con un objetivo sintético mediante FFT. Se controlan
ambigüedad, límites, información mínima y zonas ciegas.

La alineación manual usa regiones definidas por el operador, correlación cruzada
por FFT e interpolación parabólica alrededor del máximo para obtener corrimientos
subdigitales. Los bordes se mezclan linealmente con la señal original. Cuando
existe componente imaginaria se aplica la misma transformación. Aunque comparte
el principio de correlación por intervalos, no es icoshift.

Los corrimientos pueden deformar límites o señales si una región contiene cambios
químicos reales, picos que varían independientemente o información insuficiente.
La alineación no debe usarse para forzar similitud biológica. Los detalles y la
receta automática se describen en [Alineación espectral](ALIGNMENT.md).

## Zonas ciegas

Una zona ciega es un intervalo ppm persistente del conjunto. El enmascaramiento
se aplica a normalización e integración total. En exportación puede eliminar las
filas o conservarlas con intensidad cero. No equivale a borrar puntos ni a una
exclusión temporal de procesado.

## Normalización

### Área total con signo

Para los puntos válidos V de una muestra j:

```text
A_j = suma_{i en V} y_ji
f_j = objetivo / A_j
```

La suma algebraica preserva el efecto de intensidades negativas, por lo que exige
fase y línea de base adecuadas. GIULI rechaza áreas no positivas o numéricamente
inestables.

### Pico máximo

El factor es el objetivo dividido por la intensidad positiva máxima fuera de las
zonas ciegas. Este método presupone que el pico elegido implícitamente es comparable
entre todas las muestras.

### PQN

GIULI interpola los espectros sobre una grilla común, excluye zonas ciegas y forma
un espectro de referencia mediano. Para cada muestra calcula cocientes punto a
punto válidos y usa su mediana como estimación de dilución. El factor es el inverso
de ese cociente. PQN supone que la mayoría de las variables no cambia de manera
coordinada por razones biológicas.

## Integración

GIULI emplea suma digital con signo, coherente con una grilla común:

```text
I_jr = suma de y_ji dentro de la región r
R_jr = I_jr / A_j
```

La suma digital es proporcional al área física cuando todos los espectros
comparten espaciado, adquisición y procesado. Si las grillas difieren, GIULI
interpola sobre la grilla de referencia dentro del dominio común e informa las
muestras afectadas. Comparaciones cuantitativas requieren parámetros experimentales
compatibles y control de fase, base, referencia y normalización.

## Deconvolución supervisada

La deconvolución modela una región con una línea de base local y perfiles de área
unitaria. Para centro `mu`, ancho a media altura `w` y mezcla `eta`, el perfil
pseudo Voigt usado es

```text
P(x) = eta L(x; mu, w) + (1 - eta) G(x; mu, w)
```

donde L y G están normalizadas a área uno. La amplitud de cada componente
representa por tanto un área en unidades intensidad por ppm. El ajuste usa
`scipy.optimize.least_squares` con límites y pérdida robusta. La muestra elegida
por el usuario calibra centros, anchos, mezcla y proporciones; el modelo común se
ajusta después a todas las muestras permitiendo desplazamientos acotados.

Para cada compuesto se informa:

- área digital ajustada del modelo;
- fracción del área ajustada regional;
- área observada repartida, igual a la fracción por la suma digital observada.

El último valor es el apropiado para integrarse a una tabla cuantitativa general,
porque reparte el área realmente observada. R², RMSE, residuos y condición del
Jacobiano son diagnósticos. Una condición excesiva indica que distintas
combinaciones de parámetros explican casi igualmente la región y el resultado se
marca como no identificable.

La selección manual de máximos no demuestra identidad química. Una superposición
perfecta puede carecer de hombro y requiere información externa, otra señal del
mismo compuesto o restricciones químicas. GIULI no infiere automáticamente el
número de compuestos.

## Exportación

La matriz espectral se escribe con ppm crecientes por fila y muestras por columna.
Los factores de normalización se aplican sin incorporar offsets visuales. Las
zonas ciegas se excluyen o se escriben como cero.

La tabla de integrales contiene una fila por muestra. Las columnas convencionales
pueden ser absolutas o relativas. Las contribuciones de deconvolución aceptadas se
añaden como columnas identificadas por compuesto y región; para exportación
relativa se dividen por la misma integral total válida de la muestra. Los
diagnósticos del ajuste deben conservarse separadamente para auditoría.

## Validación y pruebas

La suite automatizada cubre lectura de recetas Bruker, correcciones, alineación,
normalización, integración, exportación, serialización, navegación gráfica y
deconvolución. Las pruebas sintéticas verifican recuperación de parámetros,
formas, áreas y rechazos.

Estas pruebas son validación de software, no validación metrológica. Antes de usar
GIULI para conclusiones cuantitativas se recomienda evaluar materiales de control,
repetibilidad, recuperación, linealidad, límites de detección y sensibilidad a las
decisiones de procesado en el contexto experimental concreto.

## Referencias

1. Helmus JJ, Jaroniec CP. Nmrglue: an open source Python package for the
   analysis of multidimensional NMR data. *J Biomol NMR*. 2013;55:355-367.
   <https://doi.org/10.1007/s10858-013-9718-x>
2. Chen L, Weng Z, Goh L, Garland M. An efficient algorithm for automatic phase
   correction of NMR spectra based on entropy minimization. *J Magn Reson*.
   2002;158:164-168. <https://doi.org/10.1016/S1090-7807(02)00069-1>
3. Baek SJ, Park A, Ahn YJ, Choo J. Baseline correction using asymmetrically
   reweighted penalized least squares smoothing. *Analyst*. 2015;140:250-257.
   <https://doi.org/10.1039/C4AN01061B>
4. Savorani F, Tomasi G, Engelsen SB. icoshift: a versatile tool for the rapid
   alignment of 1D NMR spectra. *J Magn Reson*. 2010;202:190-202.
   <https://doi.org/10.1016/j.jmr.2009.11.012>
5. Dieterle F, Ross A, Schlotterbeck G, Senn H. Probabilistic quotient
   normalization as robust method to account for dilution of complex biological
   mixtures. *Anal Chem*. 2006;78:4281-4290.
   <https://doi.org/10.1021/ac051632c>
6. SciPy developers. `scipy.optimize.least_squares` documentation.
   <https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.least_squares.html>
7. pybaselines developers. arPLS algorithm documentation.
   <https://pybaselines.readthedocs.io/en/latest/algorithms/whittaker.html#arpls-asymmetrically-reweighted-penalized-least-squares>
