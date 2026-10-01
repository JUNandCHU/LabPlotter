# Changelog

## 0.11.0 — 2026-10-01

- Add desktop and browser NTA workspaces with multi-ZIP atomic import, declared-video manifests, complete six-distribution/percentile validation, cross-file consistency and raw track integrity checks. Report missing files or invalid content before adding data; support nested packs and deduplicate identical imports.
- Add 19 plot modes covering weighted distributions, technical-video summaries/CV/QC, particle intensity/histograms, inclusion counts, drift, trajectories, displacement, MSD, straightness and intensity traces. Expose explicit dilution, stock mass and footprint inputs for optional derived estimates. Keep instrument and raw-track values separate.
- Reuse common graph controls, colors, editable legends, fonts, aspect ratio, clipboard and PNG/SVG/PDF export. Persist NTA controls and per-plot axis preferences; export summary, plotted coordinates and measurement/QC CSV. Add Korean controls and Hangul-aware categorical tick labels. Clear trajectory aspect when switching plots and cancel pending canvas draws on close.
- Preserve the previously delivered 0.10.9 desktop baseline (including H NMR Ver1/Ver2); do not reset libraries. Add synthetic malformed-pack/scientific/GUI regression tests; private measurements are used only for local validation.

## 0.10.9 — 2026-09-30

- Make the ANP report's broad_core3 decomposition available as model Ver2: linked aliphatic, aromatic and broad unassigned MAS families with independent nonnegative satellite heights. Fit both raw quadratures, bounded PH0/PH1 and a complex affine background; keep unassigned area separate from coverage. Default MAS / proton frequency remains 20 kHz / 400 MHz (50 ppm). Integration and complex-fit windows remain explicit and independently recorded.
- Keep model Ver1 as default and preserve old saved core-template analyses under “Legacy core template (0.10.7–0.10.8)”. No stored model is silently reinterpreted. Honor phase/baseline switches, manual phase overrides and amplitude scale; use an explicit real-only fallback when complex source is absent or smoothing is active.
- Expose “Aromatic correction: On — aromatic reference / Off — entered masses” in quantitative confirmation. Both choices work with Ver1 and the new Ver2. Preserve mass/calibration/H-count presets, signed coverage and the Schiff/Michael scenario endpoints.
- Replace the long main quantitative result list with a sample table: aromatic, aliphatic and coverage. Switch between µmol H/mg and raw intensity·ppm integrals. H/mg columns are pre-normalization; coverage reflects the selected correction. Keep a short provisional/out-of-range indicator. Move all other values, component/sideband accounting, warnings and the full audit into “More info”. Values remain selectable/copyable.
- Share corrected observations between the plot, fit residual, saved fit and CSV. Preserve component colors/styles, solid aliphatic/aromatic curves, residual-off default, library roundtrips and font-sized rows. Cache signatures include both quadratures and correction settings. Model sensitivity also tests fixed phase and broad-family width.
- Validation: all five supplied ANP series reproduce the earlier report's three family integrals within 0.001%; this is implementation reproducibility, not independent chemical validation. Complex synthetic recovery, both correction formulas, blank zero, manual/disabled corrections, saved-fit invalidation and GUI/browser workflows are covered. Broad assignment and phase-bound warnings remain visible in additional information.

## 0.10.8 — 2026-09-30

- Fix Ver2 quantitative analysis failing with `'float' object cannot be interpreted as an integer` for wide MAS spectra. Preserve the validated integer sideband order when form/JSON input is `2.0`, and validate settings at the template fitter entry point. Fractional orders remain invalid rather than silently rounded.
- Add display-independent tests of the actual desktop form serializer, pristine ANP blank and modified-core calculations with fresh/saved preprocessing, library/batch restoration and unchanged Ver1 results. Retain all fitting bounds, preprocessing, calibration and coverage equations.

## 0.10.7 — 2026-09-30

