---
name: "CLIENTE Service Health review"
description: "A charcoal and yellow review hero over white evidence cards, in the Azure SRE Agent report family."
colors:
  yellow: "#fbc807"
  charcoal: "#1e1c18"
  paper: "#f3f4f5"
  sheet: "#ffffff"
  soft: "#f4f5f7"
  hover: "#f8f9fa"
  ink: "#1f2328"
  title: "#16181b"
  muted: "#555b61"
  line: "#e1e4e8"
  line-strong: "#c4c9cf"
  hero-muted: "#d4d0c8"
  link: "#155da4"
  focus: "#155da4"
  incident: "#b42318"
  incident-wash: "#fee4e2"
  incident-bar: "#d92d20"
  maintenance: "#93370d"
  maintenance-wash: "#fef0c7"
  maintenance-bar: "#f79009"
  active: "#175cd3"
  active-wash: "#d1e9ff"
  neutral: "#344054"
  neutral-wash: "#eaecf0"
  neutral-bar: "#98a2b3"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "clamp(32px, 4vw, 44px)"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.3
  title:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "19px"
    fontWeight: 700
    lineHeight: 1.3
  kpi:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "36px"
    fontWeight: 700
    lineHeight: 1
  body:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  table:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  kicker:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.5
    letterSpacing: "0.08em"
  pill:
    fontFamily: '"Segoe UI", system-ui, -apple-system, sans-serif'
    fontSize: "12px"
    fontWeight: 650
    lineHeight: 1.5
  mono:
    fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace'
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  control: "10px"
  card: "16px"
  pill: "999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "16px"
  space-4: "24px"
  space-5: "40px"
components:
  print-button:
    backgroundColor: "{colors.charcoal}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    padding: "0 16px"
  ghost-button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 14px"
  download-link:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
  input-field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  temporal-lane:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "5px 6px 5px 14px"
  temporal-lane-selected:
    backgroundColor: "{colors.yellow}"
    textColor: "{colors.charcoal}"
  pill-incident:
    backgroundColor: "{colors.incident-wash}"
    textColor: "{colors.incident}"
  pill-maintenance:
    backgroundColor: "{colors.maintenance-wash}"
    textColor: "{colors.maintenance}"
  pill-active:
    backgroundColor: "{colors.active-wash}"
    textColor: "{colors.active}"
  pill-neutral:
    backgroundColor: "{colors.neutral-wash}"
    textColor: "{colors.neutral}"
  card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
    padding: "20px 24px"
  kpi-card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.title}"
    rounded: "{rounded.card}"
    padding: "16px 18px"
---

# Design System: CLIENTE Service Health review

## Overview

**Creative North Star: "The Evidence Workpaper, in the report family"**

The report shares the structure of the Azure SRE Agent report family (slim top bar, verdict-first hero, KPI cards overlapping the hero, white cards on a light ground, a register, then sources and method) and keeps this case's own identity: a charcoal hero with yellow accents, yellow for selection, and named evidence colours that never come from the brand.

Without a configured logo the top bar shows the **Azure SRE Agent** wordmark and the hero kicker carries the configured client name (`CLIENTE` in generic source). A configured, validated customer raster replaces the wordmark, and the Read-only chip then reads "Azure SRE Agent · Read-only". No empty logo frame is drawn. The source-sampled yellow and charcoal are visual authority, not an official customer brand specification. This document records the built `report_template.html`, not a live capture or source-acceptance result. `SURFACE.md` keeps the local task sequence.

**Key characteristics:**
- Charcoal hero with a 4 px yellow top rule, yellow kicker and yellow review status; white type on charcoal.
- One sans family (the system UI stack), tabular numerals everywhere, monospace only for identifiers and original records.
- White cards with a soft two-layer shadow on a pale neutral ground.
- Pills with a leading dot for event types and source states; text always names the meaning.
- Visible keyboard focus, sortable column headers as real buttons, and no network or external assets.

## Colors

### Brand

- **Client Yellow** (`yellow`): hero top rule, kicker, review status, provenance chip, selected temporal lane, selected-row tint, the step numbers and the skip link.
- **Client Charcoal** (`charcoal`): hero ground, print button, selected-lane count, chart bars and dark lettering on yellow.

### Evidence (shared report-family pills and bars)

- **Incident red** (`incident`, `incident-wash`, `incident-bar`): service-incident pills and the Active-incident share of the hero bar.
- **Maintenance amber** (`maintenance`, `maintenance-wash`, `maintenance-bar`): planned-maintenance pills, partial-coverage pills, incomplete-source KPI and the Active-maintenance share.
- **Active blue** (`active`, `active-wash`): the native **Active** source state.
- **Neutral slate** (`neutral`, `neutral-wash`, `neutral-bar`): Resolved and other non-Active states, complete or successful-empty receipts and the Resolved share. **Unknown** state uses a hatched slate bar segment.
- **Link / focus blue** (`link`, `focus`): links, "Review next" actions and the 3 px focus outline.

### Neutral

- **Paper** (`paper`) page ground; **Sheet** (`sheet`) cards and controls; **Soft** (`soft`) table headers, count badges and code blocks; **Hover** (`hover`) row hover.
- **Ink** (`ink`) body text, **Title** (`title`) headings and KPI values, **Muted** (`muted`) labels and notes (at least 6.9:1 on white).
- **Line** (`line`) card borders and rules; **Line strong** (`line-strong`) control borders.
- **Hero muted** (`hero-muted`) secondary text on charcoal (about 10:1).

