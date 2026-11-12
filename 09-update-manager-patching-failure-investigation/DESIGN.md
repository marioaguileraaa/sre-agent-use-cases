---
name: Swiss Architectural Industrial Operations Ledger
description: An offline Azure Update Manager post-patching and root-cause investigation workpaper with an anthracite verdict band, warm architectural stone canvas, 1px structural rules, industrial orange accents and the shared Azure SRE Agent severity scale.
colors:
  canvas: "#F6F5F2"
  surface: "#FFFFFF"
  subtle: "#F9FAFB"
  wash: "#EFECE6"
  ink: "#141B24"
  muted: "#475569"
  line: "#D8DCE3"
  line-soft: "#E6E8EC"
  field-line: "#64748B"
  accent: "#FF4E00"
  accent-text: "#C23800"
  accent-hover: "#9A2C00"
  accent-wash: "#FFF3ED"
  chrome: "#141B24"
  chrome-hover: "#1E293B"
  chrome-line: "#334155"
  chrome-muted: "#B8C2CF"
  hero-bg: "#141B24"
  hero-panel: "#1C2531"
  hero-muted: "#C5CEDA"
  critical-ink: "#B42318"
  critical-bg: "#FEE4E2"
  critical-bar: "#D92D20"
  high-ink: "#B93815"
  high-bg: "#FFEAD5"
  high-bar: "#EF6820"
  medium-ink: "#93370D"
  medium-bg: "#FEF0C7"
  medium-bar: "#F79009"
  low-ink: "#175CD3"
  low-bg: "#D1E9FF"
  low-bar: "#2E90FA"
  info-ink: "#344054"
  info-bg: "#EAECF0"
  ok-ink: "#067647"
  ok-bg: "#DCFAE6"
  ok-bar: "#17B26A"
  note-ink: "#7A2E0E"
  note-bg: "#FFFAEB"
  dark-canvas: "#0F141B"
  dark-surface: "#161E29"
  dark-subtle: "#1B2430"
  dark-wash: "#243040"
  dark-ink: "#F1F5F9"
  dark-muted: "#CBD5E1"
  dark-line: "#334155"
  dark-field-line: "#94A3B8"
  dark-accent-text: "#FF8552"
  dark-accent-wash: "#2B1912"
typography:
  display:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, -apple-system, sans-serif"
    fontSize: "42px"
    fontWeight: 700
    lineHeight: 1.12
  heading:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, -apple-system, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
  body:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, -apple-system, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  technical:
    fontFamily: "'Consolas', ui-monospace, monospace"
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.45
---

# Design System: Swiss Architectural Industrial Operations Ledger

## Creative Direction

This offline engineering workpaper keeps a disciplined Swiss architectural grid for infrastructure operations and post-patching root-cause triage, and follows the shared Azure SRE Agent report family (verdict first, KPI ledger, findings register, prioritised plan, sources last):

1. **Palette & Surface Hierarchy**:
   - Sticky top bar in deep anthracite slate (`#141B24`) with a 3px vivid orange (`#FF4E00`) structural rule: product mark, client name or logo plaque, a read-only chip, dark mode, an export menu (JSON and two CSVs) and the primary `Imprimir / PDF` action.
   - Verdict-first hero band in the same anthracite: title (two lines at most), one sentence with the key numbers, provenance chips (generated UTC, window, LIVE or SIMULATED), a verdict card (`Acción requerida` / `Requiere atención` / `Revisar` / `Sin bloqueos`) with the first action, and a severity distribution bar with legend.
   - Warm architectural stone background (`#F6F5F2`) with white 1px-bordered (`#D8DCE3`) cards, 10px radius and a soft offset shadow.
   - Interactive links and accent labels in accessible burnt orange (`#C23800`, contrast >= 4.5:1 on white).
   - Severity uses the shared family scale (text on background, bar colour): critical `#B42318` on `#FEE4E2` (`#D92D20`), high `#B93815` on `#FFEAD5` (`#EF6820`), medium `#93370D` on `#FEF0C7` (`#F79009`), low `#175CD3` on `#D1E9FF` (`#2E90FA`); healthy (`Correcto`) uses ok `#067647` on `#DCFAE6` (`#17B26A`) and neutral states `#344054` on `#EAECF0`.
   - Full dark mode (`[data-theme="dark"]`) switching to `#0F141B` / `#161E29` with translucent severity washes.

2. **Typography & Tabular Discipline**:
   - One sans family, `'Outfit', 'Segoe UI', system-ui, sans-serif`, for display, headings, copy, controls and table headers; hierarchy comes from size and weight (42 / 22 / 16 / 15 / 13 px).
   - `font-variant-numeric: tabular-nums` on all counters, timestamps, durations and patch tallies.
   - `'Consolas', monospace` reserved for ARM resource IDs, KB identifiers, package versions, correlation IDs and guest extension log paths. Long ARM IDs show as resource name + resource group + Portal link (full ID in the tooltip, CSV and JSON) and only break at `/` or `\`.

3. **Layout**:
   - KPI ledger strip of six cells joined by 1px rules, overlapping the bottom edge of the hero.
   - Sticky left section index with live counts (collapses to a horizontal strip under 1100px).
   - Section order: summary, prioritised action plan, per-machine register (filters, search, sort, CSV of the view, expandable evidence drawers), cycles, patches, extensions, sources and method.
   - A4 print keeps colours, hides controls, expands every drawer and prints a footer with title, client, generation time and page numbers.

4. **Strict Craft Floor & Anti-Slop Rules**:
   - No purple/blue gradients, glass blur, gradient text or emoji icons.
   - No tracked-out uppercase eyebrow kickers above headings.
   - No thick `border-left` > 1px on cards or rows.
   - No identical floating SaaS metric cards; metrics sit inside one 1px architectural ledger strip.