- Add selectable H NMR `model Ver1` (existing envelopes, still the default) and `model Ver2` (measured pristine-core template plus additional ligand). Ver2 fits core scale/shift, optional broadening, linked independent +/- sidebands and optional unassigned signal; it does not label the empirical core aromatic or infer particle mass.
- Connect both models to quantitative confirmation, finite-domain integrals, component/sum/residual overlays, per-curve styles, exact-view exports, CSV/audit, libraries, batch reports, model review and independent sample/reference phase sensitivity. Save template provenance and processed snapshots with fingerprint validation; changing correction settings invalidates fits.
- Add editable Schiff-base/Michael-addition H-count scenarios, both coverage endpoints and sorted lower/upper values. Default comparison includes one linkage N-H for neutral singly attached Michael products (C6: 13/14; C18: 37/38). C-H-only integration gives identical endpoints; per-ligand overrides persist. These conditional scenarios are not confidence intervals or proof of the binding mechanism.
- Preserve Ver1 nominal coverage, calibration/mass defaults, raw complex inputs, C NMR and other tabs. Add synthetic algebra/recovery/persistence tests, desktop model-selection tests and browser workflows for both models and endpoint controls.

## 0.10.6 — 2026-09-30

- Route both desktop C/H NMR import buttons through the same format-aware workspace importer. Complex TopSpin exports now open H NMR even when imported from the initial C tab; four-column exports open C NMR from either button.
- Recognize commented/BOM-prefixed ppm-real-imag tables with all supported delimiters. Preserve specific complex-file validation errors, batch valid spectra, aggregate failures and leave the current selection untouched on cancellation.
- Preserve raw complex arrays, existing phase/baseline processing, decomposition, quantitative calculations and user libraries. Add regression tests for actual import-button callbacks and mixed-file batches.

## 0.10.5 — 2026-09-30

- Default H NMR coverage to the supplied spreadsheet method: area -> umol H -> per-mg aromatic matching to pristine core -> excess aliphatic H -> ligand stoichiometry / maximum loading. Record normalization factors and all intermediate values. Retain optional mass-only subtraction and signed provisional estimates.
- Use explicit umol H fields throughout desktop, web, parameter files, batch CSV and audits. The supplied unverified default now means 1.861273386 umol H. Migrate legacy defaults, preserve custom/verified physical amounts, and update unchanged ANP/ANP-DMEN mass defaults to 38.38/55.18 mg.
- Default residual off and aliphatic/aromatic components to solid lines. Move the H NMR intensity multiplier into the Y-axis label without changing data; retain plain/scientific alternatives. Saved custom curve styles remain editable.
- Add read-only drag selection within result values, copy-value / tab-separated-table controls and selectable component cells. Preserve font-derived row heights and scrolling.
- Add read-only line-shape/overlap model comparison and broad-component diagnostics. Review all ANP spectra with multiple starts, alternative models and PH0 perturbations; do not force an expected integral ordering or silently reassign ambiguous signal.

## 0.10.4 — 2026-09-30

- Display provisional absolute coverage/ligand/loading by default without falsely marking calibration, acquisition or fit checks as verified. Keep optional reviewed-only withholding, all unresolved issues, actual assumed units/scales and signed/out-of-range results in audits.
- Add reviewable all-loaded-sample calculation, persistent reference choices, per-sample errors, result CSV with parameters/status, and coverage-first desktop/browser tables. Missing numeric inputs remain explicit errors.
- Add noise-aware resolved-sideband PH0/PH1 refinement with simultaneous masked-baseline recalculation, bounded search, central-envelope guards and candidate/acceptance records. Keep previous/manual corrections if no acceptable improvement; preserve raw complex arrays and independent sideband heights.
- Add a shared-group reprocessing shortcut with stale-result invalidation, Korean controls, font-aware tables, real Tk/browser tests, algebra/persistence/sign/phase regression tests and cumulative update packaging.

## 0.10.3 — 2026-09-30

- Use the editable 400 MHz / 20 kHz lab preset for new wide H NMR imports; link preprocessing masks and MAS fitting to 50 ppm without rescaling the input axis. Keep saved conditions intact and expose an explicit preset/reset route.
- Default to DMfit-style equal-width satellite links; add fixed per-family G fractions, optional signed diagnostic satellites, and a per-line finite/full-profile integration table. Preserve independent +/- heights and visible overlay/export styles.
- Add read-only PH0 sensitivity comparisons with fixed PH1 and recomputed baseline/fits, independent sample/reference ranges, entered mass/response scaling, and no label-dependent fitting constraints.
- Report boundary/alternate-solution ambiguity and instrument/envelope mismatch. Withhold absolute coverage for ambiguous assignments or negative fitted satellite areas. Calibration/acquisition/local residual gates remain active.
- Keep long coverage warnings from hiding result rows. Refresh decomposition previews after processing changes and reject stale fit application. Add desktop/browser controls, persistence and regression coverage.

