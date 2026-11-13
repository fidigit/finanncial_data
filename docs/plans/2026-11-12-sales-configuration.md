# Sales configuration implementation plan

Goal: keep version 0.0.3; reorganize sales-only source, formula and parameter entry points.

1. Extract read-only source samples from the local reference workbook; store business samples in ignored data/.
2. Add an authenticated, BD-scoped source-preview API with six kinds (splits, targets, services, orders, segmentation, constants). Do not apply historical Q3 samples to current Q4 orders.
3. Replace the old top-level variable drawer entry with six source buttons. Source preview is an 80vw x 80vh animated, blurred-background modal. Manual source editing is reserved for the next stage.
4. Retain five blue formula gears only (S/J/K/T/X); display fixed executed rules and empty future binding slots in a 150x100 scrollable popover. Show seven calculated intermediates in formula details, no independent entry.
5. Add two purple parameter gears (S/X). Use a compact 50x30 input viewport with vertical scrolling for multiple rates, accessible labels/tooltips and Enter-to-save. Reuse scoped/versioned period API. Show defaults as examples; preserve existing values.
6. Keep all nineteen columns and existing CSV sample records, market/meetings, row confirmations and exports. Remove extra editable variable drawer from sales.
7. Typecheck/build; scoped API/permission tests; headless UI checks for six buttons, five blue/two purple gears, dimensions, blur, sample data, persistence on isolated DB, no polling and layout fit. Restart local deployment.
