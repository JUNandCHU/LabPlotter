# Changelog

## 0.7.1 — 2026-07-22

- Added all-series and per-particle color controls to every ZetaSizer distribution and batch graph.
- Applied a particle's selected color consistently to replicates, means, SD fills, peak labels, and bars.
- Persisted the main ZetaSizer selection-list and particle-library column widths in the external user settings file.
- Preserved saved column layouts and ZetaSizer colors across restarts, upgrades, and rollbacks.

## 0.7.0 — 2026-07-22

- Split the ZetaSizer plot collection from a separate resizable, detailed particle-library window.
- Added automatic local OCR during workbook import with auto/reviewed/failed status tracking and editable review tabs.
- Added a four-panel DLS, zeta, batch Z-average, and batch average-zeta dashboard.
- Added editable automatic `JM` batch labels, mean/median summaries, and SD/SEM error bars.
- Added automatic maximum-intensity/count labels with single- and multi-particle controls and annotation-aware export.
- Ensured result-table review controls remain visible at the default window size.
- Added a one-time, rollback-safe ZetaSizer database reset for the 0.7.0 patch.
- Added storage-summary and updater database-reset/rollback tests.

## 0.6.0 — 2026-07-18

- Added format-2 cumulative snapshot patches that overwrite the complete managed target inventory while preserving unknown local files.
- Added version-independent backup, dependency reconciliation, smoke validation, and rollback for cumulative updates, including recognized legacy folders without `version.json`.
- Added `update_to_latest.bat` as a legacy bootstrap path that downloads the current updater and latest cumulative patch from GitHub.
- Kept format-1 incremental patch compatibility.
- Added multi-version cumulative update and rollback tests.

## 0.5.1 — 2026-07-15

- Moved Lines and Shapes to a direct graph action and enlarged its table.
- Added per-tab graph-setting default restoration.
- Added local RapidOCR review tabs for embedded ZetaSizer result tables.
- Added side-by-side source-image review, editable OCR cells, confidence highlighting, and explicit confirmation before library storage.
- Added reviewed-OCR counts and sorting to the particle library.
- Added English/Korean translations for the new interface.
- Verified update, rollback, reapply, OCR, and database integration.
