# GIULI

Aplicación abierta para el procesamiento interactivo y reproducible de espectros de RMN,
inicialmente orientada a experimentos Bruker 1D de protón para metabolómica.

Versión actual: **1.0.0**.

## Desarrollo

GIULI requiere Python 3.12. En PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m nmr_processor.app
```

La instalación también crea el comando `giuli`.

## Empaquetado para Windows

El empaquetado reproducible requiere Python 3.12, PySide6 6.11.2,
PyInstaller 6.22.2 e Inno Setup 7. Desde PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"
.\packaging\windows\build_release.ps1 -InstallerVersion 1.0.0
```

El script limita temporalmente el `PATH` antes de invocar PyInstaller, descarta
cualquier `icuuc.dll` o `icudt*.dll` encontrada fuera de PySide6 y comprueba el
ejecutable resultante. Después compila el instalador, lo instala en una carpeta
aislada, confirma la carga de `QtCore.pyd`, `QtWidgets.pyd` y las ICU de Windows,
y desinstala esa copia de prueba. Los artefactos quedan en `dist/` y
`dist-installer/`, que no se versionan.

En Windows, GIULI intenta utilizar OpenGL para acelerar el visor y vuelve al
renderer raster si Qt no puede crear un contexto válido. El renderer también se
puede elegir explícitamente antes de iniciar la aplicación:

```powershell
$env:GIULI_RENDERER = "opengl"  # Fuerza OpenGL
$env:GIULI_RENDERER = "raster"  # Desactiva la aceleración
```

El motor también puede cambiarse durante la sesión desde
`Ver → Motor gráfico`. La barra de estado indica si el visor utiliza efectivamente
un contexto OpenGL válido o el renderer raster de CPU; si OpenGL falla, GIULI cambia
automáticamente a raster y actualiza el indicador.

## Navegación espectral

El lienzo horizontal está limitado al dominio ppm disponible: no admite desplazarse
fuera de los datos ni reducir el zoom más allá del espectro completo. La rueda del
ratón controla exclusivamente la ganancia vertical; los arrastres desplazan o amplían
el eje horizontal. El modo opcional `Ver → Zoom` (atajo `Z`)
permite ampliar el intervalo ppm seleccionado con el botón izquierdo. En modo
apilado, las líneas base se distribuyen de forma uniforme y
permanecen fijas mientras cambia la intensidad, incluso para conjuntos grandes. En la
vista de una muestra individual también se puede arrastrar el eje Y para centrar el
espectro verticalmente; esta acción se deshabilita en conjuntos superpuestos o apilados.
`F` restablece la vista completa sin alterar los carriles apilados.
El `Crosshair` conmutable de `Ver → Crosshair` (atajo `C`) permite seguir una
misma coordenada horizontal y vertical al revisar alineación o línea de base. El color
del espectro individual, el grosor común de las curvas y el color, grosor y opacidad
de la cruz se conservan desde
`Ver → Apariencia del espectro…`.

La importación Bruker trabaja exclusivamente desde FID. La búsqueda localiza carpetas
que contienen `fid` y `acqus`; si existe un `procs` asociado, sus parámetros pueden
servir como valores de procesamiento sin importar los datos `1r/1i`. Antes de procesar,
GIULI permite conservar automáticamente el `SI` de `procs` o elegir el número de puntos
de la transformada. Reducir, por ejemplo, de 128k a 64k disminuye memoria y trabajo
posterior; no recupera ni elimina información adquirida mientras el valor siga siendo
igual o mayor que el número de puntos complejos de la FID. Todo conjunto comparable
debe procesarse con el mismo `SI`: una suma digital absoluta depende del número de
puntos, aunque las proporciones integrales se conserven.

Cuando existe `pdata/<procno>/procs`, GIULI mantiene la FID como fuente y utiliza esa
receta para reproducir el estado de TopSpin: ventana `NO`, `EM`, `GM`, `SINE` o
`QSINE`, tamaño `SI`, fase lineal `PHC0/PHC1`, inversión indicada y eje calibrado por
`SF`, `OFFSET` y `SW_p`. No se lee `1r` como señal de trabajo. La fase Bruker se
convierte a la convención de la FFT de GIULI; por eso ACME calcula después solamente
una corrección residual opcional. Las ventanas menos habituales se rechazan de forma
explícita antes que sustituirlas silenciosamente por otra transformación.

## Alineación

