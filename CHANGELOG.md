# Changelog

## 0.9.1 — 2026-09-21

- Moved the Lab DLS data list to the left and added per-measurement Hide/Exclude checkboxes. Exclusion immediately recomputes included counts, arithmetic averages, representative distributions and overlays without changing raw data. Saved libraries retain both flags and read older entries.
- Added quick mean-label/mean-line toggles, label-position reset buttons and a selected-particle average-distribution mode below the graphs.
- Collapsed overlay results into one average row per particle, with +/− expansion for measurements and excluded-row indicators. Kept font-metric row heights and scrollbars.
- Added a Legend visibility control to every desktop plot toolbar. Click a legend to unlock editing, drag inside to move or corners to resize/reflow, then click outside or Esc to finish. Saved/copied images omit editing handles and retain layout.
- Updated the web companion with the left data list, measurement controls, quick annotations, average mode and collapsed overlay details.

## 0.9.0 — 2026-09-20

- Added an independent Lab DLS tab for sparse Radius/Meas CSV distributions, with filename-based particle names, a right-side data list and two left-side plots. Kept the existing ZetaSizer workflow.
- Applied the supplied PDF defaults: radius 0.01–1,000,000 nm on a log axis, intensity 0–20%, raw connected measurement points. Added full-height Y fitting for taller peaks.
- Added an independent persistent Lab DLS library with save, rename, load, delete and reorder, plus explicit overlay registration/removal, equal-weight log-grid representative curves and an all-measurements switch.
- Added configurable mean-radius lines and mean R labels, draggable desktop label positions, and export of the exact visible graph. Overlay annotations start disabled; shared color/ratio controls remain available.
- Added below-graph per-measurement and arithmetic-average radius, diameter and distribution %PD results, CSV exports and calculation explanations distinguishing distribution moments from cumulants Z-average/PDI.
- Added font-aware row heights/scrollbars to all Lab DLS lists and a web companion with portable session libraries and numeric annotation positioning.

## 0.8.6 — 2026-09-19

- Changed Aliphatic/Aromatic shortcuts to rerun preprocessing from preserved raw spectra, using the selected ppm range for alignment, grid, smoothing and normalization. Added an editable Custom region shortcut, defaulting to 0–200 ppm.
- Displayed the applied processing range and synchronized preprocessing settings on desktop and web. Repeated switches never process an already normalized or smoothed view.
- Regional R²/r² now use each region's own processing result. Preserved a shared preprocessing basis for aliphatic/aromatic integral ratios so independent regional normalization cannot erase relative signal amounts. Audit views record the correct processing source for every calculation.

## 0.8.5 — 2026-09-19

- Added Aliphatic region / Aromatic region buttons to desktop and web spectrum comparison. Each click uses the current region bounds and immediately updates the plot and overall comparison statistics without rerunning preprocessing.
- Invalid or unmeasured region selections leave the current comparison range intact and show a clear message.

## 0.8.4 — 2026-09-19

- Fixed clipped ssNMR list/library text by sizing rows from the actual UI font.
- Added separately audited R², Pearson r/r² and point counts for the comparison, aliphatic and aromatic regions; changing bounds automatically updates statistics and ratios.
- Added common graph width:height controls, a square preset and default-ratio restoration. Desktop preview/clipboard/PNG/SVG/PDF and web preview/downloads preserve the selected full-figure ratio.
- Applied the requested seven-color RGB order across desktop and web curves, bars and TEM distributions; explicit per-series colors remain supported.

## 0.8.3 — 2026-09-19

- Replaced Bruker ZIP/FID ssNMR import with four-column TopSpin ASCII (ppm column 4, intensity column 2), preserving title-bearing first data rows.
- Added a desktop raw-spectrum list, rename/remove actions, and independent persistent ssNMR library with reload/rename/delete/reorder.
- Added shared-grid paired comparison with native edge-baseline correction, bounded rigid chemical-shift alignment, shared Gaussian broadening and normalization. Real-only exported phase is preserved and explicitly reported.
- Added direct R², Pearson r/r² and configurable aliphatic/aromatic signed integral ratios below the overlay.
- Added complete per-point preprocessing/statistics and per-segment integration audit windows, TXT exports and comparison CSV.
- Added the same processing and metrics to the web edition with a portable JSON session library and Korean/English labels.

## 0.8.2 — 2026-08-10

- Made the desktop ZetaSizer DLS and zeta distribution legends directly draggable.
- Saved the DLS and zeta legend positions independently so they survive redraws, restarts, and updates.
- Restoring a distribution graph to its tab defaults now also restores the legend to its default upper-right position.

## 0.8.1 — 2026-08-09

- Added an initial Streamlit web edition that shares LabPlotter's desktop parsing and scientific analysis core.
- Added browser workflows for FTIR processing, NanoDrop overlays, Bruker ssNMR processing, ZetaSizer distributions and raw-peak summaries, TEM TIFF screening, and custom spreadsheet mappings.
- Added English/Korean web controls, Origin-style plot settings, per-series colors, and PNG/SVG/CSV downloads.
- Kept web uploads session-oriented; persistent libraries, editable ZetaSizer OCR review, Windows clipboard export, and `.labpatch` management remain desktop-only.
- Added a dedicated web dependency file, Streamlit theme, Korean CJK font package, Linux web smoke CI, and shared-core web tests.

## 0.8.0 — 2026-07-23

- Added a dedicated TEM particle-size tab for one or many TIFF images.
- Grouped files into batches from filenames while keeping independent batch, image, and detected-particle counts separate.
- Added automatic Hitachi H-D2300/Gatan scale-bar detection and editable nm/px calibration.
- Added local dark-particle segmentation with adjustable diameter, center-distance, threshold, border, and blank-field controls.
- Added exact SHA-256 duplicate rejection and automatic blank-field exclusion with a reversible review state.
- Added original-image detection overlays, per-batch size-distribution plots, and particle-level CSV export.
- Added a persistent local TEM library whose images and reviewed settings survive application updates.
- Added English/Korean UI text and deterministic TEM analysis, calibration, blank, duplicate, and storage tests.

## 0.7.4 — 2026-07-23

- Filtered each ZetaSizer graph-settings page to the particles actually drawn on that graph.
- DLS and zeta distribution settings now list only particles with the matching raw measurement kind.
- DLS Z-average and average-zeta batch settings now list only particles with the corresponding plotted OCR summary value.
- Preserved hidden per-particle color preferences so they return if that particle later becomes plottable.

## 0.7.3 — 2026-07-23

- Prevented crowded legends from collapsing the DLS and zeta distribution axes; compact dashboards now show up to eight entries plus a remaining-series count.
- Fixed the missing graph-settings builder for DLS and zeta distribution color controls.
- Made long instrument-specific graph-setting pages vertically scrollable.
- Added a determinate ZetaSizer import progress display with live percentage, workbook, sheet, particle, measurement, and OCR task details.
- Kept the graph-settings window visible behind its parented Windows color chooser.

## 0.7.2 — 2026-07-23

- Fixed the ZetaSizer graph-settings freeze when switching a curve or bar color mode from all-series to per-particle.
- Prevented live-preview writes from recursively scheduling themselves.
- Debounced graph-setting previews and avoided redundant batch-label database writes and full library refreshes.

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
