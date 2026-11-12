---
name: AKS consulting dossier
description: An offline Fluent 2 reading system for qualified evidence and human decisions.
colors:
  canvas: "#f3f4f6"
  surface: "#ffffff"
  subtle: "#f7f8fa"
  wash: "#eceef1"
  ink: "#1f1f1f"
  muted: "#5c5c5c"
  line: "#e0e3e7"
  field-line: "#8a8a8a"
  heading: "#0c3b5e"
  accent: "#0f6cbd"
  accent-hover: "#115ea3"
  accent-wash: "#ebf3fc"
  chrome: "#0f6cbd"
  chrome-hover: "#0b5797"
  chrome-line: "#9cc8ef"
  cover: "#0c3b5e"
  cover-muted: "#c7def2"
  cover-line: "#3f6b90"
  nav: "#114b77"
  nav-muted: "#d0e4f6"
  plaque-ink: "#424242"
  critical: "#b42318"
  critical-wash: "#fee4e2"
  critical-bar: "#d92d20"
  high: "#b93815"
  high-wash: "#ffead5"
  high-bar: "#ef6820"
  medium: "#93370d"
  medium-wash: "#fef0c7"
  medium-bar: "#f79009"
  low: "#175cd3"
  low-wash: "#d1e9ff"
  low-bar: "#2e90fa"
  verdict-critical: "#ffb4ab"
  verdict-high: "#fec84b"
  verdict-medium: "#fedf89"
  brand-red: "#f25022"
  brand-green: "#7fba00"
  brand-blue: "#00a4ef"
  brand-yellow: "#ffb900"
  dark-canvas: "#141414"
  dark-surface: "#1f1f1f"
  dark-subtle: "#262626"
  dark-wash: "#2e2e2e"
  dark-ink: "#f2f2f2"
  dark-muted: "#c2c2c2"
  dark-line: "#3b3b3b"
  dark-field-line: "#949494"
  dark-heading: "#d6e9fa"
  dark-accent: "#6cb2eb"
  dark-accent-hover: "#9ccaf1"
  dark-accent-wash: "#1d3347"
  dark-chrome: "#0e4775"
  dark-chrome-hover: "#115486"
  dark-chrome-line: "#6d9cc6"
  dark-cover: "#0a2438"
  dark-cover-muted: "#b9d5ee"
  dark-cover-line: "#2e5578"
  dark-nav: "#0f3554"
  dark-nav-muted: "#c0daf1"
  dark-critical: "#ffb3ae"
  dark-critical-wash: "#4a1f1c"
  dark-high: "#ffbe94"
  dark-high-wash: "#46281a"
  dark-medium: "#fedf89"
  dark-medium-wash: "#3f3115"
  dark-low: "#a9d3ff"
  dark-low-wash: "#17304f"
  print-muted: "#505050"
  print-line: "#c8cbd0"
typography:
  display:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "40px"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-.02em"
  headline:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-.01em"
  title:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.35
  body:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
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
    fontSize: "12.5px"
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
  kpi-value:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1.1
  verdict:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1.2
  coverage-value:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "20px"
    fontWeight: 600
    lineHeight: 1.5
  chart-count:
    fontFamily: '"Segoe UI", system-ui, sans-serif'
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.25
rounded:
  control: "8px"
  card: "12px"
  pill: "999px"
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
    rounded: "{rounded.pill}"
    padding: "1px 10px 1px 8px"
  severity-high:
    backgroundColor: "{colors.high-wash}"
    textColor: "{colors.high}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "1px 10px 1px 8px"
  severity-medium:
    backgroundColor: "{colors.medium-wash}"
    textColor: "{colors.medium}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "1px 10px 1px 8px"
  severity-low:
    backgroundColor: "{colors.low-wash}"
    textColor: "{colors.low}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "1px 10px 1px 8px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "20px 24px"
  verdict-band:
    backgroundColor: "{colors.cover}"
    textColor: "{colors.surface}"
    padding: "44px 40px 104px"
  technical-receipt:
    backgroundColor: "{colors.subtle}"
    textColor: "{colors.ink}"
    typography: "{typography.technical}"
    padding: "12px"
---

# Design System: AKS Consulting Dossier

## Overview

**Creative North Star: "The Evidence Dossier", in the Azure SRE Agent report family**

A consulting document that leads with its verdict. Since the 2026-11 family
alignment the report shares the house style of the Azure SRE Agent use-case
reports: a slim Microsoft-blue top bar with section links, a "Solo lectura"
chip and the Print / PDF action; a deep-blue verdict band; KPI cards that
overlap its lower edge; then white cards on a neutral page. The four-colour
Microsoft ribbon, Segoe UI, ruled evidence tables and the client plaque remain
this case's own brand.

The system still serves reading first, with native controls for exploring the
same dated evidence. WARA informs narrative and Polaris informs wayfinding, not
scoring authority. The artifact is self-contained: inline styles and scripts,
system fonts and no network-dependent visual assets.

