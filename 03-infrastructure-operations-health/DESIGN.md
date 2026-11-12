---
name: "Infrastructure operations"
description: "Verdict-first infrastructure evidence in the Azure SRE Agent report family, in petrol on cool paper."
colors:
  paper: "#eef2f1"
  sheet: "#ffffff"
  ink: "#18312e"
  muted: "#526660"
  petrol: "#163d3a"
  petrol-2: "#24534d"
  line: "#d0dad5"
  line-soft: "#e3e9e6"
  wash: "#e4eeea"
  soft: "#f3f6f5"
  link: "#155e55"
  focus: "#156dc0"
  critical: "#b42318"
  critical-bg: "#fee4e2"
  critical-bar: "#d92d20"
  high: "#b93815"
  high-bg: "#ffead5"
  high-bar: "#ef6820"
  medium: "#93370d"
  medium-bg: "#fef0c7"
  medium-bar: "#f79009"
  low: "#175cd3"
  low-bg: "#d1e9ff"
  low-bar: "#2e90fa"
  info: "#344054"
  info-bg: "#eaecf0"
  info-bar: "#98a2b3"
  observed: "#0f5a50"
  observed-bg: "#dcefe9"
  observed-bar: "#3f9e8b"
  trace-2: "#355f9c"
  trace-3: "#745383"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, -apple-system, "Helvetica Neue", sans-serif'
    fontSize: "42px"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.3
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
  table:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  kpi:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "38px"
    fontWeight: 700
    lineHeight: 1
  identifier:
    fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace'
    fontSize: "12.5px"
    lineHeight: 1.55
rounded:
  card: "12px"
  control: "8px"
  verdict: "16px"
  pill: "999px"
spacing:
  compact: "8px"
  small: "12px"
  base: "16px"
  card: "20px"
  section: "44px"
components:
  button-primary:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    padding: "7px 16px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  input-search:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  segmented-selected:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.sheet}"
    rounded: "7px"
    padding: "0 14px"
  stamp-review:
    backgroundColor: "{colors.medium-bg}"
    textColor: "{colors.medium}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  stamp-unknown:
    backgroundColor: "{colors.info-bg}"
    textColor: "{colors.info}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  stamp-observed:
    backgroundColor: "{colors.observed-bg}"
    textColor: "{colors.observed}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.card}"
---

# Design System: Infrastructure operations

## Overview

**North Star: "Verdict first, evidence intact"**

The report is a member of the Azure SRE Agent report family: a slim top bar, a verdict band, KPI cards on its edge, then white cards on a light neutral ground. This scenario keeps its own petrol-on-cool-paper palette and one signature move: **Unknown is drawn hollow or hatched wherever it appears**, so missing evidence never reads as zero or as healthy.

Design for an operator and a customer reviewing a laptop in a normally lit meeting room, and for a printed A4 copy of the same file: readable system type, aligned measurements, explicit labels and persistent context. The report is customer-neutral and self-contained; it uses no external fonts, imagery, libraries or network requests.

This record describes the shipped CSS, markup and JavaScript of `REPORT_HTML` in `generate-infrastructure-operations-report.py`, including its opening direction comment. Frontmatter is normative. `.impeccable/design.json` is an older generated preview sidecar of the previous operations-ledger layout; regenerate it before relying on its previews.

**Key characteristics:**
- Petrol verdict band, white cards, cool paper ground.
- Shared Azure SRE Agent severity colours for stamps and bars.
- System sans with tabular numbers; monospace only for identifiers, timestamps and raw evidence.
- Visible source, units, recorded time, coverage and unknowns next to every number.
- Immediate, read-only interactions within a dated offline snapshot.

## Colors

A low-chroma paper-and-ink foundation, a petrol brand band, the family's shared severity palette and three categorical trace inks.

### Primary
- **Petrol** (`petrol`): verdict band, primary button, selected segmented controls, resource links and the first recorder trace. Hover uses `petrol-2`.
- **Focus blue** (`focus`): keyboard outlines only; distinct from the blue trace.

