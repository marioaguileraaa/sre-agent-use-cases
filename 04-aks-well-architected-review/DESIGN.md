---
name: AKS consulting dossier
description: An offline Fluent 2 reading system for qualified evidence and human decisions.
colors:
  canvas: "#f5f5f5"
  surface: "#ffffff"
  subtle: "#fafafa"
  wash: "#f0f0f0"
  ink: "#242424"
  muted: "#616161"
  line: "#d1d1d1"
  field-line: "#8a8a8a"
  accent: "#0f6cbd"
  accent-hover: "#115ea3"
  accent-wash: "#eff6fc"
  chrome-hover: "#0b5797"
  chrome-line: "#d6e7f5"
  cover-ink: "#074b83"
  nav: "#eaf3fb"
  plaque-ink: "#424242"
  critical: "#a4262c"
  critical-wash: "#fde7e9"
  high: "#8a3700"
  high-wash: "#fff1e5"
  medium: "#795b00"
  medium-wash: "#fff8d6"
  low: "#616161"
  low-wash: "#f0f0f0"
  brand-red: "#f25022"
  brand-green: "#7fba00"
  brand-blue: "#00a4ef"
  brand-yellow: "#ffb900"
  dark-canvas: "#171717"
  dark-surface: "#1f1f1f"
  dark-subtle: "#292929"
  dark-wash: "#333333"
  dark-ink: "#f5f5f5"
  dark-muted: "#c2c2c2"
  dark-line: "#525252"
  dark-field-line: "#949494"
  dark-accent: "#78b5e6"
  dark-accent-hover: "#a3d1f2"
  dark-accent-wash: "#203448"
  dark-chrome: "#073e63"
  dark-chrome-hover: "#0d507d"
  dark-chrome-line: "#91bfdf"
  dark-cover: "#17334c"
  dark-cover-ink: "#c5e4ff"
  dark-nav: "#162c3e"
  dark-critical: "#ffb3b8"
  dark-critical-wash: "#442326"
  dark-high: "#ffb98f"
  dark-high-wash: "#3b2e25"
  dark-medium: "#f5d875"
  dark-medium-wash: "#383323"
  dark-low: "#d6d6d6"
  dark-low-wash: "#333333"
  print-muted: "#505050"
  print-line: "#b3b3b3"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "40px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-.01em"
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "13px"
    fontWeight: 600
    lineHeight: 1.5
  technical:
    fontFamily: "Consolas, ui-monospace, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  financial:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "38px"
    fontWeight: 600
    lineHeight: 1.25
  financial-unknown:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.25
  coverage-value:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.5
  chart-count:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.25
rounded:
  control: "4px"
  track: "2px"
spacing:
  tight: "4px"
  compact: "8px"
  control: "12px"
  base: "16px"
  section: "24px"
  wide: "32px"
  page: "48px"
  chapter: "56px"
components:
  control:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  toolbar-primary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.cover-ink}"
    rounded: "{rounded.control}"
    padding: "8px 12px"
  provenance-label:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "5px 9px"
  severity-critical:
    backgroundColor: "{colors.critical-wash}"
    textColor: "{colors.critical}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
  severity-high:
    backgroundColor: "{colors.high-wash}"
    textColor: "{colors.high}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
  severity-medium:
    backgroundColor: "{colors.medium-wash}"
    textColor: "{colors.medium}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
  severity-low:
    backgroundColor: "{colors.low-wash}"
    textColor: "{colors.low}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "3px 8px"
  technical-receipt:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink}"
    typography: "{typography.technical}"
    padding: "12px"
---

# Design System: AKS Consulting Dossier

## Overview

**Creative North Star: "The Evidence Dossier"**

This is a Fluent 2 consulting document: Microsoft-blue framing, neutral reading
pages, Segoe UI, deliberate whitespace and ruled tables. It is sober without
being monochrome. Bounded cover and evidence containers support the document;
they do not become a generic SaaS grid of interchangeable metric cards.

The system serves reading first, with native controls for exploring the same
dated evidence. WARA informs narrative and Polaris informs wayfinding, not
scoring authority. The artifact is self-contained: inline styles and scripts,
system fonts and no network-dependent visual assets.

