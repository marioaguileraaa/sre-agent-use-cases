---
name: Swiss Architectural Industrial Operations Ledger
description: Disciplined architectural operations workpaper combining deep anthracite slate chrome, warm stone paper surfaces, 1px hairline ledger grids, and accessible industrial orange accents.
colors:
  brand-orange: "#FF4E00"
  brand-orange-alt: "#FC4C00"
  brand-orange-text: "#C23800"
  brand-orange-wash: "#FFF2EC"
  slate-topbar: "#141B24"
  slate-header: "#1C2532"
  bg-page: "#F6F5F2"
  bg-panel: "#FFFFFF"
  bg-subtle: "#EFECE6"
  ink-primary: "#141B24"
  ink-secondary: "#3E4C5E"
  ink-muted: "#5A687A"
  border-hairline: "#D8DCE3"
  border-strong: "#9AA5B5"
  dark-bg-page: "#0F141B"
  dark-bg-panel: "#161E29"
  dark-border-hairline: "#2A3647"
  dark-ink-primary: "#F3F5F8"
  dark-orange-text: "#FF8854"
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

- **Architectural Precision**: Built as an engineering operations ledger rather than a SaaS marketing dashboard. Panels use crisp `#FFFFFF` surfaces over a warm `#F6F5F2` stone background with 1px `#D8DCE3` structural borders.
- **Accessible Brand Accent**: Vivid industrial orange `#FF4E00` (`#FC4C00`) accents the topbar rule and primary action controls, paired with `#C23800` text links and tags that exceed 4.5:1 contrast on light surfaces (`#FF8854` in dark mode).
- **Anti-Slop Discipline**: No purple/blue gradients, no tracked-out eyebrow kickers above headings, no thick `border-left` > 1px callouts, and no uniform rounded SaaS metric cards.
- **Branding Privacy**: Public source files remain generic (`CLIENT_NAME = "CLIENTE"`, `CLIENT_LOGO_DATA_URI = ""`). When a private deployment configures a Pillow-validated PNG/JPEG logo, it renders inside a dedicated white plaque (`#client-plaque`) that preserves contrast in both light and dark modes.
