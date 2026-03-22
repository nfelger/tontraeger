---
title: "hx-boost bypasses native onsubmit confirmation dialogs"
category: ui-bugs
date: 2026-03-22
tags: [htmx, hx-boost, hx-confirm, onsubmit, delete]
components: [server/tontraeger_server/web.py]
---

## Problem

A delete form used `onsubmit="return confirm('Delete this mapping?')"` to show a native browser confirmation dialog. Clicking "Cancel" still deleted the mapping. The page has `hx-boost="true"` on `<body>`, which intercepts all form submissions via AJAX, bypassing the native `onsubmit` handler entirely.

## Root Cause

When `hx-boost="true"` is active, htmx takes over form submission. It does not trigger the browser's native submit event in a way that respects `onsubmit` return values. The `confirm()` dialog either never fires, or its `return false` is ignored because htmx has already initiated its own request.

## Solution

Replace `onsubmit="return confirm(...)"` with htmx's native `hx-confirm` attribute on the form:

```html
<!-- Before (broken under hx-boost) -->
<form method="post" action="/mappings/123/delete" style="display:inline"
      onsubmit="return confirm('Delete this mapping?')">

<!-- After (works with hx-boost) -->
<form method="post" action="/mappings/123/delete" style="display:inline"
      hx-confirm="Delete this mapping?">
```

`hx-confirm` hooks into htmx's request lifecycle, so the confirmation fires before htmx issues the request. Keep the `<form>` wrapper (rather than a bare `hx-post` button) so that `hx-boost` handles the server's 302 redirect response as a full-page navigation.

## Prevention

When `hx-boost="true"` is active, never use native form event handlers (`onsubmit`, `onclick` returning false) to gate submissions. Always use htmx-native attributes (`hx-confirm`, `hx-validate`, etc.) instead.
