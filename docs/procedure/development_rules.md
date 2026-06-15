# Development Rules

## Golden Rules

1. **One phase at a time.** Never work on multiple phases concurrently.
2. **Complete before continuing.** A phase is only complete after the user confirms all manual tests pass.
3. **No production code.** This is a UI Mockup Prototype only.
4. **No backend.** No REST API, database, WebSocket, or external services.
5. **No real data.** All data is dummy data stored in `src/data/`.
6. **No authentication.** No login, no sessions, no authorization.

## Asset Rules

- Use only existing assets in `src/assets/images/` and `src/assets/videos/`.
- Never create, download, or modify image/video assets.
- Reuse assets across multiple dummy cameras as needed.

## Modification Rules

- PRD, SRS, and SDD are **immutable** without explicit user request.
- Procedure and phase documents can be updated if needed.
- Never refactor outside the scope of the current phase.

## Error Handling

- If stuck, report the issue clearly to the user.
- Do not make assumptions about desired behavior.
- If a requirement is ambiguous, ask the user.
