# Human Validation Policy

## Mandatory Human Validation

All development output **must be validated by a human** before proceeding.

## What Needs Validation

- Component rendering and layout
- Navigation and interaction flows
- Filter and synchronization behavior
- Visual consistency with dark monitoring theme
- Asset loading (images/videos)
- Console and network error absence

## AI Restrictions

The AI **must not**:

- Claim that a feature is working correctly.
- State that the application is running without errors.
- Assume tests would pass.
- Self-validate any implementation.
- Mark tasks as complete without user confirmation.

## Validation Process

1. AI completes the phase implementation.
2. AI provides a Manual Testing Checklist.
3. User runs manual tests.
4. User reports results (pass/fail).
5. If fail, AI fixes bugs in the current phase only.
6. If pass, user provides explicit approval to continue.
