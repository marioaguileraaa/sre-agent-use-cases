---
name: "CLIENTE Service Health review"
description: "A readable yellow/charcoal frame around neutral, source-qualified evidence sheets."
colors:
  yellow: "#fbc807"
  charcoal: "#1e1c18"
  paper: "#f1f2f3"
  sheet: "#ffffff"
  ink: "#252722"
  muted: "#555b61"
  line: "#c8ccd0"
  quiet: "#e8ebed"
  incident: "#9b2f27"
  incident-wash: "#fceeea"
  maintenance: "#854a09"
  maintenance-wash: "#fff1da"
  info: "#1e5b75"
  info-wash: "#eaf3f8"
  unknown: "#535b67"
  unknown-wash: "#eceef1"
  focus: "#155da4"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "clamp(27px, 3vw, 36px)"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "22px"
    fontWeight: 650
    lineHeight: 1.2
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "19px"
    fontWeight: 650
    lineHeight: 1.2
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
  small:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.5
  record-title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 650
    lineHeight: 1.45
  tag:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "12px"
    fontWeight: 650
    lineHeight: 1.5
  mono:
    fontFamily: "ui-monospace, Consolas, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  compact: "3px"
  tag: "2px"
spacing:
  space-1: "6px"
  space-2: "12px"
  space-3: "18px"
  space-4: "24px"
components:
  button-default:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.compact}"
    padding: "8px 12px"
  button-default-hover:
    backgroundColor: "{colors.quiet}"
  button-default-disabled:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.muted}"
  download-action:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.compact}"
    padding: "8px 12px"
  input-field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.compact}"
    padding: "8px 10px"
  select-field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.small}"
    rounded: "{rounded.compact}"
    padding: "8px 10px"
  temporal-lane:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.compact}"
    padding: "11px 15px"
  temporal-lane-selected:
    backgroundColor: "{colors.yellow}"
    textColor: "{colors.charcoal}"
  evidence-tag:
    typography: "{typography.tag}"
    rounded: "{rounded.tag}"
    padding: "3px 7px"
  tag-incident:
    backgroundColor: "{colors.incident-wash}"
    textColor: "{colors.incident}"
  tag-maintenance:
    backgroundColor: "{colors.maintenance-wash}"
    textColor: "{colors.maintenance}"
  tag-partial:
    backgroundColor: "{colors.maintenance-wash}"
    textColor: "{colors.maintenance}"
  tag-info:
    backgroundColor: "{colors.info-wash}"
    textColor: "{colors.info}"
  tag-unknown:
    backgroundColor: "{colors.unknown-wash}"
    textColor: "{colors.unknown}"
  evidence-sheet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.compact}"
  event-open:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.record-title}"
    padding: "0"
---

# Design System: CLIENTE Service Health review

## Overview

**Creative North Star: "The Evidence Workpaper"**

The built system is a readable yellow/charcoal customer frame around flat neutral evidence sheets. Its character is compact, practical and restrained: branding establishes identity, typography organizes reading, and independently named evidence colors distinguish states without painting the whole workpaper yellow.

The generic presentation keeps CLIENTE and an empty Customer logo frame. The supplied, source-sampled identity colors are visual authority, not an official customer brand specification; the same readable identity applies to generic Git and authorized private rendering. This document records the built `report_template.html`, not a live capture or source-acceptance result. `SURFACE.md` retains the local task sequence and composition decisions; those are not global design tokens.

**Key Characteristics:**
- Sparse yellow branding and selected navigation; charcoal text on yellow.
- White, thin-bordered sheets on a pale neutral field; no shadows.
- Native system type for reading, wrapping monospace for receipts.
- Explicit text labels alongside independent evidence-state colors.
- Visible keyboard focus and responsive evidence access.

## Colors

The palette combines a warm, distinctive identity with quiet working neutrals and separate foreground/wash pairs for evidence.

### Primary

- **Client Yellow** (`yellow`): customer frame, provenance marker, selected temporal navigation and the keyboard skip link.
- **Client Charcoal** (`charcoal`): the title frame and the dark lettering and rules paired with yellow.

### Secondary

These are semantic evidence and attention colors, not additional customer brand accents.

