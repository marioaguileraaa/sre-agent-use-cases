---
name: Azure Databricks dependency and configuration dossier
description: An offline, verdict-first Azure SRE Agent report in the family house style, framed by corporate navy/steel and the Databricks lava/teal ribbon, for qualified dependency and WAF evidence.
colors:
  paper: "#f2f5f8"
  surface: "#ffffff"
  soft: "#eef2f6"
  hover: "#f6f9fc"
  ink: "#16212c"
  title: "#002b4e"
  muted: "#4f5d6b"
  line: "#dde3ea"
  line2: "#c2ccd6"
  link: "#0058a3"
  focus: "#0b6bcb"
  chart: "#0066a1"
  edge: "#4d7aa3"
  button: "#003865"
  button-hover: "#002848"
  hero-a: "#003865"
  hero-b: "#00223c"
  hero-muted: "#c3d5e8"
  brand-navy: "#003865"
  brand-lava: "#ff3621"
  brand-steel: "#0066a1"
  brand-teal: "#00875a"
  critical: "#b42318 on #fee4e2, bar #d92d20"
  high: "#b93815 on #ffead5, bar #ef6820"
  medium: "#93370d on #fef0c7, bar #f79009"
  low: "#175cd3 on #d1e9ff, bar #2e90fa"
  info: "#344054 on #eaecf0, bar #98a2b3"
  ok: "#067647 on #dcfae6, bar #17b26a"
  observed: "#00603f on #ddf4ea, line #00875a"
  inferred: "#8a4b00 on #fff1d6, dashed line #c77700"
  unknown: "#475467 on #eaecf0, hollow dot #98a2b3"
  dark-paper: "#0d141b"
  dark-surface: "#15202a"
  dark-soft: "#1c2834"
  dark-ink: "#e6edf3"
  dark-muted: "#a9b7c5"
  dark-line: "#26333f"
  dark-link: "#8cc8ff"
  dark-hero-a: "#0a2742"
  dark-hero-b: "#061626"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "clamp(28px, 3vw, 44px)"
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: "-.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "23px"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "-.01em"
  title:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  table-dense:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "12.5px"
    fontWeight: 600
    lineHeight: 1.55
  technical:
    fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace'
    fontSize: "12.5px"
    fontWeight: 400
    lineHeight: 1.55
  kpi-value:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "33px"
    fontWeight: 700
    lineHeight: 1.05
    fontVariantNumeric: "tabular-nums"
rounded:
  card: "16px"
  control: "10px"
  pill: "999px"
spacing:
  tight: "4px"
  compact: "8px"
  control: "12px"
  base: "16px"
  card: "20px"
  section: "48px"
---

# Design System: Azure Databricks Dependency and Configuration Dossier

## Overview

**Creative North Star: "The Lakehouse Dependency Dossier"**

An offline Azure SRE Agent report in the family house style: a slim sticky top bar (product mark, section navigation, `Solo lectura` chip, dark mode, an export menu and Print / PDF), a verdict-first navy band (title, one sentence with the key numbers, provenance chips, `CLIENTE` plaque, verdict card, severity distribution), KPI cards overlapping the band, then white cards on a light neutral ground. Corporate deep navy and industrial steel (`#003865`, `#0066a1`) carry the chrome and the hero; the Databricks lava and teal accents (`#ff3621`, `#00875a`) live in the four-colour brand ribbon.

## Components

- **Severity pills** use the shared family colours (critical, high, medium, low, info); check status uses a coloured dot with a Spanish label (`Cumple`, `No cumple`, `No evaluado`, `No aplica`).
- **Dependency classification** has its own vocabulary: `OBSERVED` (solid teal-green), `INFERRED` (dashed amber), `UNKNOWN` (hollow grey). The graph places nodes in one column per layer, draws OBSERVED edges solid and INFERRED edges dashed, and shows a legend; tables always hold 100 % of nodes, edges and blind spots.
- **Charts** are labelled horizontal bars with values (check status, areas, pillars, source status); no decorative charts.
- **Tables** scroll inside their card with edge-shadow cues, sort by column, page long lists, and show long ARM IDs as name, resource group and a Portal link; raw JSON evidence stays behind a `JSON completo` disclosure.
- **Print / PDF**: A4 with `@page` margins, colours kept, controls hidden, cards not split, and a running footer with the report title, workspace, UTC reference and page numbers. Dark mode is reset while printing.

## Branding and Privacy Boundaries

- The generic committed code, documentation, tests and templates contain **no customer logo** and **no customer identifiers**.
- `CLIENT_NAME` defaults to `"CLIENTE"` and `CLIENT_LOGO_DATA_URI` defaults to `""`.
- When `CLIENT_LOGO_DATA_URI` is empty, the cover renders a sober `CLIENTE` plaque placeholder.
- An authorized operator may privately configure a Pillow-validated single-frame PNG/JPEG data URI (`<= 100,000` bytes, `<= 2048 x 2048` px) in a private deployment copy outside Git.
- Brand colors frame the dossier chrome and ribbon; they never represent health or fabricate missing source coverage.
