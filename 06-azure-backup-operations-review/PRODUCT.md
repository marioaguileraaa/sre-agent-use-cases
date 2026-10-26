# Azure Backup operations review

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

IT Operations analysts reviewing existing Azure Backup jobs and deciding whether
a human incident investigation is warranted. The confirmed task is to review
failed backups today, with errors, warnings and evidence, not to create incidents.

## Product Purpose

Produce a reusable, dated, read-only operations workpaper from explicitly allowed
Recovery Services vaults. Explain what was observed, what could not be read and
what cannot be concluded about item or time coverage.

## Operating Context

A monthly scheduled review of recent available evidence, plus on-demand review.
Monthly is the reporting cadence, not a claim of full-month history. Analysts
use the downloaded offline HTML, complete JSON and ordinary CSV files at a desk,
on a phone or in print. This is not a polling monitor.

## Capabilities and Constraints

- One standalone Python runtime tool, one runtime skill and one restricted
  subagent. Runtime inputs never change identity, subscription or vault scope.
- Read existing vault metadata, paged jobs, individual job details and paged
  protected items. No backup, restore, protection, policy or cloud changes.
- Preserve native states, operation/workload types, original source properties,
  dates, full identities, source receipts and partial results.
- Distinguish backup from restore/delete/other jobs. No job is not a successful
  backup. Completed is not a recoverability, integrity or RPO/RTO test.
- Inventory describes observed items, not intended protection. Policy IDs alone
  do not establish an expected schedule, denominator or missed occurrence.
- Local filters, evidence disclosure and complete exports share one collection.
  Exported JSON must be the exact original embedded UTF-8 bytes.
- No external fonts, libraries, requests, analytics or live polling in HTML.
- Native sharing aliases derive only from the actual validated runtime cwd.
- Generic source remains unconfigured. Each customer's authorized administrator
  owns scope/access, deployment, monthly-task setup and actual download acceptance.

## Brand Commitments

The user explicitly selected the same distinctive yellow/charcoal identity for
generic source and private runtime. Supplied-asset pixel colors are `#FBC807` and
`#1E1C18`; these are not asserted to be an official brand guide. Dark text goes
on yellow; neutral sheets carry evidence. Error, warning and Unknown have
independent named semantics. Generic source says CLIENTE with an empty customer
logo placeholder. Real customer branding and data are private deployment only.

## Evidence on Hand

The confirmed brief settles audience, task, palette, cadence, privacy, source
families and accessibility; no further aesthetic interview or agents are
needed. Factory engineering contracts and cases03/04 are implementation prior
art, not runtime dependencies or visual authority. Official REST documentation
qualifies the adapter; the dated lab receipts qualify that deployment separately.
Executable fixtures remain SIMULATED. The English evidence guide now contains
privacy-masked actual saved SRE configuration and dated normal/manual-monthly
execution captures, with actual download receipts and explicit unknown history.
Those captures are not synthetic fixtures or proof of future calendar firing.
The generic package and masked lab captures are published privately; a new
customer's deployment, evidence-sharing approval and actual acceptance remain
separate gates.

## Product Principles

1. Evidence and uncertainty travel together.
2. Observed scope never silently becomes expected protection.
3. A human review queue is not an incident workflow.
4. Complete evidence is not shortened to make a transport limit pass.
5. Branding never becomes operational evidence.

## Accessibility & Inclusion

Readable AA text contrast, keyboard-native controls, visible focus, labeled
filters, source text rendered as text, meaningful empty/error states, phone
layouts and fully expanded print evidence.
