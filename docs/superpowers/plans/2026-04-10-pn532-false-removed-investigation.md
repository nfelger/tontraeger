# PN532 False-REMOVED Investigation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Identify and fix the root cause of immediate `REMOVED` events after `PRESENT` without guesswork, using hypothesis-driven diagnostics and minimal experiments.

**Architecture:** The investigation focuses on two boundaries: (1) software interpretation at `client/nfc-daemon/main.c` and libnfc/PN53x return codes, and (2) physical transport reliability (wiring quality and PN532 host protocol selection). We first add instrumentation-only diagnostics, then run tightly scoped A/B experiments that isolate one variable per iteration.

**Tech Stack:** C (`nfc-daemon`), Python async controller, libnfc (PN532 drivers/chip layer), PN532 manual.

---

## Current Status (Handoff Snapshot)

- Investigation status: **paused** (system is currently reliable enough for day-to-day use).
- Instrumentation and hypothesis loop are in place and actively used.
- Daemon policy has been refined to classify presence-check results by type:
  - `ret >= 0` => `ok` (reset misses)
  - `NFC_ETGRELEASED` / `NFC_EINVARG` / `NFC_EDEVNOTSUPP` => `hard-miss`
  - other negatives (notably `NFC_ERFTRANS` / `-20`) => `transient`
- This removed major false-pauses from `-20` bursts while preserving reliable removal behavior.
- Transport experiments completed so far:
  - UART: works with improved policy but noisy/transient-heavy.
  - SPI: functional but unstable at frame level (`Unable to wait for SPI data`, checksum/startcode mismatches).
  - I2C: best observed behavior so far (stable + responsive with reliable play/remove).
- Recommended current operating transport for next session: `pn532_i2c:/dev/i2c-1`.

---

## Task Progress (What Was Actually Tried)

- **Task 1 (completed):** Added deep diagnostics in `client/nfc-daemon/main.c` (session ids, per-poll ret/miss transitions, elapsed ms, UID/ATQA/SAK, connstring).
- **Task 2 (completed):** Ran repeated place/hold/remove cycles and collected enough logs to classify error patterns.
- **Task 2b (completed):** Ran physical/transport validation iterations. UART baseline + connector reseat showed limited improvement. SPI A/B exposed frame-level errors. I2C A/B produced the best stability/responsiveness.
- **Task 3 (completed):** Maintained and updated hypothesis backlog in this file across all experiments.
- **Task 4 (completed):** Implemented policy-classification experiments and iterated from naive any-negative handling to class-based handling.
- **Task 5 (not needed):** Timing-only variant was superseded by stronger evidence from return-code classification and transport experiments.
- **Task 6 (mostly completed):** Root-cause class identified (transport noise + return-code handling). Production policy fix implemented in `client/nfc-daemon/main.c`. Remaining verification items are long-run behavior and multi-tag matrix.
- **Task 7 (pending):** Multi-tag validation matrix not yet run.
- **Task 8 (pending user action):** `INSTALL.md` still needs manual accuracy check by you.

---

## Hypothesis Backlog (Single Source of Truth)

### Confirmed / Supported

- **H1:** Presence-check errors can be transient and should not immediately imply removal.
- **H3:** Any-negative miss policy was too strict; class-based handling is required.
- **H10:** UART is less robust than alternatives in this installation; I2C is currently best observed.

### Rejected / Retired

- Reselect confirmation gate (v1/v2) as primary fix (did not reliably confirm and added complexity).
- SPI speed-only tuning as primary fix (did not remove SPI frame-level instability).

### Open / Untested

- **H12:** Multi-tag transitions (A/B swaps, near-simultaneous tags) may expose session-edge failures not seen in single-tag tests.
  - Disproof signal: no missing `PRESENT`, no wedged state, no missed `REMOVED` across Task 7 matrix.
- **H13:** I2C may still show long-run drift/intermittency not visible in short runs.
  - Disproof signal: extended soak run shows stable `present/remove` behavior with no stuck loops.
- **H14:** Deployment docs may not match the now-validated transport/config path.
  - Disproof signal: user review confirms `INSTALL.md` matches real setup end-to-end.
- **H15:** During session handoff, placing tag B before tag A has fully emitted `REMOVED` can cause a no-output gap where tag B is not recognized.
  - Disproof signal: targeted handoff test shows consistent `PRESENT`/`REMOVED` continuity with no logging stalls.

