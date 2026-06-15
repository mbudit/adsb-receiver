# Testing Policy

## Testing Approach

This project uses **Manual Testing exclusively**. There are no automated tests.

## Who Tests

Testing is performed **entirely by the user (human)**.

## AI Restrictions

The AI must **never**:

- Run automated test suites (none exist).
- Claim that a feature is working correctly.
- State that the application runs without errors.
- Self-validate any implementation.
- Assume manual test results.

## Manual Testing Checklist

At the end of each phase, the AI provides a checklist. Example:

- [ ] Halaman berhasil dibuka.
- [ ] Tombol dapat diklik.
- [ ] Sidebar berfungsi.
- [ ] Data dummy tampil.
- [ ] Tidak ada error pada console.
- [ ] Tidak ada error pada network.
- [ ] Layout sesuai desain.

## Testing Environment

- **Resolution:** 1920×1080 or higher.
- **Browser:** Latest Chrome, Firefox, or Edge.
- **Dev Server:** `npm run dev` (Vite).

## Bug Reporting

- User reports which checklist items fail.
- AI fixes bugs within the current phase only.
- After fix, user retests the failed items.
