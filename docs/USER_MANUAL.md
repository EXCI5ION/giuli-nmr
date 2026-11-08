# Manual de usuario de GIULI

## Propósito y alcance

GIULI es una aplicación de escritorio para procesar, comparar y analizar
espectros de RMN 1D. Su flujo actual está orientado a experimentos Bruker de
protón y a conjuntos usados en metabolómica. Este manual describe cómo obtener
un resultado reproducible desde la carga de las FID hasta la exportación.

GIULI no sustituye la revisión espectroscópica. Las correcciones automáticas,
alineaciones y deconvoluciones son propuestas calculadas que deben evaluarse con
el espectro, los residuos y el conocimiento químico del experimento.

## Instalación

### Windows

Descarga el instalador desde la página de la versión publicada y sigue el
asistente. El ejecutable incluye Python y las dependencias necesarias.

### Linux en Debian Ubuntu y derivados

Con Git y Python 3.12 o 3.13 disponibles:

```bash
git clone https://github.com/EXCI5ION/giuli-nmr.git
cd giuli-nmr
python3 packaging/linux/install_linux.py
giuli
```

El instalador crea un entorno aislado y añade `giuli` y `giuli-update`. También
puede hacerse una instalación local siguiendo las instrucciones del README.

### macOS

```bash
git clone https://github.com/EXCI5ION/giuli-nmr.git
cd giuli-nmr
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install .
./.venv/bin/giuli
```

No es necesario activar el entorno virtual. Usar su ejecutable de forma explícita
evita conflictos entre `python`, `python3` y distintos shells.

## Organización de la interfaz

La lista izquierda contiene muestras y conjuntos. El área central muestra el
espectro. El panel inferior o lateral aparece sólo durante operaciones que
requieren parámetros o una vista previa. Las acciones se agrupan en Archivo,
Editar, Ver, Procesado, Conjunto, Análisis y Ayuda.

Una muestra representa un espectro. Un conjunto referencia varias muestras sin
duplicar sus arreglos y conserva propiedades comunes como modo de visualización,
zonas ciegas, factores de normalización y regiones de integración.

## Cargar datos Bruker

1. Selecciona **Archivo > Cargar datos**.
2. Elige una carpeta que contenga experimentos Bruker.
3. Revisa los experimentos detectados y confirma la carga.
4. Comprueba fase, rango ppm, intensidad y nombre de cada muestra.

GIULI reconstruye los espectros desde la FID y usa la receta compatible hallada
en `pdata/<procno>/procs`. El tamaño `SI` se toma de esa receta; no se solicita
durante la importación. Los demás experimentos presentes en una carpeta no se
cargan si no corresponden a una fuente FID seleccionada.

## Navegar y visualizar

La rueda modifica la ganancia vertical. `Shift` más rueda desplaza el intervalo
ppm y `Ctrl` más rueda realiza zoom horizontal. El arrastre normal desplaza el
espectro horizontalmente. En una vista individual, el eje Y puede arrastrarse
para centrar la señal.

Pulsa `Z` para activar el zoom rectangular en X e Y y arrastra la región de
interés. Pulsa `Z` nuevamente para salir. Esta herramienta se deshabilita en
espectros apilados porque el eje vertical está reservado a los carriles fijos.
`F` muestra el dominio completo respetando la geometría del modo actual.

`C` activa el crosshair. En **Ver > Apariencia del espectro** se ajustan color,
grosor y apariencia del crosshair. **Ver > Motor gráfico** permite escoger
OpenGL o raster; el indicador de estado informa el backend que Qt pudo activar.

## Corregir fase

La corrección manual permite ajustar fase cero y fase uno con vista previa. Es el
método recomendado cuando la fase automática no representa correctamente señales
solapadas, débiles o afectadas por supresión.

La opción automática usa ACME. Puede partir de las fases almacenadas en la receta
Bruker y permite excluir regiones problemáticas. La exclusión sólo modifica la
señal usada por la optimización; no borra ni interpola los datos confirmados.
Aplica el resultado sólo después de revisar señales positivas, dispersivas y la
línea de base.

## Corregir línea de base

La corrección automática usa arPLS. Las regiones excluidas se sustituyen por un
puente únicamente durante el ajuste para impedir que una señal de supresión
deformada atraiga la línea de base. El espectro original se corrige con la línea
estimada y conserva sus puntos.

La corrección manual interpola una línea a partir de nodos elegidos por el
usuario. Selecciona puntos representativos de la base, evita señales y confirma
la vista previa antes de aplicar.

## Referenciar

Selecciona una señal conocida y abre **Procesado > Referenciado químico** o pulsa
`R`. El modo cursor usa exactamente la posición marcada; el modo máximo local
busca el máximo positivo dentro de una ventana. Introduce el desplazamiento
químico objetivo y revisa el eje resultante.

## Crear y administrar conjuntos

Selecciona al menos dos muestras y usa **Conjunto > Crear desde la selección**.
El modo superpuesto dibuja las trazas sobre el mismo origen; el modo apilado
asigna un carril fijo a cada espectro. En apilado, la ganancia cambia la altura de
las señales sin cambiar la separación de carriles.

Duplicar un conjunto crea una rama independiente de sus metadatos y conserva el
estado de las muestras referenciadas. Es útil para separar integración de
normalización y exportación sin repetir el procesado espectral.

