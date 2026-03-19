---
title: "Print layout must account for two-cut lamination workflow"
category: ui-bugs
date: 2026-03-19
tags: [print, css, lamination, physical-dimensions]
---

## Problem

Print view for NFC tag cards was designed with 65×65mm edge-to-edge cards and no consideration for the physical lamination process. Multiple issues compounded:

1. Cards printed at 65mm left no room for laminate seal — final laminated cards would exceed 65mm
2. Full-bleed 210mm grid width is unprintable (printers have ~5mm margins)
3. Cut guides (L-shaped ticks, dashed outlines) didn't match the actual workflow
4. `|tojson` Jinja filter outputs double-quoted strings that break double-quoted HTML attributes, causing Alpine.js initialization failures

## Root Cause

The print layout was designed around the desired *final* card size (65mm) rather than working backwards from the physical workflow: print → cut paper → laminate → cut laminate. Each step imposes constraints on the previous one.

## Solution

**Work backwards from the physical workflow:**

- Final laminated card: 65×65mm with 3mm rounded corners
- Laminate seal needs ~3mm on each side
- Therefore printed paper card: 59×59mm
- Grid: 3×4 of 59mm cells, edge-to-edge (177mm wide, fits printable area)
- Single cut guide: solid rounded outline (59mm, 3mm radius) per card
- Edge-to-edge cells allow single straight cuts to separate rows/columns

**For Jinja `|tojson` in Alpine.js attributes:** use single-quoted HTML attributes (`x-data='...'`) since `|tojson` outputs double-quoted JSON strings.

```html
<!-- Breaks: double quotes nest -->
<div x-data="artworkRow({{ tag_uid|tojson }})">

<!-- Works: single-quoted attribute -->
<div x-data='artworkRow({{ tag_uid|tojson }})'>
```

## Prevention

When designing for physical output (print, cut, laminate), always start from the final physical dimensions and work backwards through each production step, subtracting tolerances at each stage. Document the full workflow (with all intermediate sizes) in the plan before writing CSS.
