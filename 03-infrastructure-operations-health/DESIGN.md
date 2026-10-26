---
name: "Infrastructure operations"
description: "Source-qualified evidence on cool technical paper."
colors:
  paper: "#eef2f1"
  sheet: "#ffffff"
  ink: "#18312e"
  muted: "#526660"
  petrol: "#163d3a"
  line: "#c8d2cd"
  wash: "#e7efeb"
  critical: "#9e302e"
  critical-wash: "#fbeaea"
  warning: "#875022"
  warning-wash: "#f6eadb"
  unknown: "#535d68"
  unknown-wash: "#e9edf0"
  blue: "#355f9c"
  purple: "#745383"
  focus: "#156dc0"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "32px"
    fontWeight: 650
    lineHeight: 1.13
    letterSpacing: "-0.025em"
  headline:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "21px"
    fontWeight: 650
    lineHeight: 1.25
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "17px"
    lineHeight: 1.3
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  stamp:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.6
  identifier:
    fontFamily: "ui-monospace, Consolas, monospace"
    fontSize: "11px"
    lineHeight: 1.5
rounded:
  square: "0"
  control: "3px"
  stamp: "2px"
spacing:
  compact: "8px"
  small: "12px"
  base: "16px"
  section: "24px"
  group: "28px"
components:
  button-primary:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    padding: "7px 11px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 11px"
  button-compact:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "6px 9px"
  input-search:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 11px"
  scope-tab:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "3px 3px 0 0"
    padding: "8px 17px"
  scope-tab-selected:
    backgroundColor: "{colors.petrol}"
    textColor: "{colors.sheet}"
    rounded: "3px 3px 0 0"
    padding: "8px 17px"
  stamp-review:
    backgroundColor: "{colors.warning-wash}"
    textColor: "{colors.warning}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "2px 7px"
  stamp-unknown:
    backgroundColor: "{colors.unknown-wash}"
    textColor: "{colors.unknown}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "2px 7px"
  stamp-observed:
    backgroundColor: "{colors.wash}"
    textColor: "{colors.petrol}"
    typography: "{typography.stamp}"
    rounded: "{rounded.stamp}"
    padding: "2px 7px"
  ledger-sheet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
---

# Design System: Infrastructure operations

## Overview

**Creative North Star: "Operations dispatch ledger"**

Cool technical paper, petrol ink and ruled registers make infrastructure evidence readable without suggesting certainty the sources cannot support. Square file tabs and compact status stamps provide personality through filing and annotation, not dashboard decoration.

Design for an operator and customer reviewing a laptop in a normally lit meeting room: readable system type, aligned measurements, explicit labels and persistent context. The world is customer-neutral and self-contained; it uses no external fonts, imagery or libraries.

This is the finished scenario-local system extracted from the CSS, markup and JavaScript of `REPORT_HTML` in `generate-infrastructure-operations-report.py`, including its opening five-block direction contract. Frontmatter is normative; `.impeccable/design.json` supplies preview snippets and extensions, not a second token authority.

**Key Characteristics:**
- Cool paper and restrained petrol ink.
- Ruled sheets, square-bodied tabs and compact status stamps.
- System sans with tabular measurements and monospace identifiers.
- Visible source, units, recorded time, coverage and unknowns.
- Immediate, read-only interactions within a dated offline snapshot.

## Colors

A low-chroma paper-and-ink foundation carries sparse semantic status color and three categorical trace inks.

### Primary
- **Petrol ink** (`petrol`): file index, selected controls, resource links, observed stamps and the first recorder trace.
- **Focus blue** (`focus`): keyboard outlines only; distinct from the blue comparison trace.

### Secondary
- **Recorder blue** (`blue`) and **recorder plum** (`purple`): second and third resource traces, paired with named legends. These are categorical inks, not status or brand accents.

### Tertiary
- **Critical red / pale critical wash** (`critical`, `critical-wash`): critical evidence and source-error emphasis.
- **Review amber / pale review wash** (`warning`, `warning-wash`): review and warning stamps, never an overall health grade.

