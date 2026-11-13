# Complete the fixed sales rule interfaces

Goal: all five gears display expanded human-readable fixed rules; keep version 0.0.3.

- J: order+BD source lookup, individual split amount / total; show empty/shared/manual cases; no invented configurable fallback.
- K: expand split lookup into order amount times split share and rounding; two decimals fixed, no new precision parameter.
- T: same BD/quarter, chronological cumulative sum of each expanded basis. Expose only existing include_ineligible switch; manual basis and confirmation priorities retained.
- X: expand eligibility, full-quarter basis gate, renewal, channel recommendation, BD-quarter target lookup/comparison and cross-target amounts. Expose exactly threshold + seven rates; target and input orders remain source inputs.
- S stays the already approved fixed VIP rule with shared VIP parameter.
- Runtime/API lock all five canonical expressions; no public free-form rewriting or circular references. Leave old stored expression text untouched but inactive under the fixed-rule policy.
- Add BD-quarter scoped, versioned, allowlisted parameter preview/save endpoints; partial changes preserve unrelated period values. Existing purple entries use the same parameter storage/validation.
- Remove free-expression UI/placeholders. Keep source modal and popover sizes; provide complete text, editable parameter fields, no-write trial, save/default/reload, read-only calculation detail.
- Verify defaults, all five locked endpoints, parameter whitelist/types/version/access scope, gate/tier propagation, preview immutability, export matching and UI synchronization. Test mutation only on copied QA DB; actual DB values unchanged.

Validation completed: 61 backend tests passed; TypeScript and production build passed. Isolated browser check verified all four expanded rules, zero code editors, J/K no extra parameters, T scope save/reset, X trial without writes, rate-to-bonus change, blue/purple synchronization, S retained and 19-column fit.