### Severity and state (shared with the report family)
- **Critical** text `critical` on `critical-bg`, bar `critical-bar`.
- **High** text `high` on `high-bg`, bar `high-bar`.
- **Medium** (the scenario's Review and Warning) text `medium` on `medium-bg`, bar `medium-bar`.
- **Low** text `low` on `low-bg`, bar `low-bar`.
- **Info / Unknown** text `info` on `info-bg`, bar `info-bar`. Unknown, Not collected and Not supported stamps use a hollow dot; Unknown in bars and in the hero distribution uses a grey hatch.
- **Observed / Complete** text `observed` on `observed-bg`, bar `observed-bar`. Observed is a collected state, never a health grade.

### Categorical
- **Trace inks** `petrol`, `trace-2`, `trace-3`: first, second and third pinned recorder traces, always paired with a named legend.

### Neutral
- **Cool paper** (`paper`) surrounds **white cards** (`sheet`). `soft` fills table headers, segmented tracks and bar tracks; `wash` marks the current nav item and pressed states.
- **Ink** (`ink`) carries primary text; **muted** carries qualifications, labels and secondary context (at least 5.4:1 on every light surface).
- **Rules** (`line`, `line-soft`) separate card regions and table rows.

**The Label Before Hue Rule.** Every evidence state is named; colour reinforces a label and never replaces it.

## Typography

**Font:** Segoe UI with system fallbacks for everything; `ui-monospace` / Cascadia Mono / Consolas only for ARM IDs, event timestamps and raw evidence JSON. No embedded or remote fonts.

### Hierarchy
- **Display:** the single H1 in the verdict band (42px; 36px under 900px; 32px on phones; 30px in print).
- **Headline:** section H2 (22px), each followed by a one-line reason to read the section (14px, muted, at most 75 characters per line).
- **Title:** card headings (17px); the inspector heading is 20px.
- **Body:** 15px prose; the hero sentence is 18px.
- **Table:** registers at 14px with 13px secondary lines; uppercase 12px column headings.
- **KPI:** 38px tabular numbers with a 14px label and a 13px muted qualifier.

All counts, measurements, dates and bin readouts use `font-variant-numeric: tabular-nums`.

**The Measurement Context Rule.** Tabular numbers stay attached to visible units, measurement scope and recorded time.

## Layout

A sticky 60px top bar (optional company logo, Azure SRE Agent mark, section nav with live counts, Read-only chip, Print / PDF), a full-width petrol band, then a centred 1320px column with 40px side padding (fluid down to 16px).

Reading order:
1. **Verdict band:** H1, one sentence with the key counts, chips for provenance (LIVE or SIMULATED), collection time, window and bin width, scope; a verdict card (Action required, Needs attention, Coverage gaps, No review flagged or No resources collected) with its breakdown; the Review / Unknown / Observed distribution bar.
2. **KPI cards** (six, overlapping the band by 64px): resources collected, resources to review, no runtime evidence, owner checks, native alerts, source requests complete.
3. **Snapshot notice**, then **At a glance:** owner checks by reason and fleet by resource type as labelled horizontal bars with values.
4. **Fleet register:** filters, hosting segmented control, live summary, sortable register and resource inspector in one card.
5. **Time recorder**, then **Owner review** (what to check next, most severe first) beside the **Event log**.
6. **Evidence coverage** (status bars and source ledger), **exports**, **Method and limits**, footer.

Spacing follows a 4/8px rhythm: 8, 12, 16, 20 and 44px between sections.

### Responsive behaviour
- **Up to 1240px:** nav items tighten.
- **Up to 1180px:** the top-bar nav hides; the inspector stacks under the register; filters use three columns with full-width search.
- **Up to 900px:** the verdict card stacks under the heading; Owner review and Event log stack; coverage bars stack above their export.
- **Up to 640px:** KPI cards use two columns; filters use two columns; Print / PDF becomes an icon button with an accessible name; bars put the track under the label. No horizontal page overflow at 390px: wide tables scroll inside their card with edge-shadow cues, and IDs wrap only at `/`.
- **Print (A4):** `@page` margins 14/12/16mm with a running footer (title, collection time, provenance) and page numbers. Controls, nav and buttons are hidden; colours are kept (`print-color-adjust: exact`); cards, rows and list items avoid breaking. The fleet register, owner review and event log print every matching row; the source ledger prints only results that are not complete and says so, because every result stays in the CSV and complete JSON exports.

## Elevation and depth

White cards carry a 1px rule and a soft two-layer shadow (`0 1px 2px` plus `0 6px 18px -8px`, petrol-tinted). Print removes shadows. No gradients except the Unknown hatch and the table-edge scroll cues; no glass, glow or animated entrances. State changes are immediate; `prefers-reduced-motion` keeps it that way.

## Shapes

Cards 12px, controls 8px, the verdict card 16px; stamps, chips, nav counts and bar tracks are fully rounded. Segmented controls (hosting scope, event provenance) use a soft track with a petrol selected segment.

## Components

### Top bar
Logo frame (132 by 40px; 100 by 34px on phones), the Azure SRE Agent mark, section links with live counts (`aria-current="location"` follows the section in view), the Read-only chip and the primary Print / PDF button.

### Optional company logo
The frame sits at the left of the top bar. An empty configuration displays exactly `logo company`; an optional validated PNG/JPEG is contained without changing its aspect ratio or the palette. The asset is embedded offline, with descriptive alternative text and no external requests. The dated provenance and collection chips stay visible in the verdict band, including on phones.

### Verdict band and KPI cards
Counts come straight from the snapshot summary; nothing is scored or weighted. KPI numbers take the severity text colour only when the count carries meaning (review, unknown, critical or partial/error sources).

### Fleet register and inspector
Search, type, state, owner and Arc administration filters with persistent labels; Reset; the hosting segmented control; a live summary of the current view. Column headers are sort buttons with `aria-sort`; missing measurements always sort last. Resource names open the inspector and hand it keyboard focus; checkboxes pin up to three resources for the recorder. Each row shows name, hosting, type and resource group; the inspector shows facts, the selected metric, Pin / Resource JSON / Open in Azure portal, the full ARM ID (wrapped only at `/`) and expandable Arc administration, measurements, signals and native state.

### Time recorder
Petrol, blue and plum traces keep named source/unit/grain/coverage legends. Solid lines follow the recorded primary aggregation; optional dashed lines show supplied source maxima only. Missing or noncontiguous bins remain gaps; isolated samples stay visible as small markers. A keyboard-operable range control inspects recorded bins; it never interpolates.

### Owner review, event log and coverage
Owner review items are evidence-linked checks, most severe first, with the resource as a button and the owner tag; no remediation runs from the report. Native alert-rule titles show the rule name, rule kind and resource group, with the full ID beneath in the event log. Event provenance keeps native events separate from local observations. Coverage summarises results by status before the ledger; complete, partial, error, not collected, not supported and not configured stay distinct.

### Exports
Filtered CSVs carry snapshot provenance, collection date and window; the trace CSV adds unit, source, aggregation, grain and coverage. Complete JSON is the complete embedded snapshot. Export, sort and selection feedback use a polite live region.

## Do's and Don'ts

### Do
- Keep units, source, recorded time and Unknown labels next to measurements.
- Use the shared severity colours, named stamps and labelled bars with values.
- Preserve keyboard focus, visible focus rings and announced interaction outcomes.
- Keep component previews free of invented telemetry, brands and deployment claims.

### Don't
- Replace evidence with a composite health score or imply that Observed certifies health.
- Turn missing data into zero, connect gaps or invent maxima.
- Add emoji icons, gradient text, glass, neon or decorative charts, or nest cards inside cards.
- Load external fonts, scripts or images, or label source replay as live validation.