### Neutral
- **Cool technical paper** (`paper`) surrounds **white sheets** (`sheet`).
- **Deep green-black ink** (`ink`) carries primary text; **muted annotation ink** (`muted`) carries qualifications, labels and secondary context.
- **Register rule** (`line`) separates sections; **pale petrol wash** (`wash`) supports observed stamps and neutral button hover.
- **Unknown slate / pale slate wash** (`unknown`, `unknown-wash`) keep unknown, partial and error states legible without presenting them as healthy.

**The Label Before Hue Rule.** Every evidence state is named; trace color identifies a resource, not a health grade.

Sidecar tonal ramps are synthesized preview strips, not shipped tokens; do not apply their values to the report.

## Typography

**Display and body font:** Segoe UI with system-ui and sans-serif fallbacks. **Identifier font:** ui-monospace with Consolas and monospace fallbacks.

The hierarchy is compact and technical, not a display-font pairing or mathematical scale. Use the frontmatter roles; dense register text and annotations step down without replacing readable body copy.

### Hierarchy
- **Display:** page heading; compact layout sizes are recorded below.
- **Headline:** section headings; the inspector uses a slightly smaller heading (20px).
- **Title:** subordinate headings; preserve the built heading semantics rather than prescribing an unobserved custom weight.
- **Body:** explanatory copy and normal controls; the main subtitle is bounded (72ch).
- **Label:** field labels; register text is compact (13px), with smaller table headings and stamps (12px).
- **Stamp:** semibold, sentence-case state names; the dated snapshot label is the deliberate uppercase exception.
- **Identifier:** wrapping resource IDs; event timestamps use the same monospace stack at a slightly larger size (12px).

Measurements, counts, dates and bin readouts use `font-variant-numeric: tabular-nums`. Do not apply numeric styling by stripping units or source context.

**The Measurement Context Rule.** Tabular numbers stay attached to visible units, measurement scope and recorded time.

## Layout

Use a filing index beside a working sheet, with evidence grouped by rules and aligned columns. The workspace has a bounded width (1740px) and base padding (32px 36px 48px); the desktop index occupies a narrow track (190px). Repeated spacing tokens describe the built rhythm, not a requirement to round every local gutter to one scale step.

The fleet register and inspector share one ruled sheet: register-to-inspector columns are `minmax(0,1.7fr) minmax(300px,1fr)`. The recorder follows with section spacing (24px); review and event sheets share a lower row (`1.15fr 1fr`, gap 24px). Register and source tables retain horizontal scrolling rather than squeezing evidence columns (minimum widths 570px and 680px).

### Responsive behavior
- **Wide desktop (min-width 1600px):** workspace side padding expands (44px); the register/inspector ratio becomes `1.9fr` with a wider inspector minimum (330px).
- **Laptop (max-width 1190px):** index narrows (165px), workspace padding becomes (26px 24px), inspector stacks beneath the register, filters use three columns and the owner field spans two. Display type reduces (29px).
- **Compact (max-width 780px):** index becomes a static, wrapping horizontal header; workspace padding becomes (23px 16px 36px). Search and reset span the two-column filters. Review and event sheets stack; chart fields become full-width, legends and bin inspection stack, and exports wrap. Display and section headings reduce (28px and 19px). Chart height reduces (255px to 225px).
- **Print:** hide navigation and interactive controls, flatten the layout, use white paper and retain the dated evidence and inspector. This is not a replacement for complete machine exports.

## Elevation & Depth

There are no shadows, gradients, animated entrances or floating cards. White sheets, pale annotation fields and thin rules provide depth. The masthead uses a stronger petrol rule (2px); other structural boundaries use thin rules (1px). Focus outlines are interaction feedback, not elevation.

**The Ruled Sheet Rule.** Use borders and tonal fields to group evidence; do not substitute shadows or floating tiles for the ledger.

State changes are immediate. Scrolling is automatic rather than animated; the built reduced-motion query disables transitions and smooth scrolling.

## Shapes

Sheets and registers remain rectangular. Controls use minimal corner relief; status stamps use the smaller radius. Hosting tabs have only top-corner relief (`3px 3px 0 0`) and meet the register without a bottom border. Do not reinterpret square file tabs as pills.

