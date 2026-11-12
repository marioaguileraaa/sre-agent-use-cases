---
name: Swiss Architectural Industrial Operations Ledger
description: Disciplined operations workpaper in the Azure SRE Agent report family, combining deep anthracite slate chrome and a verdict-first header, warm stone paper surfaces with white hairline cards, the shared severity palette, and accessible industrial orange accents.
colors:
  brand-orange: "#FF4E00"
  brand-orange-alt: "#FC4C00"
  brand-orange-text: "#C23800"
  brand-orange-wash: "#FFF2EC"
  slate-topbar: "#141B24"
  slate-header: "#1C2532"
  bg-page: "#F6F5F2"
  bg-panel: "#FFFFFF"
  bg-subtle: "#F1EEE8"
  ink-primary: "#141B24"
  ink-secondary: "#3E4C5E"
  ink-muted: "#5A687A"
  border-hairline: "#DEDCD6"
  border-strong: "#9AA5B5"
  dark-bg-page: "#0F141B"
  dark-bg-panel: "#161E29"
  dark-border-hairline: "#2A3647"
  dark-ink-primary: "#F3F5F8"
  dark-orange-text: "#FF8854"
  sev-critical: "#B42318 on #FEE4E2, bar #D92D20"
  sev-high: "#B93815 on #FFEAD5, bar #EF6820"
  sev-medium: "#93370D on #FEF0C7, bar #F79009"
  sev-low: "#175CD3 on #D1E9FF, bar #2E90FA"
  sev-info: "#344054 on #EAECF0, bar #98A2B3"
  ok: "#067647 on #DCFAE6"
typography:
  heading:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, sans-serif"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  body:
    fontFamily: "'Outfit', 'Segoe UI', system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  mono:
    fontFamily: "'Consolas', ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
---

# Design System: Swiss Architectural Industrial Operations Ledger

## Visual Direction

- **Report family, case brand**: The dossier follows the Azure SRE Agent report family (slim sticky top bar, verdict-first slate header, KPI cards overlapping it, white hairline cards on the warm `#F6F5F2` stone ground, horizontal bars with values, sortable registers, coverage and method last) while keeping this case's slate and orange identity.
- **Verdict first**: The `#1C2532` → `#141B24` header carries the H1 (at most two lines), the window, one sentence with the key counts, chips for generation time, window, subscription, LIVE/SIMULATED and coverage, a verdict card (`Acción requerida`, `Requiere atención`, `Sin hallazgos prioritarios`) and the severity distribution.
- **Accessible Brand Accent**: Industrial orange `#FF4E00` marks the top-bar rule, the primary `Imprimir / PDF` action, focus rings and the `Inmediato <24h` horizon; `#C23800` carries links and tags above 4.5:1 on light surfaces (`#FF8854` in dark mode).
- **Shared severity palette**: Pills and bars use the family colours listed above, so severities read the same across every use-case report.
- **Type and numbers**: One sans stack (Outfit, then Segoe UI and the system font), tabular numerals, H1 42 px, H2 22 px, body 15 px, tables 13.5 px; monospace only for IDs, ARM types and read signatures.
- **Print**: A4 landscape, colours kept, controls and filters hidden, every register row printed, repeated table headers and a footer with title, window, date and page numbers.
- **Anti-Slop Discipline**: No purple/blue gradients, no gradient text, no eyebrow kickers above headings, no thick `border-left` > 1px callouts, no emoji icons, no cards inside cards.
- **Branding Privacy**: Public source files remain generic (`CLIENT_NAME = "CLIENTE"`, `CLIENT_LOGO_DATA_URI = ""`). When a private deployment configures a Pillow-validated PNG/JPEG logo, it renders inside a dedicated white plaque (`#client-plaque`) that preserves contrast in both light and dark modes.
