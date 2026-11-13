# Eligibility column only: expanded fixed rule

- Expand S -> R -> service-name / order-amount / service-rule lookup. Display complete human-readable branching instead of a bare R.
- Only editable control is VIP minimum amount, shared with existing BD-quarter purple parameter storage. Fixed VIP service name, comparison, yes/no branches, service-rule lookup and missing/error -> Check cannot be edited.
- Server S template uses descriptive variables and expands the same R logic. S expression endpoint rejects arbitrary rewrites. Existing saved legacy S text is not executed by this fixed-template mode; other four definitions remain untouched.
- Add no-write VIP parameter trial scoped to selected BD+quarter; reuse comparison result schema. Save via existing versioned period endpoint. Preserve manual per-order confirmation priority.
- Both blue 500x400 and purple 200x150 remain. Blue S shows full rule with inline editable amount, trial/save/default/reload; detail repeats expanded rule with sources. Do not apply old Q3 preview tables to current Q4 data.
- Tests: >= boundary, nonVIP lookup true/false/missing, missing amount, manual priority; strict endpoint lock, parameter validation/version/permission, preview no writes, save-to-bonus/export, other four unchanged. Isolated UI save/synchronization plus actual read-only deployment smoke. Version stays 0.0.3.