---

## Context Baseline

- Event flow is daemon-led: `PRESENT`/`REMOVED` are emitted by `client/nfc-daemon/main.c`, consumed by `client/tontraeger_client/control.py`.
- Original daemon behavior treated any `nfc_initiator_target_is_present(...) < 0` as a miss and emitted `REMOVED` after 3 misses at 300ms intervals.
- libnfc/PN53x internals indicate that negative codes include both true release and transient RF/protocol errors.

---

### Task 1: Lock Investigation Baseline and Observability Contract

**Status:** Completed

**Goal:** Define exactly what must be observed before changing behavior.

**Files:**
- Modify: `client/nfc-daemon/main.c`
- Verify notes in: `client/CLAUDE.md` (if needed later)

**Acceptance Criteria:**
- [x] Diagnostic fields are specified and implemented with no behavior changes.
- [x] Logs can distinguish strong removal from transient communication failure.
- [x] Each presence poll is traceable to a specific card session.

**Verify:** Run client with daemon logs and confirm diagnostic lines appear for each poll.

**Steps:**
- [x] Add a per-session identifier for each `PRESENT` to `REMOVED` cycle.
- [x] Log on `PRESENT`: UID, timestamp, and any available target classification hints.
- [x] Log on each presence check: session id, poll index, `ret`, `nfc_strerror(dev)`, misses before/after, elapsed ms since `PRESENT`.
- [x] Log on `REMOVED`: session id, total elapsed ms, and terminal miss summary.
- [x] Keep event protocol unchanged (`PRESENT`/`REMOVED` output format remains identical).

---

### Task 2: Gather Evidence and Build Return-Code Histogram

**Status:** Completed

**Goal:** Collect enough runtime evidence to rank hypotheses from observed behavior.

**Files:**
- No code changes required (operational run + analysis notes)

**Acceptance Criteria:**
- [x] At least one multi-minute capture with repeated place/hold/remove cycles.
- [x] Histogram produced for ret buckets: `0`, `NFC_ETGRELEASED`, `NFC_ERFTRANS`, `NFC_ETIMEOUT`, other.
- [x] False-REMOVED cases isolated with immediately preceding return-code sequences.

**Verify:** Provide a short report with count table and 3 representative event timelines.

**Steps:**
- [x] Run controlled test cycles: place tag, hold steady, remove tag, repeat.
- [x] Tag each cycle outcome as correct/false removal.
- [x] Extract and count return-code patterns before each `REMOVED`.
- [x] Record whether false removals cluster around ~0.9-1.1s after `PRESENT`.

---

### Task 2b: Validate Physical Link and Transport Assumptions

**Status:** Completed (with follow-up transport decision recorded)

**Goal:** Rule in/out wiring and host-transport instability before attributing failures to logic.

**Files:**
- No source edits required for baseline checks
- Optional notes: `docs/superpowers/plans/2026-04-10-pn532-false-removed-investigation.md`

**Acceptance Criteria:**
- [x] Active libnfc connstring and transport are captured (`pn532_uart`, `pn532_i2c`, or `pn532_spi`).
- [x] Physical checklist is completed (power, ground, signal integrity, cable path).
- [x] If hardware supports alternatives, at least one transport A/B comparison is run under the same test cycles.

**Verify:** Investigation notes contain a one-page matrix: transport, wiring setup, false-REMOVED rate, and observed return-code histogram.

**Steps:**
- [x] Capture active device connstring at runtime (via `nfc_device_get_connstring` log or `nfc-scan-device`) and record exact bus/protocol.
- [x] Run a physical sanity checklist:
  - stable 3.3V supply under load
  - shared ground quality
  - TX/RX (or SDA/SCL / SPI lines) continuity and level compatibility
  - cable length/routing away from EMI sources
- [x] Repeat Task 2 cycles after reseating/reterminating wiring to detect contact/intermittency effects.
- [x] If feasible on this hardware, run one protocol alternative (e.g., SPI or I2C) with same daemon build and compare outcome distributions.

**Operational checklist (Pi):**
- [x] Capture baseline run to file:
  - `journalctl -u tontraeger-client -f | tee /tmp/nfc-baseline.log`