Borders, text labels and background fields express state. Recorder circles are legitimate data markers for isolated observations, not a forbidden rounded UI device.

## Components

### Buttons and fields
Quiet, bordered native controls. Normal controls retain a minimum height (40px); contextual export/show-more actions use the built compact height (35px). Primary export uses petrol with white text and semibold weight; secondary controls use white with ink text. Hover uses tonal fill, active uses the built pressed fill, and disabled buttons reduce opacity (.58) without implying success. Keyboard focus is a clear outline (3px) with an offset (3px).

Search and selects have persistent labels, not placeholder-only identification. The skip link becomes visible on focus. Hosting and event-provenance controls expose their selected state through `aria-pressed`; hosting tabs are filing controls, not interchangeable decorative chips.

### Navigation and ruled sheets
The petrol index uses a pale active entry and restrained hover/focus treatment. Its anchors select report sections; compact layouts wrap them rather than hiding navigation. Containers use white backgrounds and ruled headers, not detached metric cards.

The fleet register separates inspection from comparison: resource-name buttons open evidence; native checkboxes pin up to three resources. Selection has a pale row fill. Empty results say what is absent and offer a next check without a reassuring score.

### Optional company logo
The masthead's right-hand group contains a 180px by 56px bordered logo frame
above the dated snapshot stamp. An empty configuration displays exactly
`logo company`; an optional validated PNG/JPEG is contained without changing
its aspect ratio or the ledger palette. On compact screens the frame narrows
to 128px and wraps alongside the still-visible date stamp. The asset is
embedded offline, with descriptive alternative text and no external requests.

### Resource inspector
A pale annotation sheet holds ownership, native state, source-qualified measurements and expandable evidence. Changing the recorded metric refreshes both inspector and recorder. Resource selection hands keyboard focus to the inspector heading; comparison and pin actions restore control focus after redraw. IDs wrap rather than truncating the evidence. “Open resource” is an explicit external portal link, not an embedded live integration.

Arc machines add a separately labeled administration assessment, exact native
agent/OS metadata, baseline provenance/validity and a ruled extension list.
Configured and instance-view versions and the two upgrade settings stay distinct.
Unknown is visible, not a new guest-health grade. The extra Arc administration
filter combines with existing hosting/type/owner/state/search filters; search
also matches safe extension metadata. Resource/complete exports retain every
matched child record, not just visible register rows. Long metadata wraps
inside the inspector without changing the palette or company-logo placeholder.

### Time recorder
Petrol, blue and plum traces retain named source/unit/grain/coverage legends. Solid lines follow the recorded primary aggregation; optional dashed lines show supplied source maxima only. Missing or noncontiguous bins remain gaps. Isolated samples remain visible as small filled primary markers or hollow maximum markers (radius 2.8px). A keyboard-operable range control inspects recorded bins; it does not interpolate values.

### Review, events, coverage and exports
Owner reviews are evidence-linked register entries, not remediation buttons. Event provenance keeps native events separate from local observations. Source rows distinguish complete requests, missing monitoring, unsupported metrics and errors.

Native ARM alert titles and source/details wrap without truncation, including on mobile. Review-title flex children can shrink; horizontal table scrolling is local to the table, never hidden by a page-wide overflow mask.

Exports preserve the evidence, not just the visible page: filtered CSVs carry snapshot provenance, collection date and window; trace CSV additionally carries unit, source, aggregation, grain and observed/expected coverage. Complete JSON is the complete embedded snapshot. Export and selection feedback uses a polite live region; no live polling, synthetic deployment claim or composite health score belongs in this system.

## Do's and Don'ts

### Do:
- Do keep units, source, recorded time and unknown labels adjacent to measurements.
- Do use ruled sheets, aligned registers and compact named status stamps.
- Do preserve keyboard focus and announce local interaction outcomes.
- Do keep component previews free of invented telemetry, brands and deployment claims.

### Don't:
- Don't replace evidence with decorated scores or imply that an observed state certifies health.
- Don't turn missing data into zero, connect gaps or invent maxima.
- Don't introduce gradients, floating card grids, pill-shaped file tabs or external assets.
- Don't label source replay as live validation or publish private replay screenshots as product assets.
