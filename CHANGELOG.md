# Historial de cambios

Todos los cambios importantes de GIULI se documentarán en este archivo a partir de
su primera versión pública.

## Sin publicar

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