**Key Characteristics:**
- Verdict first: one-sentence summary with the key counts, provenance chips,
  a qualified verdict card and a severity distribution, before any detail.
- Explicit provenance, named severities and visible qualifications.
- White cards (12px radius, soft two-layer shadow) on a light neutral ground;
  ruled tables and receipts inside them.
- Local interaction and a complete, expanded print reading.

The frontmatter records source values and component primitives. `dark-` and
`print-` keys name overrides to existing color roles, not additional CSS custom
properties. Spacing keys collect recurring CSS literals.

## Colors

### Primary

Microsoft blue is the single operating accent: links, primary actions, index
fills and the passed segment of the status bar use `accent`, with
`accent-hover` and `accent-wash` for interaction. The top bar uses `chrome`;
the verdict band uses the deep `cover` blue with `cover-muted` secondary text
(never grey on blue) and `cover-line` chips. The verdict card sits on `nav`.
Section headings use `heading`, a deep blue that reads as ink.

### Neutral

`canvas` frames white `surface` cards. `subtle` supports table headers,
receipts and empty states; `wash` supports hover states and empty tracks.
`ink` carries reading, `muted` carries qualifications, `line` separates
content, and `field-line` gives native controls a stronger boundary.

### Severity

Severity uses the report family's shared pairs (text on wash, bar colour):
**Crítica** `critical` on `critical-wash` (`critical-bar`), **Alta** `high` on
`high-wash` (`high-bar`), **Media** `medium` on `medium-wash` (`medium-bar`),
**Baja** `low` on `low-wash` (`low-bar`). Pills are rounded, carry a current-
colour dot and always their name. The hero distribution bar uses the bar
colours with a labelled count legend. On the verdict card the verdict text uses
`verdict-critical`, `verdict-high` or `verdict-medium` so it stays legible on
`nav`; a report without evaluated checks says **No evaluado** in white.

The thin brand ribbon uses four equal, static red/green/blue/yellow spans. It is
decorative and hidden from assistive technology, not a status visualization.
Its brand colors are not interchangeable with severity colors.

Dark mode keeps the same roles with the recorded dark values: a darker band,
lighter accent and severity foregrounds on darker washes. The white client
plaque, the white theme selector and the white toolbar primary action remain
fixed-light exceptions.

Print forces the light roles in both themes and keeps the band, chips, pills
and bars in colour (`print-color-adjust: exact`). Muted text uses
`print-muted`; rules use `print-line`. Hidden operating chrome does not supply
print colors.

**The Evidence Before Color Rule.** Blue frames and operates; the ribbon brands;
severity names qualify findings. None of them grades an unavailable source.
Unknowns remain explicit, neutral **No evaluado** text with coverage or source
context, never a green success, low-severity substitute or healthy zero.

The assessment count chart is a single labelled horizontal bar: operating blue
for passed checks, `high-bar` for checks with a finding (not a severity
reclassification), field-line gray for not-evaluated and an outlined neutral
segment for N/A. Its heading shows the number of checks, never a health
percentage. A four-row labelled data table is the accessible source of the same
counts. The separate supplied score and coverage are not recomputed from it.

## Typography

The system stack is shared by display and reading text; numbers use tabular
figures throughout. Technical receipts and ARM IDs use the separate monospace
stack; there are no downloaded fonts.

The ramp: `display` (40px, at most two lines) for the band title, `headline`
(24px) for chapters, `title` (18px) for card headings, `body` (15px) for
reading, `body-small` (14px) for tables and qualifications, and `label` (13px)
for captions and pills. KPI values use `kpi-value` (34px), the verdict uses
`verdict` (26px) and the financial reading keeps `financial` (38px). Prose is
bounded (72ch), qualifications (75ch) and the band introduction (60ch).

At 760px and below the band title reduces to 28px, chapters to 21px and card
headings to 17px. Print uses body text (10pt), title (24pt), chapters (16pt),
card headings (12pt), tables (7.5pt) and receipts (6.5pt).

## Layout

A sticky slim top bar (about 64px) carries the product mark, section links
(Resumen, Inventario, Arquitectura, Hallazgos, FinOps, Plan de acción, Método),
the "Solo lectura" chip, the theme selector, **JSON completo** and
**Imprimir / PDF**. Below 1360px the links become a labelled section selector;
at 760px and below the bar stops being sticky and its controls wrap.

The full-bleed verdict band holds the title, introduction, one-sentence summary
and provenance chips on the left, the client plaque and verdict card on the
right, and the severity distribution across the bottom. Five KPI cards overlap
its lower edge. Content then sits in a centred column (max 1320px, 40px side
padding; 16px on phones) as white cards: the snapshot scope card, the optional
multi-cluster card, the executive grid (index and areas, assessment bar and
coverage, critical priorities, next actions, engine reading, pillars), the
filter card and the chapters. Grids collapse to one column at 1100px; KPI
cards become two columns on phones.

**The Wrap, Don't Clip Rule.** Prose wraps anywhere it must; ARM IDs break only
at `/` separators; wide tables keep local scrolling inside their card with
inset edge shadows that show which side has more columns. No page-level
horizontal overflow at 320px.

