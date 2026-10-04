# Alineación espectral en GIULI

## Relación con icoshift

El alineador estable que usa actualmente la interfaz de GIULI no importa ni ejecuta
ningún port Python de `icoshift`: es una implementación propia inspirada en el método
publicado por Savorani, Tomasi y Engelsen. En paralelo se está desarrollando un núcleo
independiente que reproduce explícitamente icoshift y que permanecerá separado hasta
completar su validación:

> Savorani F., Tomasi G., Engelsen S. B. (2010). *icoshift: A versatile tool
> for the rapid alignment of 1D NMR spectra*. Journal of Magnetic Resonance,
> 202(2), 190–202. <https://doi.org/10.1016/j.jmr.2009.11.012>

Ambos enfoques comparten estas ideas:

- desplazamiento rígido global o independiente por intervalos;
- maximización de correlación cruzada calculada mediante FFT;
- intervalos regulares o definidos por el usuario;
- prealineación global antes del ajuste local;
- objetivo real o sintético representativo del conjunto.

## Diferencias actuales

| Aspecto | icoshift publicado | GIULI actual |
| --- | --- | --- |
| Objetivo sintético | promedio, mediana, máximo por intervalo y `average2` | mediana antes y después de la prealineación |
| Máximo desplazamiento | valor fijo o búsqueda automática `fast`/`best` por intervalo | valor solicitado limitado por seguridad y contenido |
| Aplicación del corrimiento | inserción/eliminación; relleno con borde o `NaN` | interpolación subdigital y transición lineal en bordes |
| Resolución | corrimientos enteros en la implementación clásica | refinamiento parabólico a fracciones de punto |
| Cálculo | FFT simultánea sobre la matriz | correlación FFT por muestra e intervalo |
| Automatización adicional | segmentación regular y selección de objetivo | bordes en valles, rechazo por confianza y segunda pasada por multipletes |

Por eso no sería correcto presentar el motor actual como una copia exacta de
icoshift. GIULI ya añade controles útiles, pero todavía no explota dos propiedades
importantes del original: la selección de objetivo y la búsqueda del radio de
corrimiento por intervalo.

## Hipótesis para señales débiles y solapadas

La mediana es robusta ante espectros atípicos, pero puede ensanchar o atenuar señales
débiles que no coinciden todavía. En esos casos, un espectro real bien definido como
objetivo local (`max`) o un objetivo reconstruido en dos etapas (`average2`) puede
ofrecer una correlación más informativa.

Un máximo fijo demasiado pequeño deja el óptimo en el límite; uno demasiado grande
aumenta la posibilidad de emparejar el componente equivocado de un multiplete. Una
búsqueda `fast`/`best` por intervalo permitiría adaptar ese radio usando la forma de
la función de correlación, no solamente el ancho seguro de la región.

La correlación de intervalos, por sí sola, no identifica químicamente componentes
superpuestos. Cuando dos corrimientos distintos producen máximos similares debe
abstenerse o pedir intervención, en vez de forzar el de mayor correlación. El rechazo
por ambigüedad de GIULI debe conservarse incluso si se adopta más lógica de icoshift.

## Siguiente experimento recomendado

1. Implementar internamente objetivos candidatos `median`, `average2` y `max` por
   intervalo, sin añadir como dependencia el port Python existente.
2. Incorporar una búsqueda automática acotada del máximo desplazamiento por región,
   con modos rápido y exhaustivo.
3. Evaluar cada combinación sobre datos sintéticos y el conjunto NASH usando
   dispersión de posiciones, mejora de correlación, cambios de área, rechazos y
   aciertos en límites.
4. Mantener como ganador solamente un candidato que mejore las métricas sin aumentar
   el riesgo de bordes ni deformar el área.
5. Vectorizar después la FFT por bloques de muestras; es una optimización de tiempo y
   no debe mezclarse con la primera evaluación de calidad.

El objetivo del experimento no es sustituir inmediatamente el alineado aprobado, sino
comparar una nueva estrategia contra él y conservar el comportamiento actual como
alternativa estable mientras se valida.

## Estado de la implementación icoshift

El núcleo matricial independiente se encuentra en `nmr_processor.core.icoshift`. Esta
primera etapa ya implementa:

- objetivos `average`, `median`, `max` y `average2`; este último ejecuta la
  secuencia de dos pasadas del original (promedio, alineado preliminar y promedio
  reconstruido aplicado otra vez sobre la matriz de entrada);
- espectro completo, partición regular o intervalos explícitos;
- búsqueda FFT simultánea de desplazamientos enteros;
- máximo manual y búsquedas automáticas `fast` y `best`;
- prealineación global opcional;
- reconstrucción con `NaN`, cero o valor adyacente;
- salida explícita de intervalos, desplazamientos preliminares y finales, límites
  efectivos, objetivo empleado y desplazamientos globales.

El núcleo se conecta a la interfaz exclusivamente mediante el adaptador descrito más
abajo. El alineador histórico de GIULI permanece sin cambios y continúa disponible
como alternativa independiente.

Una primera prueba de rendimiento sobre la matriz común del proyecto NASH (18 ×
65.493 puntos, 100 intervalos, `average2` y búsqueda `best` limitada a 32 puntos)
demoró aproximadamente 3 segundos en el equipo de desarrollo. La presencia de 50
intervalos con algún óptimo en el límite confirmó que la integración debía conservar
el filtro de información y ambigüedad de GIULI.

## Adaptación al modelo de GIULI

`nmr_processor.core.icoshift_adapter` integra el núcleo sin alterar el alineador
existente. La capa:

- interpola los miembros sobre el tramo común de la malla ppm del primer espectro;
- ejecuta icoshift únicamente dentro de la ventana solicitada y conserva sin cambios
  el resto de esa malla común;
- aplica a la componente imaginaria exactamente los desplazamientos aceptados para
  la componente real;
- respeta las zonas ciegas persistentes del conjunto;
- contrasta cada desplazamiento entero propuesto con la correlación, prominencia y
  condición de límite que ya utiliza GIULI;
- registra por separado los desplazamientos propuestos y aplicados, junto con el
  motivo de cada rechazo.

Con NASH, una prueba preliminar sobre 0,2–10 ppm, 100 intervalos, `average2`, modo
`best` y límite de 0,01 ppm demoró aproximadamente 0,75 segundos. De 403 propuestas
no nulas se aceptaron 129 y se rechazaron 274. Estas cifras no constituyen todavía
una evaluación de exactitud: muestran que el filtro evita aplicar automáticamente
gran parte de las soluciones débiles, discordantes o situadas en el límite.

La reconstrucción adopta el intervalo ppm común a todos los miembros. Por tanto, los
pocos puntos extremos que no estén contenidos en todos los espectros quedan fuera
del resultado alineado; la vista previa lo indica expresamente antes de habilitar la
aplicación.

La opción `Procesamiento → Alineación icoshift del conjunto…` mantiene una sesión de
vista previa independiente. El objetivo recomendado es `average2`, la búsqueda
predeterminada es `best` y los parámetros técnicos permanecen plegados. El cálculo
se ejecuta fuera del hilo gráfico; `Cancelar` restaura el conjunto y `Aplicar` crea
una única operación reversible con método, ventana, intervalos y conteos de ajustes
aceptados y rechazados en el historial científico.
