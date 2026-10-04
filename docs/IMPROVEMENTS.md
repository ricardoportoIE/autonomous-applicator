# Post-test improvements

The October 2026 improvement pass prioritises decisions that the candidate can inspect and everyday use of the local workbench. All controls retain evidence-based 80/50 routing and the configured attempt limits.

## Delivered

| Improvement | Practical value | Validation |
| --- | --- | --- |
| React/TypeScript workspace | Organises existing information in clean cards, creation/editing dialogues and application tabs | Typed API contracts, draft/revision handling, native focus checks, production-browser parity and accessibility tests |
| Stronger frontend session ownership | Rejects old responses even after unlocking with the same token; preserves the newest refresh | Session-generation, simultaneous expiry and out-of-order refresh regressions |
| Application document workspace | Keeps current downloads and explicit approved-evidence selection together | Vacancy-specific provenance retained; manual preparation records a distinct origin |
| Local submission preflight | Explains each gate before any browser action; shows current fit and actionable blockers | Read-only checks, missing profile, pause/scope, exhausted capacity, unresolved questions, stale/altered/missing materials and invalid LinkedIn identity |
| Daily attempt budget | Shows actual usage and remaining capacity for the London calendar day | Includes uncertain reservations, midnight reset and limit reductions below existing usage |
| Search, status and sorting | Finds opportunities by role, employer and location; prioritises fit or recency | Case-insensitive multi-term search, combined status filters, stable sorting, zero-fit/unevaluated ordering and source records unchanged |
| Application activity | Keeps relevant journal entries visible even when global activity is busy | Entries scoped by application, newest-first limit and older entries outside the global window |
| Faster queue reads | Removes repeated database connections as the queue grows | Single-connection listing and indexes for journal/attempt queries |
| Earlier target and cover checks | Prevents avoidable attempt consumption and incomplete materials | Identity and required cover PDF validated before reservation; submission still repeats provider checks |

The preflight is deliberately a snapshot, not an external validation or reservation. It does not discover unknown provider questions or certify account sign-in. No application, invitation or paid AI request was sent during this improvement pass.

## Next priorities

These are proposed follow-on capabilities, not implemented features.

1. **Live adapter validation:** use the authenticated account to review selectors, uploads and parsed candidate fields before enabling the background agent. Keep uncertain attempts held for reconciliation.
2. **Scheduling diagnostics:** current vacancy, preparation/submission stage, elapsed time and failure history are already implemented. Add next scheduled cycle and a health check that never enables automation.
3. **Saved search sets:** store separately named Ireland and UK searches, deduplicate shared results and keep one application budget across them.
4. **Follow-up planning:** candidate notes, interview dates and local reminders tied to confirmed submissions. Messaging would remain an explicit candidate action.
5. **Feedback analysis:** compare outcome patterns only when enough confirmed results exist. Present proposals for review; never infer new qualifications, immigration facts or automatically change permissions.

Live account validation is the next operational dependency. The other items can be developed with fictional local fixtures while automation remains paused.
