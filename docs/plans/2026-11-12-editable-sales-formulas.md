# Executable sales formula editing

Goal: five blue gears edit and execute S/J/K/T/X; keep version 0.0.3.

- Sales-wide versioned rules; admin write, authenticated read; ordinary BD does not acquire write permission.
- Decimal expression interpreter with AST whitelist, length/node/depth bounds, upstream-only variable lists, lazy IF/COALESCE, typed and range-checked outputs. Never eval/exec arbitrary code.
- Default S=R; J=split ratio; K=ROUND(H*J,2); T=previous cumulative+included basis; X=eligibility/gate/renewal/channel tier. Preserve explicit manual overrides and existing data-scope/export behavior.
- Recompute complete owner-quarter groups before filters/pages. T changes propagate to V; evaluate X separately for ordinary/base/excess branches so custom X also changes AA, including cross-target orders. AB continues selecting automatic segmented or ordinary calculation.
- Authenticated definitions GET; admin preview POST and version-checked PUT. Trial changes are isolated in memory. New runtime errors reject saves, missing inputs remain pending. Audit changes; restore default increments version.
- Replace read-only binding placeholders with 500x400 editor, current/default formula, variable insertion/help, preview rows, save and reset. Preserve 200x150 purple parameter popover.
- Verify default regression, all five edits affecting downstream, cross-tier X edits, invalid/malicious/cyclic inputs, versions/permissions, preview immutability, XLSX values, UI save/restore on copied QA DB. Restart actual service with original DB.
