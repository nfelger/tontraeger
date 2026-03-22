# Alpine.js to htmx Migration

**Date:** 2026-03-22
**Status:** Ready for planning

## What We're Building

Migrate two Alpine.js features to htmx server-rendered patterns, and clarify CLAUDE.md to reflect a pragmatic "htmx-first, Alpine.js where simpler" principle.

### Migrations

1. **Unknown tag polling + rendering** — Replace Alpine's `setInterval` + JSON fetch + client-side rendering with htmx `hx-trigger="every 5s"` polling a server endpoint that returns an HTML fragment.

2. **Speaker dropdown population** — Replace Alpine's `loadSpeakers()` JSON fetch + `x-for` rendering with htmx `hx-get` on load, server returns `<option>` elements.

### Kept as Alpine.js

- **"Use" tag button** — Copies a tag UID into a form input. A simple `x-ref` + value assignment is cleaner than any htmx alternative.
- **Speaker auto-select** — When only one speaker exists, auto-select it. Small Alpine snippet is simpler than server-side logic.
- **"Now Playing" button** — Multi-state button (loading/error/success) that sets a value on a different input. Genuine client-side state.
- **Print mode** — Global UI mode toggle with selection state across many cards. Textbook client-side state management.

## Why This Approach

The CLAUDE.md principle is "prefer htmx where possible" but the intent is pragmatic: use htmx for server-driven interactions (data fetching, rendering lists, polling), use Alpine.js where client-side state genuinely makes things simpler (DOM manipulation, UI mode toggles, multi-state buttons).

The two selected migrations are clear wins — they replace client-side JSON-to-HTML rendering with server-rendered fragments, which is exactly what htmx excels at. The kept features are cases where Alpine.js is the simpler, more natural tool.

## Key Decisions

- **htmx-first, not htmx-only**: Alpine.js is the right tool when it makes things simpler than htmx would. Update CLAUDE.md to reflect this nuance.
- **"Use" button stays Alpine**: Inline DOM manipulation (setting an input value) is cleaner with Alpine/JS than with htmx form re-rendering.
- **Speaker auto-select stays Alpine**: Client-side convenience logic, not worth a server round-trip.
- **New server endpoints needed**: One for unknown tags HTML fragment, one for speaker `<option>` list.

## Scope

- Migrate unknown tag polling to htmx
- Migrate speaker dropdown population to htmx
- Update CLAUDE.md UI Principles to clarify the htmx/Alpine.js boundary
- Remove Alpine.js code that becomes unused (but keep Alpine.js itself — it's still needed)