El menú `Procesamiento` conserva por separado la alineación global, la automática de
GIULI, la manual y la implementación independiente de icoshift. La alineación manual
permite delimitar señales arrastrando sobre el gráfico o mediante dos clics, además de
crear una región desde la vista actual. Estima corrimientos subpunto, aísla la señal
elegida dentro de un contexto local y mezcla los bordes para no crear discontinuidades.
La implementación de icoshift ofrece objetivos `average2`, mediana, máximo y
promedio, junto con búsquedas
`best` o `fast`. Su vista previa se calcula en segundo plano, rechaza propuestas no
confiables y no modifica el proyecto hasta pulsar `Aplicar`.
Como alternativa experimental, el modo adaptativo prueba varias cantidades de
intervalos y los objetivos `average2` y mediana; elige la propuesta con mejor
correlación penalizando rechazos y variaciones bruscas entre intervalos. La corrección
de fase automática conserva el criterio ACME, pero calcula sus parámetros sobre una
copia reducida y aplica el resultado al espectro completo. En una muestra individual,
`Procesamiento → Zonas ciegas…` permite guardar regiones ignoradas solo durante ACME
y arPLS; no se eliminan de integración, normalización ni exportación. Si se procesa un
conjunto, sus zonas ciegas y las máscaras individuales de sus miembros se ignoran
durante ACME para que señales residuales fuera de fase, como agua suprimida, no
gobiernen la optimización.

La línea de base automática aplica la misma regla: las regiones excluidas se reemplazan
por un puente neutro únicamente durante el ajuste arPLS. La línea calculada se resta
después del espectro original, por lo que los datos dentro de esas regiones no se
borran ni se sustituyen.

## Integración y normalización

`Análisis → Integrar…` (`I`) permite definir
regiones arrastrando sobre el lienzo o mediante dos clics. Mientras ese selector está
activo, el lienzo no se desplaza accidentalmente; los ejes siguen disponibles para
navegar. GIULI calcula sumas digitales con signo, valores absolutos y proporciones
respecto a la suma total válida. Las regiones calculadas se guardan en el conjunto.
Las pantallas de integración y alineación manual permiten guardar y cargar sus propias
plantillas JSON por separado. Las coordenadas se expresan en ppm, por lo que pueden
reutilizarse después de reprocesar una serie con otro `SI`; GIULI rechaza plantillas del
otro tipo, regiones solapadas o límites fuera del dominio común.

La normalización del conjunto ofrece suma total con signo, pico máximo y PQN. Las zonas ciegas se
excluyen de todos los estimadores y también pueden escribirse numéricamente. Duplicar
un conjunto (`Ctrl+D`) conserva modo de vista, normalización, zonas ciegas y regiones
de integración, de modo que se puedan separar las ramas de análisis y exportación.

## Formato de proyecto

Los archivos `.giu` son contenedores ZIP versionados con un manifiesto JSON y
arreglos NumPy, sin serialización mediante `pickle`. Conservan el último estado
científico guardado y el historial de procesamiento confirmado, pero no duplican los
datos importados. Para recuperar el estado de adquisición se vuelven a importar las
FID. El historial operativo de deshacer/rehacer pertenece solo a la sesión y se limpia
al guardar o abrir un proyecto. La extensión admitida es
exclusivamente `.giu`. Desde el formato v5, los bytes de cada matriz se reordenan de
forma reversible antes de comprimir: se mantiene exactamente la precisión original y
los proyectos anteriores se compactan automáticamente al volver a guardarlos.

## Exportación estadística

Con un conjunto espectral activo, `Archivo → Exportar…`
genera una matriz CSV o TXT tabulada. Cada fila es un punto ppm y cada columna una
muestra, ordenadas de menor a mayor ppm; esta orientación mantiene angostas las
tablas de conjuntos grandes. Se aplican los factores de normalización del conjunto,
nunca los
desplazamientos verticales usados sólo para visualizar el apilado, y se puede elegir
si eliminar las filas de sus zonas ciegas. Si se conservan, las intensidades de esas
filas se escriben como cero para no reincorporar el área excluida de la normalización.
Cuando los ejes no coinciden, se usa el intervalo ppm común y la interfaz informa
cuántos espectros debieron interpolarse. La exportación aplica exactamente los
factores guardados y no sustituye el método elegido por una renormalización implícita.

## Cómo citar

Los metadatos de citación de GIULI se encuentran en [`CITATION.cff`](CITATION.cff).
GitHub permite obtener desde ese archivo una referencia en formatos APA y BibTeX.
Cuando el repositorio sea público, las nuevas versiones se archivarán en Zenodo y
recibirán un DOI; el DOI conceptual se añadirá aquí después del primer depósito.

## Licencia

Copyright (C) 2026 Gabriel Anderson.

GIULI es software libre distribuido exclusivamente bajo la
[GNU General Public License, versión 3](LICENSE) (`GPL-3.0-only`). Los componentes
de terceros conservan sus propias licencias; véase
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
