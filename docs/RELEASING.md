# Publicación de versiones

## Integración con Zenodo

Zenodo no puede acceder al repositorio mientras sea privado. Después de hacerlo
público, la integración requiere una única configuración manual:

1. Iniciar sesión en Zenodo mediante GitHub.
2. Abrir la sección de GitHub en Zenodo y usar **Sync now** si el repositorio no
   aparece todavía.
3. Activar `EXCI5ION/giuli-nmr` en la lista de repositorios.
4. Revisar que `CITATION.cff` contenga la versión, autores y afiliaciones correctos.
5. Publicar una nueva GitHub Release con un tag nuevo. Zenodo archivará esa versión
   y acuñará automáticamente su DOI.
6. Añadir a `CITATION.cff` y al `README.md` el DOI conceptual que Zenodo asigne al
   proyecto. Ese DOI representa todas las versiones; cada depósito conserva además
   su DOI específico.

No se debe mover ni volver a crear un tag ya publicado. La primera versión depositada
automáticamente será una versión posterior a `v1.0.0`, una vez que el repositorio sea
público y esté habilitado en Zenodo.

No se necesita un GitHub Action para este flujo: la integración oficial recibe el
evento de cada nueva GitHub Release.

## Comprobaciones de metadatos

Antes de publicar una versión:

- actualizar la versión y la fecha en `CITATION.cff`;
- actualizar la versión en `pyproject.toml` y los metadatos del instalador;
- confirmar que `LICENSE`, `CITATION.cff` y `THIRD_PARTY_NOTICES.md` se incluyen en
  el instalador;
- ejecutar las pruebas y la validación completa del instalador;
- publicar la GitHub Release sólo después de que los artefactos hayan sido validados.