- [x] Perform one physical change at a time (example order):
  - re-seat PN532 connector and ground,
  - shorten/reroute UART wiring away from EMI,
  - improve 3.3V/GND stability.
- [x] Capture post-change run to file:
  - `journalctl -u tontraeger-client -f | tee /tmp/nfc-after-change.log`
- [x] Compare quick metrics between files:
  - `-20` frequency (`RF Transmission Error` lines),
  - average time from `present` to `removed`,
  - sessions with no `present` while tag is intentionally placed.

---

### Task 3: Hypothesis Backlog (Ranked) and Disproof Signals

**Status:** Completed (living document maintained)

**Goal:** Maintain a living, falsifiable hypothesis set.

**Files:**
- Modify: `docs/superpowers/plans/2026-04-10-pn532-false-removed-investigation.md` (this section)

**Acceptance Criteria:**
- [x] 8+ hypotheses ranked by likelihood.
- [x] Every hypothesis has a disproof signal tied to actual logs.
- [x] Backlog is updated after each experiment pass.

**Verify:** Review document includes "evidence for/against" per hypothesis.

**Initial Backlog (historical snapshot from investigation start):**
- [ ] H1: Any-negative-as-miss policy conflates transient RF faults with real removal.
- [ ] H2: Tag subtype path in PN53x presence logic changes error profile.
- [ ] H3: Immediate post-`PRESENT` interval is unstable and causes transient misses.
- [ ] H4: `MISS_THRESHOLD=3` at 300ms is too aggressive for real RF conditions.
- [ ] H5: Unsupported/state-related return codes are being counted as physical removal.
- [ ] H6: Bus-level timing jitter (I2C/SPI/UART path) produces burst failures.
- [ ] H7: Helper retry strategy in libnfc is insufficient for this deployment environment.
- [ ] H8: Physical/environmental RF interference causes consecutive transient failures.
- [ ] H9: Intermittent wiring/power integrity causes short communication dropouts interpreted as tag removal.
- [ ] H10: UART transport is less robust in this installation than SPI/I2C (or current UART configuration is marginal).
- [ ] H11: UART framing/baud/driver-side timing mismatch causes clustered transient errors after selection.

---

### Task 4: Minimal Experiment A (Policy Classification)

**Status:** Completed (iterated through v1-v4 policy)

**Goal:** Test whether strict negative-code handling causes false removals.

**Files:**
- Modify: `client/nfc-daemon/main.c`
- Test: daemon runtime log behavior

**Acceptance Criteria:**
- [x] One policy-only variant implemented (no unrelated refactor).
- [x] Event protocol still unchanged.
- [x] A/B comparison against baseline available.

**Verify:** Compare false-REMOVED rate baseline vs experiment run.

**Steps:**
- [x] Keep current logic as baseline branch/commit.
- [x] Implement experimental classification:
  - hard miss for `NFC_ETGRELEASED`
  - transient bucket for `NFC_ERFTRANS`/`NFC_ETIMEOUT` (separate handling)
- [x] Run same cycle protocol as Task 2.
- [x] Decide if H1 is supported/rejected from measured delta.

---

### Task 5: Minimal Experiment B (Timing Only)

**Status:** Skipped by design (classification + transport evidence was stronger)

**Note:** Leave this task untouched unless new evidence shows timing (not return-code class or transport) is the primary driver.

**Goal:** Isolate timing sensitivity independently of return-code classification.

**Files:**
- Modify: `client/nfc-daemon/main.c`

**Acceptance Criteria:**
- [ ] Only timing knobs change (e.g., grace window or threshold), no other behavior changes.
- [ ] Measurable impact on false-REMOVED rate is captured.

**Verify:** Side-by-side rate and latency comparison vs baseline.

**Steps:**
- [ ] Add one timing variant (choose one):
  - post-`PRESENT` grace period before miss counting, or
  - higher miss threshold with same poll interval.
- [ ] Repeat Task 2 cycle protocol.
- [ ] Evaluate H3/H4 support based on change magnitude and removal latency.

---

### Task 6: Converge on Root Cause and Production Fix

**Status:** In progress (core fix landed; long-run + multi-tag verification pending)

**Goal:** Select the smallest durable fix backed by evidence and guard it with tests.

**Files:**
- Modify: `client/nfc-daemon/main.c`
- Modify/Add tests as appropriate in `client/tests/` (or daemon-level validation harness if test framework coverage is limited)