- **Incident Red** (`incident`, `incident-wash`): service-incident tags and visible initialization/no-script errors.
- **Maintenance Brown** (`maintenance`, `maintenance-wash`): planned-maintenance tags and partial-coverage warnings.
- **Evidence Blue** (`info`, `info-wash`): Active source-state tags, explanatory evidence notes and ordinary text links.
- **Unknown Slate** (`unknown`, `unknown-wash`): Unknown and other non-Active source-state tags, uncertainty text and neutral coverage receipts.
- **Focus Blue** (`focus`): the shared keyboard outline, independent of evidence classification.

These foreground/wash pairs are not tonal ramps. No synthesized palette steps are recorded.

### Neutral

- **Paper** (`paper`): the surrounding work area and disabled controls.
- **Sheet White** (`sheet`): working sheets, controls and the action toolbar.
- **Reading Ink** (`ink`): primary working text and communication-title buttons.
- **Muted Text** (`muted`): labels, qualifications, timestamps and supporting counts.
- **Sheet Rule** (`line`): sheet edges, dividers and subdued control boundaries.
- **Quiet Hover** (`quiet`): the shared neutral hover treatment for ordinary action controls.

### Named Rules

**The Dark-on-Yellow Rule.** Use charcoal lettering on yellow identity and selected-navigation surfaces, never white lettering.

**The Separate Semantics Rule.** Yellow identifies branding and selection; evidence states retain their named foreground/wash pairs and explicit text labels.

## Typography

**Display and Body Font:** Segoe UI, with system-ui and sans-serif fallbacks.
**Receipt Font:** ui-monospace, with Consolas and monospace fallbacks.

**Character:** One native sans-serif family provides the reading hierarchy without external font assets. Weight and size establish emphasis; monospace is reserved for identifiers and original-record material rather than decorative labels.

### Hierarchy

- **Display:** the fluid `display` role is the report heading, with slightly tightened tracking.
- **Headline / Title:** `headline` and `title` provide the two descending heading steps. These headings use balanced wrapping and the same compact line-height as Display.
- **Body:** `body` is the default reading text. Paragraphs have a maximum measure of (74ch).
- **Label / Small:** `label` emphasizes field names and disclosure summaries; `small` carries ordinary supporting text, toolbar actions and field values. Fields inherit the smaller label context, not the larger body size.
- **Record title:** `record-title` distinguishes repeated communication-title buttons inside the register.
- **Tag:** `tag` is the compact, semibold evidence-label role; table headings use the same size and weight with their own neutral treatment.
- **Mono:** `mono` wraps long identifiers and original records instead of imposing a single unbroken line.

### Named Rules

**The Reading-and-Receipts Rule.** Use the native sans-serif for reading and controls, and wrapping monospace for identifiers and original records.

## Layout

The built report uses a centered, bounded content area, flexible grids with zero-minimum columns, and closely aligned bordered sheets. The recurring spacing vocabulary matches the first four declared spacing steps; the CSS currently applies these lengths as literals rather than consuming the spacing custom properties. Smaller inline gaps and control insets remain component-specific.

The wide report places the register beside its dossier. That arrangement is this surface's implementation, not a universal layout requirement. At the first breakpoint (maximum width 1100px), the workbench becomes one column, context becomes two columns with the final group spanning the row, and filters become three columns.

At the compact breakpoint (maximum width 620px), the customer/title frame stacks, branding becomes a horizontal row, the toolbar wraps, navigation becomes a two-column button grid, and filters use two columns with full-width search. Context and dossier metadata become single-column. Evidence is retained: the register scrolls inside its own focusable region, long values wrap, and disclosures remain available. Toolbar action minimum heights increase from (42px) to (44px); compact navigation uses a minimum height of (48px). Export actions remain in normal document flow, not a sticky overlay.

Print is a separate built layout: actions, filters, pagination controls and the skip link are hidden; all matching register rows are rendered; the selected dossier remains; raw-text height caps are removed; and the source ledger starts a new page. Print is not a replacement for the complete exports.

## Elevation & Depth

The system has no box-shadow vocabulary. Depth comes from the contrast between Paper and Sheet White, fine borders, neutral table headers, and restrained state washes. Selected-row and hover tints are local table treatments, not new elevation levels. Keyboard outlines are attention affordances, not shadows.

### Named Rules

**The Flat Sheet Rule.** Separate work areas with neutral surfaces and fine rules rather than shadow elevation.

## Shapes

The form is nearly rectangular: sheets and ordinary controls share the `compact` radius, while tags and the provenance marker use the smaller `tag` radius. Borders are fine (1px). Wide navigation rounds only its upper corners and meets a lower rule; compact navigation becomes individually bordered buttons with all corners rounded. Tags are small rectangles, not pills.

