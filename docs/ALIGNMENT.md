# Alineación espectral en GIULI

GIULI ofrece tres operaciones complementarias: alineación global, automática y
manual. La manual es el método principal para el ajuste fino supervisado; la
automática proporciona una propuesta reproducible que siempre debe revisarse en la
vista previa.

## Alineación automática

La única alineación automática visible utiliza la implementación matricial de
`nmr_processor.core.icoshift`, basada en el método de interval-correlation shifting:

> Savorani F., Tomasi G., Engelsen S. B. (2010). *icoshift: A versatile tool
> for the rapid alignment of 1D NMR spectra*. Journal of Magnetic Resonance,
> 202(2), 190–202. <https://doi.org/10.1016/j.jmr.2009.11.012>

La receta pública queda fijada en:

- objetivo sintético `average2`;
- búsqueda exhaustiva `best` del máximo desplazamiento por intervalo;
- 100 intervalos iniciales;
- límite de seguridad predeterminado de 0,01 ppm;
- exclusión de las zonas ciegas persistentes;
- rechazo de propuestas débiles, ambiguas o situadas en el límite.

Los ajustes avanzados permiten cambiar la ventana ppm, la cantidad de intervalos y
el límite máximo, pero no seleccionar algoritmos automáticos alternativos. El cálculo
se ejecuta fuera del hilo gráfico y no modifica el proyecto hasta pulsar `Aplicar`.

El núcleo calcula correlaciones por FFT sobre una matriz común y propone corrimientos
enteros independientes para cada intervalo. El adaptador
`nmr_processor.core.icoshift_adapter` interpola los miembros sobre una grilla común,
conserva fuera de la ventana los datos sin modificar, aplica a la componente
imaginaria los mismos desplazamientos aceptados y registra cada rechazo.

Esta es una reimplementación propia basada en el método publicado; no importa ni
ejecuta un port externo de icoshift. Por ello, la validación de GIULI debe documentar
por separado la recuperación de desplazamientos conocidos, la conservación de área
y forma, los rechazos por ambigüedad y el comportamiento sobre conjuntos reales.

## Alineación manual

El operador selecciona las regiones y el espectro de referencia. Para cada región,
GIULI calcula la correlación cruzada mediante FFT, refina el máximo con interpolación
parabólica hasta una fracción de punto y aplica el corrimiento mediante interpolación.
Una transición lineal mezcla los bordes con la señal original para evitar
discontinuidades. La misma transformación se aplica a la componente imaginaria.

El método comparte con icoshift la alineación por correlación de intervalos, pero no
es icoshift: las regiones son supervisadas, la referencia es un espectro elegido por
el usuario y los desplazamientos pueden ser subdigitales.

## Alineación global

La alineación global estima un único corrimiento rígido por espectro contra una
referencia. Es apropiada cuando el desplazamiento afecta de manera aproximadamente
uniforme a todo el espectro y puede utilizarse antes del ajuste manual.
