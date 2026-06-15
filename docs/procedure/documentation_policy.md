# Documentation Policy

## Document Priority (Conflict Resolution)

1. PRD (Product Requirements Document)
2. SRS / SKS (Software Requirements Specification)
3. SDD (Software Design Document)
4. Procedure Documents (`docs/procedure/*`)
5. Phase Documents (`docs/phases/*`)

## Documentation Structure

```
docs/
├── procedure/     # Development guidelines (immutable during a phase)
└── phases/        # Phase definitions (sequential development steps)
```

## Phase Document Rules

- Maximum **200 lines** per phase file.
- Must include: Objective, Scope, Task List, Dependency, Expected Output, Manual Testing Checklist.
- No source code in phase documents.
- Each phase must be modular and self-contained.

## Document Immutability

- PRD, SRS, SDD — **do not modify** unless the user explicitly requests changes.
- Procedure and phase documents — can be updated when agreed upon with the user.
- All document changes must be communicated to the user before implementation.
