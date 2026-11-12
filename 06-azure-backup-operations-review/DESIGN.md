---
name: Azure Backup operations review
description: A coverage-first operations workpaper in customer-selected yellow and charcoal, in the Azure SRE Agent report family.
colors:
  primary: "#FBC807"
  charcoal: "#1E1C18"
  bar: "#151411"
  canvas: "#F2F4F5"
  sheet: "#FFFFFF"
  ink: "#24272B"
  muted: "#535D66"
  line: "#D5DADF"
  field: "#6C7680"
  wash: "#F6F8F9"
  link: "#18577D"
  critical: "#B42318"
  critical-wash: "#FEE4E2"
  critical-bar: "#D92D20"
  high: "#B93815"
  high-wash: "#FFEAD5"
  high-bar: "#EF6820"
  low: "#175CD3"
  low-wash: "#D1E9FF"
  low-bar: "#2E90FA"
  info: "#344054"
  info-wash: "#EAECF0"
  info-bar: "#98A2B3"
  ok: "#067647"
  ok-wash: "#DCFAE6"
  ok-bar: "#17B26A"
typography:
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "44px"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "-.02em"
  heading:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.25
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  kpi:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "40px"
    fontWeight: 700
    lineHeight: 1
  evidence:
    fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace'
    fontSize: "12.5px"
    lineHeight: 1.55
rounded:
  control: "8px"
  card: "12px"
  pill: "999px"
spacing:
  compact: "8px"
  field: "14px"
  group: "16px"
  sheet: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  unknown:
    backgroundColor: "{colors.info-wash}"
    textColor: "{colors.info}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
  kpi-card:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.card}"
    padding: "16px 18px"
---

# Design System: Azure Backup operations review

## Overview

**Creative North Star: "The backup shift workpaper"**

The implemented system is a neutral evidence sheet under a charcoal verdict
band, with the customer-selected yellow kept to the plaque, the band's top rule,
the provenance chip and the primary full-file action. Since 2026-11-12 it shares
the Azure SRE Agent report family's frame (slim bar, verdict band, KPI cards,
white cards on a light ground, shared severity colours) while keeping its own
brand and evidence rules. It is an operating surface, not a score dashboard.
Literal dates, native states and readable source disclosure carry its authority.

The palette is binding user direction, not a claim of an official brand guide.
The default customer plaque is deliberately CLIENTE, never a copied real logo.
No visual tournament, generated illustration or delegated agents were used for
this precisely bounded, already-pinned identity.

**Key Characteristics:**

- A verdict and counts first, each qualified by the window, provenance and Unknown denominator.
- Brand yellow independent of named operational severity.
- Familiar native controls and inline source disclosure.
- System typography and full offline behavior.

## Colors

Yellow and charcoal are supplied-asset pixel evidence; neutral sheets support
long-form review. Severity uses the report family's shared pairs (text on wash,
plus a bar colour): Error and Failed use critical, Warning and partial reads use
high, Attention and InProgress use low (blue), Unknown and Cancelled use info,
Completed and complete reads use ok. Medium is not used. Each state keeps its
native word next to the colour.

**The Brand Is Not Severity Rule.** Yellow marks branding, the provenance chip
and the primary full-file action. It never means a warning, successful backup or
grade; warnings are orange-red (`high`), never brand yellow.

**The Dark-on-Yellow Rule.** The brand field uses charcoal text, not white.
All evidence uses contrast-preserving text on neutral or named semantic washes.

## Typography

Segoe UI with system sans fallbacks is the only interface family, with
tabular numerals everywhere. Native IDs and dates use the sans at 13px; monospace
is reserved for JSON/hash disclosure rather than applied as a technical costume.

The H1 is up to 44px/1.1 (clamped from 30px), section headings 22px/1.25, card
headings 19px, subheadings 17px/1.35, body 16px/1.5, KPI figures 40px and
table/note text 14px (small table lines 13px). At <=640px KPI figures are 30px.
Prose is constrained to 75ch. Data ledgers may be wider.

## Layout

A slim charcoal bar carries the CLIENTE plaque (or the customer logo), the
"Azure SRE Agent" mark, section links, a Read-only chip and Print / PDF; it is
sticky from 1000px. The verdict band follows: H1, one key-numbers sentence,
provenance/reference/window/scope chips, a verdict card and the human-review
queue by severity as a labelled distribution bar. Six KPI cards overlap the
band's lower edge. Below sit the SIMULATED banner (non-live data only), the
unknown-history notice, two cards for the UTC window and the complete files,
two cards for prioritised next steps and Backup records by native state, then
the job ledger, human review register, item/history coverage, source ledger and
business limits. Content is at most 1320px wide with 16-40px side padding.

At <=1000px the verdict card stacks under the title. At <=640px the KPI grid is
two columns, side padding is 12px, cards use 14px side padding, filters stack
and ledger records become labeled blocks. No body-level horizontal overflow was
observed at 1440px, 768px, 390px or 320px in the bounded synthetic pass.

## Elevation & Depth

Only KPI cards carry a soft offset shadow, because they sit across the band edge.
Other cards are white with a 1px border on the neutral ground. No gradients or
glass. Focus is a visible 3px outline with 2px offset (yellow on charcoal, blue
on light surfaces), not decorative glow.

## Shapes

Cards and ledgers have 12px corners, controls 8px, state labels are pills.
Color never substitutes for the native state word.

## Components

### Actions and fields

Native buttons, inputs and selects have minimum 44px height and 8px/14px padding.
Primary download uses dark-on-yellow. Secondary actions are neutral. Hover,
active, disabled and keyboard-focus states are implemented. Download and print
actions remain disabled until successful evidence rendering.

### Navigation

Light links on the charcoal bar, with wrapping mobile rows, explicit focus and a
subtle hover. Navigation uses section anchors, not hidden routes. The skip link
lands on the explicitly focusable main evidence surface.

### Verdict, KPIs and next steps

The verdict names the most severe review class present (failures, warnings,
unfinished work or blind spots) or says nothing is flagged; it is a reading of
native states, never a score. "What to do next" lists one step per severity with
a button that filters the review register, then the human decision step.

### State labels

Native text remains visible next to named category color. Unknown and Cancelled
use the info pair; InProgress uses low. Completed is a native state, not a
success rate or recovery assertion. Partial/denied sources remain distinct.

### Ledger disclosure

Ledgers are tables styled as grid rows (with explicit table roles). Each record's
`details`/`summary` evidence and its full native IDs sit on a full-width line
under the record; IDs wrap only after `/` or `;`. JSON is always rendered with
textContent. Desktop ledgers become labeled mobile records. Job pagination is 40
visible records and can be ordered by review priority, newest, oldest or source
order; it never narrows downloads. The human review register is ordered by
severity and filterable. Printing (A4 landscape, colours kept, footer with title,
provenance, reference UTC and page numbers) renders every matching job and opens
disclosures, without clipping source text or printing interactive buttons.

## Do's and Don'ts

- Do preserve the supplied yellow/charcoal identity in generic and private copies.
- Do keep dates, uncertainty and source evidence beside every count and verdict.
- Do use full native item/vault identities and distinct named semantic states.
- Do keep mobile controls keyboard-native and at least 44px high.
- Don't use brand yellow as operational warning severity.
- Don't invent scores, success rates, incident outcomes or decorative charts.
- Don't turn a logo, source presence or a blank ledger into health evidence.
- Don't add external assets, libraries or live polling, and never link source text; the only remote link is an explicit "Vault in Azure portal" link built from an approved vault ID.