Print is A4 (14mm 12mm 16mm margins) with a running footer: report title,
cluster and UTC reference on the left, "Página n de m" on the right. The band
prints in colour; chapters begin on new pages; cards and rows avoid breaking;
every matching record is materialized and disclosures open. Table receipts are
moved below their table at full width in print, and JSON receipts print
compact.

## Elevation & Depth

Cards use a soft two-layer shadow (`0 1px 2px` + `0 1px 3px`, low alpha); KPI
cards a deeper offset shadow because they sit on the band edge. Tables, filters
and receipts stay flat inside their cards. No glass, no gradients, no coloured
glows. Print drops all shadows.

## Shapes

Controls use an 8px radius, cards 12px, chips and severity pills are fully
rounded. Client plaques stay square-cornered at 8px on white. Tracks and bars
are fully rounded. Most boundaries are thin (1px).

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

Focus is a visible outline (3px, offset 2px), using the operating accent on
reading surfaces and light text color in the toolbar. A focus-revealed skip
link targets the main document. Compact scope actions and pagination use
minimum height (40px); table text actions and receipt summaries use (32px).
Do not describe every shipped control as a uniform 44px target.

### Contents and scope wayfinding

Top-bar section links are semibold small-body text on the blue bar; hover
uses `chrome-hover`. Below 1360px a labelled section selector preserves the
same section names and moves focus to the selected heading. Namespace/workload text actions similarly move the reader to findings.
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

Provenance chips in the verdict band carry the UTC reference, LIVE or
SIMULATED provenance, environment and cluster. LAB and SIMULATED remain
explicit fixture provenance, not production-deployment claims. Full cluster
identity and source identity stay readable in the scope card.

### Verdict band and KPI cards

The verdict card derives only from supplied findings: **Acción prioritaria**
when a critical finding exists, **Requiere atención** for high,
**Revisión recomendada** for medium/low, **Sin hallazgos registrados** when
checks were evaluated without findings (with "no equivale a ausencia de
riesgo"), and **No evaluado** when nothing was evaluated. It always shows the
four severity counts and the evaluated-check basis. KPI cards show findings,
the local index (/100, "no oficial"), coverage (%), observed cost (or
**No evaluado**) and observed workloads; an unknown is written, never zero.
SIMULATED data adds an amber "Datos simulados" note under the KPIs.

### Indices, severities and qualifications

Local indices use simple accent-filled, fully rounded tracks (8px high);
unknown values keep written **No evaluado** and an unfilled track. Known score
tracks expose named meter values and coverage text. The severity distribution
in the verdict band is a separate bar (12px high) with named severity counts;
its segments do not replace the legend.

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
the `heading` role for a supplied amount, or muted **Por estimar** with
**No calculado** when absent. The large value is qualified, not a zero fallback
or a savings promise. Display values use tabular numerals at 38px (30px mobile);
unknowns use 30px (26px mobile). Candidates and original measurement windows
remain separate from this billing reading.

### Ruled tables and evidence disclosures

Tables use small-body text, small uppercase header labels on a subtle band,
thin horizontal rules, captions and top-aligned cells padded (12px 14px), all
inside a white card. Wide screen tables keep a minimum width (680px) inside a
focusable, named scrolling region with edge-shadow cues. ARM IDs break only at
`/`; captions and source/date notes preserve context.

Findings use native details/summary rows grouped by level in cards, sorted by
severity by default (an **Ordenar** selector restores the engine order), with
named severity pills, the title and a short reference (`check_id · nivel ·
namespace / carga`) above expandable evidence. Resource cells show the
resource name, its resource group and an Azure Portal link instead of a raw
ARM ID; full IDs stay in receipts and exports. Workload containers show name,
image, requests/limits and probes instead of raw JSON. Receipts and commands use the technical
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
- **Do** keep the family layout: slim blue bar, verdict band with KPI cards,
  white cards on a neutral page, and the decorative Microsoft ribbon.
- **Do** carry severity names, coverage, unknown reasons and source
  qualifications beside every visual summary.
- **Do** show long ARM IDs as name + resource group + Portal link in tables,
  keep receipts complete, keep wide tables locally scrollable and print
  complete matching evidence.
- **Do** retain fixed-light client branding, the public CLIENTE placeholder,
  explicit fixture provenance and native labeled controls.

### Don't:
- **Don't** use the ribbon colors as health grades or turn missing observations
  into successful, low-severity or zero-cost results.
- **Don't** let the verdict or a KPI imply health the coverage does not
  support; an unknown stays **No evaluado**.
- **Don't** add gradients, glass, decorative icons, emoji, external fonts,
  fetched imagery or network-dependent UI assets.
- **Don't** treat an official product icon, a configured Service annotation or
  a reference proposal as proof of deployment, reachability or ownership.
- **Don't** imply live deployment, official scoring, certified compliance or
  automated remediation through visual styling or labels.