**Key Characteristics:**
- Blue chrome and blue-toned cover/navigation around neutral reading surfaces.
- Explicit provenance, named severities and visible qualifications.
- Flat, lightly rounded controls beside square, ruled evidence.
- Local interaction and a complete, expanded print reading.

The frontmatter records reused source values and component primitives.
`dark-` and `print-` keys name overrides to existing color roles, not additional
CSS custom properties. Spacing keys collect recurring CSS literals; they do not
introduce a new source spacing API. Component entries describe the light
baseline; theme mappings and fixed-light exceptions are described below.

## Colors

### Primary

Microsoft blue is the single operating accent: links, primary actions and local
index fills use `accent`, with `accent-hover` and `accent-wash` for interaction.
The light toolbar shares that blue; the cover shares the accent wash. The
contents rail uses `nav`, with the same foreground color as `cover-ink`.
Toolbar hover and boundary colors remain distinct from reading-page rules.

### Neutral

`canvas` frames the white `surface`. `subtle` supports table headers, provenance,
empty states and technical receipts; `wash` supports hover states and empty
tracks. `ink` carries reading, `muted` carries qualifications, `line` separates
content, and `field-line` gives native controls a stronger boundary.

Severity has its own named foreground/wash pairs: **Crítica** is muted red,
**Alta** is brown-orange, **Media** is amber-brown and **Baja** is neutral gray.
Each badge includes its name and a current-color border. Distribution segments
use those severity foregrounds, with a labeled count legend beside the bar.

The thin brand ribbon uses four equal, static red/green/blue/yellow spans. It is
decorative and hidden from assistive technology, not a status visualization.
Its brand colors are not interchangeable with severity colors.

Dark mode uses the recorded dark reading roles, a lighter blue operating accent
and darker blue chrome, cover and navigation planes. Primary-action text uses
the dark canvas color; toolbar text uses the dark ink color. Severity labels keep
their names and receive the source's lighter foregrounds and darker washes.
The white client plaque, white theme selector and white toolbar primary action
remain fixed-light exceptions rather than inverted reading surfaces.

Print forces a light color scheme in both theme roots: white canvas and surface,
light ink, blue cover, blue index fills and light severity pairs. Muted text and
low-severity text use `print-muted`; rules use `print-line`. Hidden operating
chrome does not supply print colors.

**The Evidence Before Color Rule.** Blue frames and operates; the ribbon brands;
severity names qualify findings. None of them grades an unavailable source.
Unknowns remain explicit, neutral **No evaluado** text with coverage or source
context, never a green success, low-severity substitute or healthy zero.

The assessment count chart uses operating blue for passed checks, the existing
named high-color role for checks with a finding (not a severity reclassification),
field-line gray for not-evaluated, and a neutral surface segment for N/A.
Its centre displays the number of checks, never a health percentage. A four-row
labelled data table is the accessible source of the same counts. The separate
supplied score and coverage are not recomputed from the drawing.

## Typography

The system stack is shared by display and reading text. Technical receipts use
the separate monospace stack; there are no downloaded fonts.

The ramp is consultative, left-aligned and predominantly regular/semibold:
`display` for the cover title, `headline` for chapters, `title` for subsections,
`body` for reading, `body-small` for tables and qualifications, and `label` for
provenance and severity. Body-sized semibold headings subdivide evidence.
Field labels and compact buttons use the small-body size with semibold weight;
ordinary captions use the label size with regular weight.

The cover introduction is larger reading text (18px), returning to body size on
small screens. Prose is bounded (72ch), qualifications (75ch), and the cover
introduction (62ch). The cover title is bounded (22ch; 23ch on small screens).
Indices and inventory counts use tabular numerals; index bars retain written
values and evaluated/not-evaluated/not-applicable counts.

At the intermediate breakpoint, the cover title reduces to (32px). At the
small-screen breakpoint it reduces to (28px), chapter headings to (24px), and
subsection headings to (18px). These are source overrides, not another font
family or a fluid type scale.

Print uses body text (10pt), heading levels (26pt / 20pt / 14pt / 11pt), compact
reading (9pt), and table cells, captions and technical receipts (8pt).

## Layout

The screen shell is centered with a maximum width (1440px). Its desktop layout
has a quiet contents rail (218px) and a flexible, shrinkable document column.
The rail is sticky at the top; the toolbar is not. Document padding
(48px 48px 32px), ruled chapter divisions and the recorded spacing rhythm make
the reading plane feel like a dossier rather than an application dashboard.

