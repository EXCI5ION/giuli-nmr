# Manual de usuario GIULI

Versión **1.1.0**

Autor: Gabriel Anderson

## 1. Introducción

### 1.1. Propósito y alcance

GIULI es una aplicación de escritorio para procesar y analizar espectros de RMN
1D. Su flujo de trabajo actual está orientado a experimentos Bruker y al análisis
de conjuntos utilizados en metabolómica. Este manual describe cómo obtener
resultados reproducibles desde la carga de las FID hasta la exportación de
matrices para análisis estadístico.

GIULI es un programa completamente gratuito y de código abierto distribuido bajo
la licencia GPL-3.0. Su propósito es ofrecer una alternativa libre para el
trabajo científico y académico, adaptada a las necesidades del usuario y sin
dependencia de licencias de software propietario de alto costo.

### 1.2. Organización de la interfaz

La lista izquierda contiene muestras y conjuntos. El área central muestra el
espectro. El panel inferior o lateral aparece solo durante operaciones que
requieren parámetros o una vista previa. Las acciones se agrupan en **Archivo**,
**Editar**, **Ver**, **Procesado**, **Conjunto**, **Análisis** y **Ayuda**.

Una muestra representa un espectro. Un conjunto referencia varias muestras sin
duplicar sus arreglos y conserva propiedades comunes como modo de visualización,
zonas ciegas, factores de normalización y regiones de integración.

## 2. Instalación

### 2.1. Windows