## 0.10.2 — 2026-09-30

- Add empirical MAS sideband families to H NMR decomposition: linked spacing/shape, independent +/- amplitudes, optional common satellite-width multiplier, central/sideband/total integrals and per-order CSV/audit records. No peak-count area multiplier or mirrored weak peaks.
- Add data-aware wide preprocessing, bounded automatic PH0/PH1, outer peak-excluded baseline anchors, persistent manual phase pivot/span, and a correction/sideband QC view. Inspect per-order residuals and detection significance in addition to global R2.
- Record the supplied standard as including all sidebands without changing its area or mmol H. Withhold coverage for mismatched scopes, unreviewed satellite coverage or substantial local residuals; preserve calibration/acquisition/assignment gates.
- Retain family overlays, per-curve colors/styles, exact-view copy/export, libraries and common graph features. Preserve old settings with an explicit full-range migration path. Add scientific, persistence, real-Tk and browser regression coverage.
- Package a direct 0.10.0 to 0.10.2 update including 0.10.1. The linked-envelope model is inspired by DMfit ssb; it is not DMfit or a CSA/dipolar simulation.

## 0.10.1 — 2026-09-29

- Correct H NMR quantitation to decompose before integrating; retire direct-window/aromatic-mass-scaling as quantitative methods. Fit constrained Gaussian, Lorentzian or pseudo-Voigt aliphatic/aromatic envelopes, with an optional unassigned overlap band.
- Add fit preview, component/sum/residual overlays, analytic finite-domain component integrals, fit diagnostics and raw-window diagnostic areas. Persist fit settings, records and styles with fingerprint-based invalidation.
- Add individual decomposition line width/style/visibility, area shading and shared curve colors; clipboard and PNG/SVG/PDF retain the currently visible layers.
- Withhold absolute ligand amounts/coverage until standard units/response, quantitative acquisition and assignments are reviewed. Separate proton-signal fractions from coverage; retain unclipped model algebra in the audit. Use entered mass ratios for pristine-core background, with optional independently known core mass.
- Migrate old analysis settings safely, retain C NMR/DLS behavior, and update desktop/browser workflows and scientific/UI regression coverage.

## 0.10.0 — 2026-09-29

- Preserve C NMR under an ssNMR subtab and add complex H NMR import with immutable real/imaginary inputs, automatic zero-order phase, optional manual phase, baseline switches and common non-normalizing preprocessing.
- Add independent persistent complex-spectrum and quantitative-parameter libraries, group preparation status, editable calibration/core/ligand/mass presets, and JSON portability. Lys defaults contain MW only.
- Add confirmation-before-calculation, pristine-core corrected region areas, optional exploratory three-band Gaussian decomposition, apparent ligand coverage/loading/mass equivalents, signed out-of-range diagnostics, complete formula/input/processing audit and processed CSV export.
- Keep absolute results explicitly provisional until standard area units/response and effective H assignments are verified; never clamp negative or >100% results.
- Reuse shared desktop curve colors, legend editing, graph ratios, clipboard and exports; use font-aware rows and scrolling forms. Add the browser companion and quantitative/UI regression tests.

## 0.9.2 — 2026-09-24

- Added a shared Curve colors page to every desktop plot's settings, with native RGB selection, HEX/name input, live/manual apply, color swatches, per-curve/default restoration and font-sized scrollable rows.
- Connected FTIR, NanoDrop, ssNMR raw/comparison, ZetaSizer means/replicates/bars, Lab DLS individual/average/overlay distributions, TEM histograms and custom-format plots. Keep overrides attached to data identity through hide/show, rename, reorder and region reprocessing.
- Keep linked labels, mean/median lines, SD bands, legends and exports in sync with curve colors while preserving explicitly configured annotation colors. Color-only edits retain toolbar zoom/pan and do not change analysis data or results.
- Unified web color pickers with default restoration and session persistence across hidden widgets; added missing ssNMR and TEM controls and separate ZetaSizer replicate colors.

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
