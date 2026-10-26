---
name: Swiss Architectural Industrial Operations Ledger
description: An offline Azure Update Manager post-patching and root-cause investigation workpaper with anthracite slate chrome, warm architectural stone canvas, 1px structural rules, and industrial orange accents.
colors:
  canvas: "#F6F5F2"
  surface: "#FFFFFF"
  subtle: "#F9FAFB"
  wash: "#EFECE6"
  ink: "#141B24"
  muted: "#475569"
  line: "#D8DCE3"
  field-line: "#64748B"
  accent: "#FF4E00"
  accent-text: "#C23800"
  accent-hover: "#9A2C00"
  accent-wash: "#FFF3ED"
  chrome: "#141B24"
  chrome-hover: "#1E293B"
  chrome-line: "#334155"
  success: "#15803D"
  success-teal: "#0F766E"
  success-wash: "#ECFDF5"
  warning: "#B45309"
  warning-wash: "#FFFBEB"
  critical: "#B91C1C"
  critical-wash: "#FEF2F2"
  unknown: "#475569"
  unknown-wash: "#F1F5F9"
  dark-canvas: "#0F141B"
  dark-surface: "#141B24"
  dark-subtle: "#1E2633"
  dark-wash: "#263040"
  dark-ink: "#F1F5F9"
  dark-muted: "#CBD5E1"
  dark-line: "#334155"
  dark-field-line: "#94A3B8"
  dark-accent: "#FF6A2B"
  dark-accent-text: "#FF8552"
  dark-accent-wash: "#2C1A12"
typography:
  heading:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, sans-serif"
    fontWeight: 600
    lineHeight: 1.25
  body:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  technical:
    fontFamily: "'Consolas', ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.45
---

# Design System: Swiss Architectural Industrial Operations Ledger

## Creative Direction

This offline engineering workpaper adopts a disciplined Swiss architectural grid tailored for infrastructure operations and post-patching root-cause triage:

1. **Palette & Surface Hierarchy**:
   - Top bar and structural headers in deep anthracite slate (`#141B24`) with a 3px vivid orange (`#FF4E00`) structural rule.
   - Warm architectural stone background (`#F6F5F2`) paired with crisp `#FFFFFF` 1px-bordered (`#D8DCE3`) workpaper panels.
   - Interactive links and accent labels in accessible burnt orange (`#C23800`, contrast >= 4.5:1 on white); semantic state tokens strictly reserved for verified success (`#0F766E` / `#15803D`), warning/in-progress (`#B45309`), failure/unresponsive (`#B91C1C`), and unknown/unassessed (`#475569`).
   - Full dark mode (`[data-theme="dark"]`) switching cleanly to `#0F141B` / `#141B24`.

2. **Typography & Tabular Discipline**:
   - `'Outfit', 'Segoe UI', system-ui, sans-serif` for headings, narrative copy, controls, and table headers.
   - `font-variant-numeric: tabular-nums` enforced on all counters, timestamps, durations, and patch tallies.
   - `'Consolas', monospace` strictly reserved for ARM resource IDs, KB identifiers, package versions, correlation IDs, and guest extension log paths.

3. **Strict Craft Floor & Anti-Slop Rules**:
   - No purple/blue gradients or decorative glass blur.
   - No tracked-out uppercase eyebrow kickers above headings.
   - No thick `border-left` > 1px on cards or rows.
   - No identical SaaS metric cards; metrics sit inside a unified 1px architectural ledger strip.