En sistemas con arquitectura x64, descarga el instalador desde la
[página de la versión publicada](https://github.com/EXCI5ION/giuli-nmr/releases/latest)
y sigue el asistente. El ejecutable incluye Python y las dependencias necesarias.

Como alternativa, en Windows x64 y ARM64 puedes usar el instalador por consola
con Python 3.12 o 3.13 para la arquitectura correspondiente:

```powershell
Invoke-WebRequest `
  https://github.com/EXCI5ION/giuli-nmr/releases/latest/download/install_windows.py `
  -OutFile "$env:TEMP\install_windows.py"
py -3.13 "$env:TEMP\install_windows.py"
```

El instalador descarga la última versión estable sin requerir Git, crea un
entorno aislado por usuario y añade accesos directos. Tras abrir una terminal
nueva quedan disponibles:

```text
giuli
giuli-update
giuli-uninstall
```

### 2.2. Linux en Debian, Ubuntu y derivados

Con Git y Python 3.12 o 3.13 disponibles:

```bash
git clone https://github.com/EXCI5ION/giuli-nmr.git
cd giuli-nmr
python3 packaging/linux/install_linux.py
giuli
```

El instalador crea un entorno aislado y añade los comandos `giuli` y
`giuli-update`. También puedes realizar una instalación local siguiendo las
instrucciones del README.

### 2.3. macOS

El instalador admite macOS 13 o posterior en equipos Intel y Apple Silicon.
Requiere una cuenta administradora, Git, Python 3 y las herramientas de línea de
comandos de Apple. Si estas no están instaladas, puedes obtenerlas con:

```bash
xcode-select --install
```

Para instalar GIULI:

```bash
git clone https://github.com/EXCI5ION/giuli-nmr.git
cd giuli-nmr
python3 packaging/macos/install_macos.py
```

El instalador detecta la arquitectura, rechaza procesos traducidos mediante
Rosetta, instala un Python 3.12 privado y crea
`/Applications/GIULI.app`. También añade:

```text
giuli
sudo giuli-update
sudo giuli-uninstall
```

## 3. Carga y visualización de datos

### 3.1. Carga de datos Bruker

1. Selecciona **Archivo > Cargar datos**.
2. Elige una carpeta que contenga experimentos Bruker.
3. Revisa los experimentos detectados y confirma la carga.
4. Comprueba fase, rango ppm, intensidad y nombre de cada muestra.

GIULI reconstruye los espectros desde la FID y usa la receta compatible hallada
en `pdata/<procno>/procs`. Antes de la transformada de Fourier aplica la
función de apodización indicada por `WDW` con sus parámetros asociados, como
`LB` y, cuando corresponde, `GB` o `SSB`. Si `WDW` indica que no debe
usarse una ventana, la FID no se apodiza. A continuación realiza el *zero
filling* según el número de puntos `SI` especificado en la misma receta.

### 3.2. Navegación y visualización

La rueda del ratón modifica la ganancia vertical y, por tanto, la intensidad
visible de los espectros. Los controles de navegación son:

- **Shift + rueda:** desplaza horizontalmente el intervalo ppm. También puedes
  navegar arrastrando directamente ese eje.
- **Ctrl + rueda:** realiza zoom horizontal.
- **Alt + rueda:** desplaza verticalmente la vista para recorrer el eje de
  intensidad. También puedes arrastrar ese eje para centrar el espectro.
- **Z:** activa el zoom rectangular. En espectros individuales y superpuestos,
  la selección modifica los ejes horizontal y vertical. La herramienta se
  deshabilita en espectros apilados.
- **F:** muestra el dominio completo respetando la geometría del modo actual.
- **C:** activa y desactiva el *crosshair* para comparar posiciones e
  intensidades.

El desplazamiento vertical se deshabilita en la vista apilada para conservar los
carriles fijos.

Las principales opciones de visualización son:

- **Ver > Apariencia > Espectro:** modifica el color y el grosor de las trazas.
- **Ver > Apariencia > Crosshair:** ajusta el estilo del indicador.
- **Ver > Apariencia > Tema:** alterna entre la interfaz moderna y la clásica.
- **Ver > Motor gráfico:** permite escoger OpenGL o raster. El indicador de
  estado informa el motor que Qt pudo activar realmente.

## 4. Procesado de espectros

### 4.1. Corrección de fase

La opción automática usa el algoritmo
[ACME](https://doi.org/10.1016/S1090-7807(02)00069-1) y puede partir de las fases
almacenadas en la receta Bruker. Para activarla, presiona **P**. Si el resultado
no es óptimo, puedes deshacer el cambio con **Ctrl + Z**.

La corrección manual permite ajustar fase cero y fase uno con vista previa. Es el
método recomendado cuando la fase automática no representa correctamente las
señales.

Para corregir la fase manualmente:

1. Ve a **Procesado > Corrección de fase > Manual...**.
2. Selecciona el desplazamiento de la señal que utilizarás como pivote.
3. Mueve los controles correspondientes para corregir la fase de orden cero
   (`PH0`) y de primer orden (`PH1`).
4. Cuando el resultado sea satisfactorio, presiona **Aplicar**.

En ambos casos se pueden excluir regiones problemáticas. La exclusión solo
modifica la señal usada por la optimización; no borra ni interpola los datos
confirmados. Para excluir una región, presiona **X**, arrastra sobre el intervalo
que deseas omitir y confirma la selección.

### 4.2. Corrección de línea de base

La corrección automática usa
[arPLS](https://doi.org/10.1039/C4AN01061B). Las regiones excluidas se sustituyen
por un puente únicamente durante el ajuste para impedir que una señal de
supresión deformada atraiga la línea de base.

Para aplicarla:

1. Presiona **B**.
2. Selecciona con el deslizador o un botón de selección rápida el valor de
   \(\lambda\).
3. Evalúa en tiempo real la línea de corrección dibujada sobre el espectro.
4. Cuando el resultado sea satisfactorio, presiona **Aplicar**.

Para excluir una región, presiona **X**, arrastra sobre el intervalo que deseas
omitir y confirma la selección.

La corrección manual interpola una línea a partir de nodos elegidos por el
usuario. Ve a **Procesado > Corrección de línea de base > Manual...**, selecciona
puntos representativos de la base, evita las señales y confirma la operación con
**Aplicar**.

### 4.3. Referenciado químico

Para activar el referenciado, pulsa **R** o abre
**Procesado > Referenciado químico**. Selecciona una señal conocida e introduce
el desplazamiento químico objetivo. El modo cursor usa exactamente la posición
marcada; el modo máximo local busca el máximo positivo dentro de una ventana.

## 5. Conjuntos

### 5.1. Crear y administrar conjuntos

Selecciona al menos dos muestras y ve a
**Conjunto > Crear desde la selección**. Define el nombre del conjunto y confirma
la selección. Deberás elegir entre los modos **Superpuestos** y **Apilados**.

El modo superpuesto dibuja las trazas sobre el mismo origen y el modo apilado
asigna un carril fijo a cada espectro. Ambos comparten los atajos de navegación y
zoom. En el modo apilado se desactivan **Alt + rueda** y **Z** para evitar
conflictos con la geometría de los carriles.

Puedes duplicar un conjunto para crear una rama independiente de sus metadatos.
Las regiones, zonas ciegas y opciones de normalización de la copia pueden
modificarse sin alterar el conjunto original.

> **Observación:** el estado de los conjuntos es dinámico. Las operaciones
> realizadas sobre los espectros individuales se reflejan en el conjunto. Si
> algún espectro contiene un error de fase, línea de base o referenciado, puedes
> corregir la muestra individual y el cambio aparecerá también en el conjunto
> apilado o superpuesto.

### 5.2. Zonas ciegas

Para definir zonas ciegas en un conjunto, pulsa **X** y arrastra sobre el gráfico.
Estos intervalos no participan en la normalización, la integración total ni otros
cálculos del conjunto. Una zona ciega no elimina datos: en la exportación
espectral puede excluirse por completo o conservarse con intensidades iguales a
cero.

También puedes presionar **X**, seleccionar **Ingresar valores**, definir los
límites superior e inferior y confirmar con **Aplicar**.

> **Observación:** las exclusiones de procesado de una muestra y las zonas
> ciegas de un conjunto tienen propósitos diferentes. Las primeras protegen
> correcciones de fase o línea de base; las segundas forman parte del análisis
> del conjunto.

### 5.3. Alineado de espectros

GIULI presenta tres métodos: **Alineación global**, **Alineación automática** y
**Alineación manual**.

#### Alineación global

Aplica un único corrimiento rígido por espectro y es útil cuando el error es
aproximadamente uniforme.

1. Ve a **Procesado > Alineación global...**.
2. Selecciona el espectro de referencia.
3. Define los límites del intervalo y el desplazamiento máximo.
4. Presiona **Calcular vista previa**.
5. Revisa los desplazamientos y las correlaciones calculados.
6. Si el resultado es satisfactorio, presiona **Aplicar**.

#### Alineación automática

Divide el dominio en intervalos y propone corrimientos mediante una
implementación propia basada en
[icoshift](https://doi.org/10.1016/j.jmr.2009.11.012).

1. Ve a **Procesado > Alineación automática...**.
2. Presiona **Calcular vista previa** para usar los parámetros predeterminados.
3. Si necesitas mayor control, abre **Mostrar ajustes avanzados** y define los
   límites de la ventana, los intervalos y el desplazamiento máximo.
4. Vuelve a calcular la vista previa.
5. Si el resultado es satisfactorio, presiona **Aplicar**.

#### Alineación manual

Es el método principal para el ajuste fino.

1. Ve a **Procesado > Alineación manual...**.
2. Selecciona el espectro de referencia.
3. Arrastra para definir las regiones que deseas alinear.
4. Presiona **Calcular vista previa** y evalúa el resultado.
5. Si el resultado es satisfactorio, presiona **Aplicar**.

Si existen regiones conflictivas, puedes trabajar primero con un grupo pequeño,
aplicar el alineado y continuar después con otras regiones o con otro espectro de
referencia. Las regiones previamente aplicadas no se ven afectadas por el cambio
de referencia.

Puedes guardar y cargar las regiones mediante los botones del panel inferior.
Consulta la [documentación de alineación espectral](ALIGNMENT.md) para conocer
los detalles técnicos.

### 5.4. Normalizado

GIULI ofrece tres métodos de normalización: **Área total**, **Pico máximo** y
**PQN**. Las zonas ciegas se excluyen del cálculo.

#### Área total

Conserva el signo y requiere fase y línea de base adecuadas. Si la suma es nula,
negativa o inestable, GIULI rechaza el cálculo.

Selecciona el conjunto, presiona **N** o ve a **Procesado > Normalizar**, elige
**Área total**, ingresa el valor objetivo y confirma la operación.

#### Pico máximo

Calcula, para cada espectro, la mayor intensidad positiva situada fuera de las
zonas ciegas y aplica un factor para llevarla al valor objetivo. Este método
presupone que el pico de mayor intensidad es comparable entre todas las muestras;
las señales atípicas o saturadas pueden producir factores poco representativos.
Si un espectro no contiene un máximo positivo y finito, GIULI rechaza el cálculo.

Selecciona el conjunto, presiona **N** o ve a **Procesado > Normalizar**, elige
**Pico máximo**, ingresa la intensidad máxima objetivo y confirma la operación.

#### PQN

PQN estima un factor de dilución relativo a un espectro de referencia mediano. No
corrige variaciones químicas específicas ni sustituye el control experimental.

Selecciona el conjunto, presiona **N** o ve a **Procesado > Normalizar**, elige
**PQN (cociente probabilístico)** y confirma la operación.

### 5.5. Exportado

Para exportar el conjunto de datos y utilizarlo en análisis estadísticos,
selecciona un conjunto y ve a **Archivo > Exportar**. GIULI crea una matriz con
valores ppm crecientes por fila y muestras por columna, en formato CSV o texto
tabulado. Si se conservan las zonas ciegas, sus valores se escriben como cero.

## 6. Integración y deconvolución

### 6.1. Integración en conjuntos

1. Selecciona un conjunto y pulsa **I** o ve a **Análisis > Integrar**.
2. Arrastra cada región sobre el gráfico.
3. Usa **Editar tabla** para asignar nombres de metabolitos o señales.
4. Calcula las integrales con **Calcular** y revisa las advertencias de
   interpolación.
5. Elige si deseas exportar valores absolutos o relativos.
6. Presiona **Exportar** para asignar la ubicación y el nombre del archivo.

La integral absoluta es la suma digital con signo de los puntos de la región. La
integral relativa es el cociente entre esa suma y la suma total válida del
espectro.

La pantalla de integración exporta una fila por muestra y una columna por región
o compuesto. Los nombres editados se usan como encabezados.

Las regiones pueden guardarse y cargarse mediante los botones del panel inferior.
Los espectros con grillas distintas se interpolan sobre una grilla común y se
identifican en el resultado.

### 6.2. Deconvolución de señales solapadas

La deconvolución está disponible para conjuntos apilados.

Selecciona una muestra de referencia donde la geometría sea clara, arrastra una
región, marca los máximos y asigna cada componente a un compuesto. Si varias
componentes pertenecen al mismo compuesto, usa el mismo nombre y define sus
proporciones cuando el modelo lo requiera.

Puedes elegir entre los modelos **Pseudo-Voigt** y **Lorentziana**.

GIULI calibra centros y anchos en la referencia y ajusta el mismo modelo al
conjunto, permitiendo pequeños desplazamientos. Revisa R², RMSE, residuos,
advertencias y condición de identificabilidad. La ausencia de un hombro visible
no demuestra la ausencia de superposición; la asignación química sigue sujeta al
criterio del usuario.

Para la exportación cuantitativa, el valor principal es el área observada de la
región repartida entre compuestos según el modelo. Los parámetros del ajuste son
diagnósticos y no sustituyen esa magnitud. No deben aceptarse silenciosamente
resultados marcados como no identificables.

## 7. Proyectos y recuperación del trabajo

### 7.1. Guardar proyectos y deshacer

Los proyectos `.giu` guardan el último estado confirmado, no una copia adicional
de los datos originales. El historial de **deshacer** y **rehacer** pertenece a
la sesión y se reinicia al abrir o guardar un proyecto. Para recuperar el origen
después de otra sesión, vuelve a cargar las FID.

- **Ctrl + S** o **Archivo > Guardar proyecto:** guarda el proyecto actual.
- **Ctrl + Shift + S** o **Archivo > Guardar proyecto como...:** permite elegir
  otra ubicación o nombre.
- **Ctrl + O** o **Archivo > Abrir proyecto...:** abre un archivo `.giu`.

## 8. Solución de problemas y soporte

### 8.1. Solución de problemas

#### Una corrección automática no converge

Excluye supresión o artefactos, comprueba que exista componente imaginaria para
fase y usa el método manual.

#### La alineación automática mueve una señal incorrecta

Reduce el desplazamiento máximo, excluye regiones ambiguas y termina con
alineación manual.

#### La integral total es inestable

Revisa fase, línea de base y zonas ciegas. No normalices ni interpretes integrales
antes de corregir la causa.

#### OpenGL no mejora o falla

Selecciona **Raster**. El rendimiento depende del controlador, Qt y la cantidad
de geometría visible; OpenGL no corrige por sí solo un cuello de botella
algorítmico.

#### Un ajuste deconvolucionado no es identificable

Reduce componentes, amplía la región con base suficiente, elige una referencia
mejor resuelta o no cuantifiques esa región con ese modelo.

### 8.2. Citación y soporte

Usa los metadatos de `CITATION.cff` y el DOI de la versión concreta. Los
problemas reproducibles pueden comunicarse en la
[sección Issues del repositorio](https://github.com/EXCI5ION/giuli-nmr/issues).

## Bibliografía

1. L. Chen, Z. Weng, L. Goh y M. Garland, “An efficient algorithm for automatic
   phase correction of NMR spectra based on entropy minimization”, *Journal of
   Magnetic Resonance*, vol. 158, pp. 164-168, 2002.
   [doi:10.1016/S1090-7807(02)00069-1](https://doi.org/10.1016/S1090-7807(02)00069-1).
2. S.-J. Baek, A. Park, Y.-J. Ahn y J. Choo, “Baseline correction using
   asymmetrically reweighted penalized least squares smoothing”, *Analyst*,
   vol. 140, pp. 250-257, 2015.
   [doi:10.1039/C4AN01061B](https://doi.org/10.1039/C4AN01061B).
3. F. Savorani, G. Tomasi y S. B. Engelsen, “icoshift: A versatile tool for the
   rapid alignment of 1D NMR spectra”, *Journal of Magnetic Resonance*, vol. 202,
   pp. 190-202, 2010.
   [doi:10.1016/j.jmr.2009.11.012](https://doi.org/10.1016/j.jmr.2009.11.012).