### Named rules

**The Dark-on-Yellow Rule.** Yellow surfaces always carry charcoal lettering, never white.

**The Separate Semantics Rule.** Yellow marks identity and selection only. Evidence states keep their own pill colours and an explicit text label; a completed receipt is slate, never a green health verdict.

## Typography

**Font:** Segoe UI with system-ui, -apple-system and sans-serif fallbacks; no embedded fonts. **Receipts:** ui-monospace, Cascadia Mono, Consolas.

- **Display** (H1): fluid 32 to 44 px, bold, tight tracking, at most two lines.
- **Headline** (section H2) 22 px; **Title** (card H2, dossier H3) 19 px; dossier H4 15 px.
- **KPI** values 36 px bold (30 px under 640 px).
- **Body** 15 px / 1.55, measure at most 75ch. **Table** 14 px. **Label** 13 px semibold for field names and filter labels. **Kicker** 13 px uppercase, tracked, yellow on charcoal.
- **Pill** 12 px semibold. **Mono** 13 px for tracking IDs, receipt IDs and resource IDs; secondary table lines (times, "total unknown") 13 px.
- `font-variant-numeric: tabular-nums` is set on the body so counts and times align.

## Layout

- Top bar: sticky, 60 px, white, with the wordmark or logo, section links (Summary, Communications, Sources, Method), the Read-only chip and the Print / PDF button.
- Hero: full-bleed charcoal; a two-column grid (copy and meta chips, then the review-status card) and a full-width distribution bar with legend. Content width 1320 px.
- KPI row: six cards pulled 64 px up over the hero edge; three columns under 1180 px, two under 640 px.
- Overview: "Review next" beside a stack of "Named in communications" and "The window matters"; one column under 1040 px.
- Review: one card with temporal lanes, filters, the result count and the four downloads; below it the register (left) and the selected-communication dossier (right). On wide screens the dossier is sticky with its own scroll; under 1100 px it stacks below the register.
- Then the source and coverage ledger, the method and limits card and a footer with the reference.
- Spacing follows 4/8 px steps (4, 8, 16, 24, 40) with 12, 14 and 20 px insets inside dense components.
- Under 640 px the lanes and downloads become two-column grids with 44 px targets, the register keeps a 560 px minimum width and scrolls inside its card with edge shadows, and the page never scrolls sideways at 390 px.

## Print

`@page` is A4 with 14/12/16 mm margins and a running footer (title, client, reference, provenance, "Page n of m"). Print text keeps an 11 px floor. Print keeps colours exactly, hides the section links, Print button, filters, downloads, pager and review links, renders every matching register row, keeps the selected dossier, removes scroll caps, avoids breaking KPI cards, steps, ledger entries and rows, and starts the source ledger on a new page. The PDF is the browser's print of this same HTML.

## Elevation and depth

Cards and KPI cards share one soft shadow (`0 1px 2px` plus `0 8px 24px`, both at low opacity). Depth otherwise comes from the paper/sheet contrast and fine borders. Print drops shadows.

## Shapes

Controls and download links use a 10 px radius, cards 16 px, pills and temporal lanes are fully rounded, step numbers are circles. Borders are 1 px.

## Components

- **Review status card** (hero aside): "Partial coverage", "Review needed", "No communications returned" or "Nothing Active when read", with a one-line breakdown. It summarises evidence; it is not a workload-health verdict.
- **Distribution bar**: in-scope records by type and native state (Active incidents, Active maintenance, Resolved, Unknown), with legend counts and an accessible label.
- **KPI cards**: In scope, Active when read, Updated in window, Future maintenance, Resource associations, Incomplete sources (amber when above zero).
- **Review next**: up to five numbered steps derived from the counts; each opens the matching lane, state filter or the ledger.
- **Named in communications**: top six published services and regions as labelled bars with values.
- **Temporal lanes**: pressed-state buttons with counts (`aria-pressed`); the selected lane is yellow with a charcoal count.
- **Register**: sortable headers (`aria-sort`), title buttons with `aria-controls`/`aria-pressed`, type pill and tracking ID under the title, impact start and last update as date over time (no mid-token wrap), resource counts right-aligned, selected row tinted yellow.
- **Dossier**: type and state pills, title, field grid, published text, plain-text and original-record disclosures, resource associations shown as name, resource group and type with an Azure portal link and the full ID wrapping only after "/", then unknowns and receipt IDs.
- **Source ledger**: a strip of status counts, then one disclosure per receipt; incomplete receipts are tinted amber.
- **Simulated banner**: hatched amber strip whenever provenance is not LIVE.

## Do's and Don'ts

### Do:

- **Do** keep yellow for identity and selection, with charcoal lettering.
- **Do** keep event-type and state meaning in text, not only in colour.
- **Do** keep every in-scope record, receipt and uncertainty reachable on every viewport.
- **Do** preserve visible focus, native controls and focus transfer to the refreshed dossier.

### Don't:

- **Don't** put white lettering on yellow or turn a complete receipt into a green health verdict.
- **Don't** draw an empty logo frame or embed real customer branding in generic source.
- **Don't** add external fonts, images, CDNs or network calls.
- **Don't** describe these source-sampled colours as an official customer brand specification or this template as live evidence.
