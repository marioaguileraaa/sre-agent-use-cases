---
name: Azure Backup operations review
description: A coverage-first operations workpaper in customer-selected yellow and charcoal.
colors:
  primary: "#FBC807"
  charcoal: "#1E1C18"
  canvas: "#F2F4F5"
  sheet: "#FFFFFF"
  ink: "#24272B"
  muted: "#535D66"
  line: "#CCD2D7"
  field: "#6C7680"
  wash: "#F6F8F9"
  error: "#A51E29"
  error-wash: "#FFF0F1"
  warning: "#854400"
  warning-wash: "#FFF4E9"
  unknown: "#4F5971"
  unknown-wash: "#F0F2F8"
  complete: "#276442"
  complete-wash: "#EEF7F1"
  active: "#175A83"
  active-wash: "#EDF5FA"
typography:
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "30px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-.02em"
  heading:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.3
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  evidence:
    fontFamily: "Consolas, monospace"
    fontSize: "12px"
    lineHeight: 1.6
rounded:
  control: "3px"
spacing:
  compact: "8px"
  field: "12px"
  group: "16px"
  sheet: "28px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  button-secondary:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  unknown:
    backgroundColor: "{colors.unknown-wash}"
    textColor: "{colors.unknown}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
---

# Design System: Azure Backup operations review

## Overview

**Creative North Star: "The backup shift workpaper"**

The implemented system is a neutral evidence sheet inside a charcoal mast and
sparse customer-selected yellow navigation. It is an operating surface, not a
score dashboard. Literal dates, native states and readable source disclosure
carry its authority.

The palette is binding user direction, not a claim of an official brand guide.
The default customer plaque is deliberately CLIENTE, never a copied real logo.
No visual tournament, generated illustration or delegated agents were used for
this precisely bounded, already-pinned identity.

**Key Characteristics:**

- Neutral ruled ledgers rather than nested metric cards.
- Brand yellow independent of named operational severity.
- Familiar native controls and inline source disclosure.
- System typography and full offline behavior.

## Colors

Yellow and charcoal are supplied-asset pixel evidence; neutral sheets support
long-form review. Error, warning, Unknown, completed and active states have
separate text labels, foregrounds and restrained washes.

**The Brand Is Not Severity Rule.** Yellow marks branding/navigation and the
primary full-file action. It never means a warning, successful backup or grade.

**The Dark-on-Yellow Rule.** The brand field uses charcoal text, not white.
All evidence uses contrast-preserving text on neutral or named semantic washes.

## Typography

Segoe UI with system sans fallbacks is the only interface family. Native IDs,
dates and JSON use compact evidence text; monospace is reserved for code/hash/
source disclosure rather than applied as a technical costume.

The desktop mast is 30px/1.2, section headings 24px/1.3, subheadings 18px/1.35,
body 16px/1.5 and table/note text 14px. At <=640px the mast is 26px and section
headings 21px. Most prose is constrained to 75ch. Data ledgers may be wider.

## Layout

The main canvas is at most 1552px wide with 32px desktop side padding and 28px
evidence-sheet padding. The mast combines a 190px client plaque, flexible title
and right-hand provenance stamp. The window/evidence sheet is a 1.5fr/1fr
composition with a four-column count strip, not an oversized hero metric.

At <=1000px the stamp moves beneath the title and the introductory columns
stack. At <=640px the mast is one column, main side padding is 12px, sheets use
16px side padding, filters stack and table records become labeled blocks.
Controls and wrapped pager groups stay within 320px. No body-level horizontal
overflow was observed at 1440px, 390px or 320px in the bounded synthetic pass.

## Elevation & Depth

No shadows, gradients or glass. White sheets, neutral background, ruled borders
and semantic washes provide grouping. Focus is a visible 3px outline with 3px
offset, not decorative glow.

## Shapes

Evidence sheets and ledgers are square. Controls and semantic state labels have
3px corners and 1px borders. Color never substitutes for the native state word.

## Components

### Actions and fields

Native buttons, inputs and selects have minimum 44px height and 8px/12px padding.
Primary download uses dark-on-yellow. Secondary actions are neutral. Hover,
active, disabled and keyboard-focus states are implemented. Download actions
remain disabled until successful evidence rendering.

### Navigation

Plain dark links on the yellow band, with wrapping mobile rows, explicit focus
and a darker yellow hover. Navigation uses section anchors, not hidden routes.
The skip link lands on the explicitly focusable main evidence surface.

### State labels

Native text remains visible next to named category color. Unknown and Cancelled
use the Unknown vocabulary; InProgress uses active. Completed is a native state,
not a success rate or recovery assertion. Partial/denied sources remain distinct.

### Ledger disclosure

Inline native `details`/`summary` keeps source and normalized evidence together.
JSON is always rendered with textContent. Desktop ledgers become labeled mobile
records. Job pagination is 40 visible records; it never narrows downloads.
Printing renders every matching job and opens disclosures, without clipping
source text or printing interactive buttons.

## Do's and Don'ts

- Do preserve the supplied yellow/charcoal identity in generic and private copies.
- Do keep dates, uncertainty and source evidence visible before conclusions.
- Do use full native item/vault identities and distinct named semantic states.
- Do keep mobile controls keyboard-native and at least 44px high.
- Don't use brand yellow as operational warning severity.
- Don't invent scores, success rates, incident outcomes or decorative charts.
- Don't turn a logo, source presence or a blank ledger into health evidence.
- Don't add external assets, libraries, live polling or remote links to source text.