The cover pairs flexible text with a bounded client plaque. Metadata uses three
columns, and the executive reading places a local index beside area readings.
Pillars use two columns. These are the shipped report's layouts, not a general
requirement to turn every section into a grid.

- At (1180px) and below: the rail narrows (182px), document padding reduces
  (36px 32px), and the main filters become two columns.
- At (900px) and below: the rail disappears in favor of a labeled native
  contents selector, and the document becomes a single page column.
- At (600px) and below: document padding becomes (28px 16px 24px), cover and
  score layouts stack, metadata uses two columns with a full-width UTC
  reference, filter fields stack, and fact pairs read vertically. Action rows
  wrap, with chapter/filter actions taking full width.

**The Wrap, Don't Clip Rule.** The body uses `overflow-wrap: anywhere`; resource
identities, source URLs, fact values and evidence also wrap. Keep the flexible
document column shrinkable. Wide tables retain local scrolling, not page-level
overflow hiding or clipped evidence.

Print is A4 with margins (16mm 14mm), no rail or operating toolbar, and no
document padding. Chapters begin on new pages; headings stay with following
content. Tables lose their minimum width, use fixed layout, repeat headers and
keep rows together where possible. Every matching record is materialized and
disclosures open; the selected scope remains written in the report.

## Elevation & Depth

There are no shadows. Depth comes from the canvas/page relationship, blue-toned
framing, subtle evidence backgrounds, whitespace and thin rules. Hover changes
color or underline rather than lifting elements.

**The Flat by Default Rule.** Keep reading surfaces and controls flat. Do not
add floating-card shadows, glass or gradients to express hierarchy already
carried by headings, spacing and borders.

## Shapes

The small control radius is shared by fields, buttons, navigation links, tags,
the cover frame and screen table regions. Tracks use the tighter track radius.
Client plaques, technical receipts and ordinary ruled sections stay square;
inline text actions have no rounded container. Print table regions are square.

Most boundaries are thin (1px). Severity badges use their foreground for the
border; evidence boundaries use the neutral line. Rounded track clipping is
limited to bar geometry, not reading content.

## Components

### Native controls

Buttons, inputs and selects share the frontmatter control surface and padding.
Standard controls have minimum height (44px). Buttons are semibold; generic
hover uses the wash and generic pressed state uses the line color. Disabled
buttons use reduced opacity (.55) and a not-allowed cursor. Primary-button
hover uses the operating accent hover.

Toolbar secondary actions are transparent with light text and chrome-colored
borders; their hover uses the chrome hover. The toolbar primary action and
theme selector are white with light cover-colored text in both themes; primary
hover uses the light navigation tint. Inputs have muted, fully opaque
placeholders, with visible labels rather than placeholder-only names.

Focus is a visible outline (3px, offset 3px), using the operating accent on
reading surfaces and light text color in the toolbar. A focus-revealed skip
link targets the main document. Compact scope actions and pagination use
minimum height (40px); table text actions and receipt summaries use (32px).
Do not describe every shipped control as a uniform 44px target.

### Contents and scope wayfinding

Desktop contents links are padded, small-body text with the shared control
radius; hover/focus uses the accent wash and accent foreground. The mobile
selector preserves the same section names and moves focus to the selected
heading. Namespace/workload text actions similarly move the reader to findings.
There is no decorative icon or invented active-route indicator.

Filters use native search/select fields, an additional-filters disclosure,
textual scope navigation and a polite live count. Local JSON/CSV exports and
the print action are text-labeled controls. Pagination does not redefine the
matching-record scope; summary indices retain their whole-snapshot label.

### Identity and provenance

The client plaque is bounded, square and white, with `plaque-ink` lettering.
The public placeholder is **CLIENTE**. Optional authorized private branding is
a contained inline PNG/JPEG with alternative text, not an externally fetched
image or a real customer identity committed to public documentation.

**The White Plaque Rule.** Keep the plaque's `color-scheme: only light`, fixed
white background and fixed readable foreground in both themes. Do not apply
dark reading-surface inversion to this branding surface.

Provenance labels use the neutral label primitive. LAB and SIMULATED remain
explicit fixture provenance, not production-deployment claims. Cluster identity,
source identity and the UTC reference stay readable alongside the cover.