## Zonas ciegas

Pulsa `X` y arrastra sobre el gráfico para definir intervalos que no deben
participar en normalización, integración total o determinados cálculos. Una zona
ciega no elimina datos. En la exportación espectral puede excluirse por completo
o conservarse con intensidades iguales a cero.

Las exclusiones de procesado de una muestra y las zonas ciegas de un conjunto
tienen propósitos diferentes: las primeras protegen correcciones de fase o línea
de base; las segundas forman parte del análisis del conjunto.

## Alinear espectros

La alineación global aplica un único corrimiento rígido por espectro y es útil
cuando el error es aproximadamente uniforme. La alineación automática divide el
dominio en intervalos y propone corrimientos mediante una implementación propia
basada en icoshift. La alineación manual es el método principal para ajuste fino:
arrastra regiones bien definidas, elige una referencia y revisa la vista previa.

Las plantillas de alineación guardan únicamente los intervalos. Permiten repetir
una selección tras reprocesar datos, pero no garantizan que la misma región sea
válida para otro experimento. Consulta [Alineación espectral](ALIGNMENT.md) para
los detalles técnicos.

## Normalizar

GIULI ofrece área total con signo, pico máximo y PQN. Las zonas ciegas se excluyen
del cálculo. El área total con signo requiere fase y línea de base adecuadas; si
la suma es nula, negativa o inestable, GIULI rechaza el cálculo.

PQN estima un factor de dilución relativo a un espectro de referencia mediano.
No corrige variaciones químicas específicas ni sustituye el control experimental.
Revisa siempre la coherencia de las muestras antes y después de normalizar.

## Integrar conjuntos

1. Selecciona un conjunto y pulsa `I`.
2. Arrastra cada región sobre el gráfico.
3. Usa **Editar tabla** para asignar nombres de metabolitos o señales.
4. Calcula las integrales y revisa las advertencias de interpolación.
5. Elige exportar valores absolutos o relativos.

La integral absoluta es la suma digital con signo de los puntos de la región. La
relativa es el cociente entre esa suma y la suma total válida del espectro. Las
regiones se conservan en el conjunto y también pueden guardarse como plantilla.
Los espectros con grillas distintas se interpolan sobre una grilla común y se
identifican en el resultado.

## Deconvolucionar señales solapadas

La deconvolución está disponible para conjuntos apilados. Selecciona una muestra
de referencia donde la geometría sea clara, arrastra una región, marca los
máximos y asigna cada componente a un compuesto. Si varias componentes pertenecen
al mismo compuesto, usa el mismo nombre y define sus proporciones cuando el
modelo lo requiera.

GIULI calibra centros y anchos en la referencia y ajusta el mismo modelo al
conjunto, permitiendo pequeños desplazamientos. Revisa R², RMSE, residuos,
advertencias y condición de identificabilidad. La ausencia de un hombro visible
no demuestra la ausencia de superposición; la asignación química sigue siendo
responsabilidad del usuario.

Para la exportación cuantitativa, el valor principal es el área observada de la
región repartida entre compuestos según el modelo. Los parámetros del ajuste son
diagnósticos y no sustituyen esa magnitud. No deben aceptarse silenciosamente
resultados marcados como no identificables.

## Exportar

**Archivo > Exportar** crea una matriz con ppm crecientes por fila y muestras por
columna en CSV o texto tabulado. Los programas estadísticos pueden transponerla
al importar. Si se conservan zonas ciegas, sus valores se escriben como cero.

La pantalla de integración exporta una fila por muestra y una columna por región
o compuesto. Los nombres editados se usan como encabezados. Conserva junto a la
tabla la versión de GIULI, el proyecto y las decisiones de procesado relevantes.

## Guardar proyectos y deshacer

Los proyectos `.giu` guardan el último estado confirmado, no una copia adicional
de los datos originales. El historial de deshacer y rehacer pertenece a la sesión
y se reinicia al abrir o guardar un proyecto. Para recuperar el origen después de
otra sesión, vuelve a cargar las FID.

Guarda plantillas de regiones por separado cuando quieras reutilizar selecciones.
Las plantillas de alineación y de integración son formatos distintos por diseño.

## Solución de problemas

**Una corrección automática no converge.** Excluye supresión o artefactos,
comprueba que exista componente imaginaria para fase y usa el método manual.

**La alineación automática mueve una señal incorrecta.** Reduce el desplazamiento
máximo, excluye regiones ambiguas y termina con alineación manual.

**La integral total es inestable.** Revisa fase, línea de base y zonas ciegas. No
normalices ni interpretes integrales antes de corregir la causa.

**OpenGL no mejora o falla.** Selecciona Raster. El rendimiento depende del
controlador, Qt y la cantidad de geometría visible; OpenGL no corrige por sí solo
un cuello de botella algorítmico.

**Un ajuste deconvolucionado no es identificable.** Reduce componentes, amplía la
región con base suficiente, elige una referencia mejor resuelta o no cuantifiques
esa región con ese modelo.

## Citación y soporte

Usa los metadatos de `CITATION.cff` y el DOI de la versión concreta. Los problemas
reproducibles pueden comunicarse en el sistema de incidencias del repositorio:
<https://github.com/EXCI5ION/giuli-nmr/issues>.
