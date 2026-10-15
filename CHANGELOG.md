# Historial de cambios

Todos los cambios importantes de GIULI se documentarán en este archivo a partir de
su primera versión pública.


## 1.0.2 - 2026-10-15

- El zoom horizontal se conserva al aplicar alineaciones para facilitar la
  evaluación inmediata del resultado en la región de interés.
- La creación gráfica de regiones se unifica mediante clic y arrastre en la
  alineación manual, la integración y las zonas ciegas.
- Los paneles de alineación manual, integración y zonas ciegas se simplifican al
  retirar controles redundantes y dedicar más espacio al set de espectros.
- La tabla editable de regiones o metabolitos se traslada a una ventana flotante
  no modal y conserva los nombres al añadir o ajustar regiones.
- El selector de visualización apilada o superpuesta se oculta mientras una
  herramienta de alineación está activa.
- Se retira la confirmación repetitiva al realinear un conjunto; cada operación
  continúa registrada en el historial y disponible mediante Deshacer.

## 1.0.1 - 2026-10-13

- Se toma `SI` directamente de la receta de procesado Bruker, sin solicitarlo
  durante la importación.
- La exportación de integrales permite elegir valores relativos o absolutos y
  utilizar nombres editables de regiones o metabolitos.
- Las zonas ciegas pueden crearse mediante clic y arrastre sobre el espectro.
- Las regiones de alineación manual, integración y zonas ciegas pueden
  seleccionarse y eliminarse con `Del` sin borrar el espectro o conjunto activo.

## 1.0.0 - 2026-10-04

Primera versión estable de GIULI.

- Importación y reconstrucción de espectros desde FID Bruker 1D usando la receta
  compatible guardada en `pdata/<procno>/procs`.
- Corrección automática y manual de fase y línea de base, con zonas excluidas para
  señales problemáticas sin borrar los datos originales.
- Referenciado químico, normalización por área total, pico máximo y PQN, y zonas
  ciegas persistentes.
- Alineación global, automática, manual por regiones e implementación independiente
  de icoshift con vista previa y aplicación reversible.
- Visualización individual, superpuesta y apilada, con carriles fijos, navegación
  espectral, zoom horizontal, crosshair y renderer OpenGL o raster seleccionable.
- Integración regional de conjuntos para análisis estadístico y plantillas JSON
  reutilizables de regiones de integración y alineación.
- Duplicación de conjuntos y exportación CSV/TXT de matrices espectrales e integrales.
- Proyectos `.giu` versionados y comprimidos que conservan el último estado
  científico sin duplicar los datos originales.
- Empaquetado reproducible para Windows mediante PyInstaller e Inno Setup, incluida
  la validación de Qt/PySide6 y la protección frente a DLL ICU incompatibles.