**Acceptance Criteria:**
- [x] Root cause statement is evidence-backed (not speculative), and explicitly classifies software vs physical/protocol origin.
- [x] Fix is minimal and targeted.
- [ ] Regression coverage exists for observed failure mode.

**Verify:** `make check` at repo root passes; runtime validation no longer shows immediate false removals.

**Steps:**
- [x] Promote one hypothesis to root-cause status only if directly supported by logs/experiments.
- [x] Implement minimal final behavior.
- [ ] Add/adjust tests or deterministic checks for the selected policy.
- [ ] Run `/usr/bin/make check`.
- [ ] Record before/after behavior summary in a short debugging note.

---

### Task 7: Multi-Tag Validation (Post-Stabilization)

**Status:** Pending

**Goal:** Validate behavior with multiple physical tags after single-tag reliability is stable.

**Files:**
- No source edits required for validation run
- Optional notes: `docs/superpowers/plans/2026-04-10-pn532-false-removed-investigation.md`

**Acceptance Criteria:**
- [ ] Sequential tag swaps are reliable (A->remove->B, B->remove->A).
- [ ] Quick swap tests (remove A and place B quickly) do not wedge session state.
- [ ] Simultaneous/near-simultaneous two-tag placement does not lock the daemon loop.
- [ ] No stuck condition where new `PRESENT` events stop appearing after removals.

**Verify:** Capture logs for a multi-tag matrix and summarize pass/fail per scenario.

**Steps:**
- [ ] Use at least two known-good mapped tags (A and B).
- [ ] Run matrix:
  - A hold/remove, then B hold/remove
  - B hold/remove, then A hold/remove
  - quick swap A->B and B->A
  - both tags near reader at same time (expect nondeterministic pick)
- [ ] Confirm each scenario eventually emits matching `REMOVED` for active session and accepts next `PRESENT`.
- [ ] Record any scenario that causes missing events or stuck polling as a new hypothesis.

---

### Task 8: Install Guide Verification (User Check)

**Status:** Pending (user-owned check)

**Goal:** Ensure deployment instructions match the validated transport and runtime behavior.

**Files:**
- Review only: `INSTALL.md`

**Acceptance Criteria:**
- [ ] You (human operator) manually verify that `INSTALL.md` accurately reflects the transport/setup we are actually using.
- [ ] Any mismatch is captured as a follow-up docs task (do not fix inside this step).

**Verify:** Add a short note in the next session whether `INSTALL.md` is accurate or needs updates.

**Steps:**
- [ ] Read `INSTALL.md` end-to-end from the perspective of a fresh device setup.
- [ ] Confirm instructions for PN532 mode/wiring, libnfc connstring, and service env behavior match working reality.
- [ ] If anything is off, record exact section(s) and expected corrections as backlog items.

---

## Next Session Start Point

- Continue only if reliability regresses; otherwise keep current policy/transport as-is.
- Keep `client/nfc-daemon/main.c` policy as-is unless new contradictory evidence appears.
- Keep transport baseline on I2C (`pn532_i2c:/dev/i2c-1`).
- Run Task 7 multi-tag matrix on I2C.
- Perform Task 8 (`INSTALL.md` manual verification by user) and capture any doc gaps.
- First targeted experiment if resumed: add pre/post `nfc_initiator_target_is_present(...)` timing logs and test fast A->B handoffs where B is placed before A's `REMOVED` is emitted.
- If Task 7 reveals regressions, add them as new hypotheses and run targeted single-variable experiments only.

## Research Anchors (for future reference)

- Client daemon logic:
  - `client/nfc-daemon/main.c`
- Python event handling:
  - `client/tontraeger_client/control.py`
- libnfc target presence dispatch:
  - `vendor-src/libnfc/libnfc/nfc.c`
  - `vendor-src/libnfc/libnfc/drivers/pn532_i2c.c`
  - `vendor-src/libnfc/libnfc/drivers/pn532_spi.c`
  - `vendor-src/libnfc/libnfc/drivers/pn532_uart.c`
  - `vendor-src/libnfc/libnfc/chips/pn53x.c`
  - `vendor-src/libnfc/include/nfc/nfc.h`
  - `vendor-src/libnfc/libnfc.conf.sample`
- PN532 manual:
  - `docs/pn532-user-manual.pdf`