### Indices, severities and qualifications

Local indices use simple accent-filled tracks (8px high); unknown values keep
written **No evaluado** and an unfilled track. Known score tracks expose named
meter values and coverage text. The severity distribution is a separate bar
(12px high) with named severity counts; its decorative segments do not replace
the legend.

Coverage, empty states and source failures are textual reading elements.
The interface keeps no-data and zero-matching-record explanations distinct.
Neither the index nor these components claims an official Azure, WARA or
Polaris score.

### Architecture and cluster selection

Observed architecture is an exact-ID neighbourhood diagram beside native type/
object selectors and a grouped resource tree. Every node, edge and unknown
retains its full receipt in paginated tables. The drawing shows at most thirteen
nodes with visible/total counts; it never replaces the full model or a record
table. On narrow screens the diagram is a labelled, focusable local scrolling
region; readable labels are not reduced to tiny mobile pixels.

The second tab is a separate, cited **Propuesta de referencia - NO desplegada**.
Its dashed VNet/subnet boundaries and alternative public L4 versus protected
HTTP(S)/private entry communicate design intent, not deployed connectivity.
Official Microsoft Azure V24 product icons are nearby named semantic assets,
not decorative UI icons or this report's brand. Eleven original SVGs are embedded
as audited static data URIs; usage terms and source hashes live in
`images/azure-icons/`. SVG-internal Microsoft paint remains original; the
application still introduces no decorative gradient.

A multi-cluster overview displays the supplied aggregate and every run status.
The selected cluster supplies the detailed reading and local scope. Selection
resets filters; failed primary reads expose their errors and hide all detailed
assessment instead of borrowing another cluster's data. Fixed roster entries
outside this artifact are explicitly unavailable for local selection.

### FinOps emphasis

One split financial reading separates **Coste observado** from **Ahorro
estimado**. The observed side retains amount, currency, exact cost scope,
association, source state and billing period. The accent-wash savings side uses
the existing cover-ink role for a supplied amount, or muted **Por estimar** with
**No calculado** when absent. The large value is qualified, not a zero fallback
or a savings promise. Display values use tabular numerals at 38px (32px mobile);
unknowns use 32px (28px mobile). Candidates and original measurement windows
remain separate from this billing reading.

### Ruled tables and evidence disclosures

Tables use small-body text, subtle headers, thin horizontal rules, captions and
top-aligned cells padded (12px 14px). Wide screen tables keep a minimum width
(680px) inside a focusable, named scrolling region. Resource IDs wrap within
cells; captions and source/date notes preserve context.

Findings use native details/summary rows, named severity badges and written
references above expandable evidence. Receipts and commands use the technical
primitive, pre-wrapped text and local scrolling with a maximum height (28rem).
Print removes that height limit and overflow restriction. Printing opens
evidence and hides controls; it does not discard off-page matching rows.

### Accessible system states

The source supplies semantic headings, labeled filters/navigation, scoped table
headers, live status text and native keyboard controls. Reduced-motion styling
removes transitions/animation and retains automatic scrolling behavior.
Forced-colors styling uses system-colored tracks/borders and a Highlight focus
outline while written labels remain available. These are implemented
affordances, not a WCAG certification or a claim of complete live verification.

## Do's and Don'ts

### Do:
- **Do** keep Microsoft-blue framing around neutral reading pages and preserve
  the separate decorative brand ribbon.
- **Do** carry severity names, coverage, unknown reasons and source
  qualifications beside the visual summary.
- **Do** wrap resource identities, retain locally scrollable tables and print
  complete matching evidence.
- **Do** retain fixed-light client branding, the public CLIENTE placeholder,
  explicit fixture provenance and native labeled controls.

### Don't:
- **Don't** use the ribbon colors as health grades or turn missing observations
  into successful, low-severity or zero-cost results.
- **Don't** replace the dossier with a hero metric or an identical-card SaaS
  dashboard; the cover establishes identity before the executive reading.
- **Don't** add gradients, glass, decorative icons, emoji, external fonts,
  fetched imagery or network-dependent UI assets.
- **Don't** treat an official product icon, a configured Service annotation or
  a reference proposal as proof of deployment, reachability or ownership.
- **Don't** imply live deployment, official scoring, certified compliance or
  automated remediation through visual styling or labels.