The generic customer-logo position remains a visible outlined frame with no embedded customer image. Its dimensions respond to the report header rather than becoming a reusable asset-size scale.

## Components

### Buttons

Neutral and direct, without a yellow-filled primary-action tier.

- Ordinary buttons use Sheet White, Reading Ink, the compact radius and the `button-default` insets; their minimum height is (42px).
- Hover uses Quiet Hover. Disabled buttons use Paper, Muted Text and a subdued border, with the default cursor.
- Download links have the same bordered-action silhouette, smaller toolbar typography and no text underline.
- All focus-visible controls use an outline (3px) in Focus Blue with an offset (3px). The skip link becomes visible when focused.
- There are no authored button transitions or custom active-state animations.

### Inputs / Fields

Compact, explicitly labeled native controls.

- Search and selects share white backgrounds, dark values, fine borders, compact corners and the recorded field insets.
- Labels use the semibold label role; input/select values use the regular small role. Placeholder text remains Muted Text at full opacity.
- Fields use the shared focus outline. No custom field-error or disabled-select appearance is established by this template.

### Navigation

Pressed-state buttons, not a decorative tab imitation.

- The group exposes its purpose and each button exposes `aria-pressed`.
- The selected button uses Client Yellow and Client Charcoal with semibold text; unselected buttons remain neutral.
- Counts use tabular numerals. Hover changes the relevant neutral or yellow fill without removing the selected-state distinction.
- The compact layout retains every button in a two-column grid. The temporal-lane names and overlap semantics remain local to `SURFACE.md`.

### Chips

Small, non-interactive evidence labels.

- Tags use the recorded tag typography, radius and insets; foreground and wash stay paired.
- Incident and maintenance describe event categories. Active source state uses Evidence Blue; other native states use Unknown Slate.
- Partial coverage uses Maintenance Brown. Completed returned-page receipts remain slate rather than becoming a green workload-health verdict.
- Meaning remains readable in the text, not just in the color.

### Cards / Containers

Flat evidence sheets with context-specific padding.

- Sheets share Sheet White, the fine Sheet Rule border and compact corners.
- The template does not establish one universal card-padding token: context, dossier and ledger have different insets.
- Supporting blue notes and red error blocks use existing semantic pairs rather than a separate decorative card palette.

### Communication Register and Dossier

A compact table with an explicit title-button selection affordance.

- Column headings, supporting timestamps and repeated receipt identifiers have distinct type roles; timestamps and counts use tabular numerals where authored.
- A selected row receives a pale warm tint. Hover preserves the selected/unselected distinction. These contextual tints are not general-purpose palette tokens.
- The communication title is a real button with `aria-controls` and `aria-pressed`, not a whole-row click target.
- Selection refreshes the dossier, focuses its `tabindex="-1"` section with `preventScroll`, then scrolls that section into view on both wide and compact layouts.
- The empty view explicitly distinguishes no filter matches, partial collection and successful-empty reads rather than presenting a health-success card.

### Source Disclosures

Native disclosure rows retain the original-record reading affordance.

- Resource records, full descriptions and source receipts use native `details`/`summary` controls and the shared visible focus treatment.
- Original records use wrapping monospace on a quiet neutral field. Long source text and record blocks scroll within bounded heights on screen; print removes those height limits.
- Resource identifiers wrap rather than being visually truncated. Disclosure rows use fine separating rules, not elevated nested cards.

## Do's and Don'ts

### Do:

- **Do** use yellow sparsely for branding and pressed navigation, with charcoal lettering.
- **Do** pair incident, maintenance, information and Unknown foregrounds with their matching washes and explicit labels.
- **Do** keep evidence sheets flat and reserve monospace for records and identifiers.
- **Do** preserve visible keyboard focus, native controls and focus transfer to the refreshed dossier.
- **Do** retain wrapping, disclosures and local table scrolling in compact layouts instead of dropping evidence.

### Don't:

- **Don't** put white lettering on yellow.
- **Don't** recolor all evidence yellow or replace Unknown with a reassuring success color.
- **Don't** embed real customer branding in the generic CLIENTE name or empty Customer logo frame.
- **Don't** promote the local temporal strategy, composition choice or surface seed into global design tokens.
- **Don't** describe these source-sampled colors as an official customer brand specification or this template as live evidence.
