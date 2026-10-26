# Service Health events review

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Infrastructure operators reviewing Microsoft-published service incidents and
maintenance communications for one approved subscription. The job is to find
the relevant communication, inspect its potential resource associations and
coverage, and decide what needs human review.

## Product Purpose

A restricted read-only Azure SRE tool produces a dated offline workpaper,
complete source-qualified JSON and two ordinary CSV exports. It consolidates
communications; it does not measure workload outages or operate a ticket queue.

## Operating Context

Monthly recurrence and focused on-demand reviews use the same bounded reader.
Requested-window updates, source-observed Active status and future communicated
maintenance remain separate. Every report retains its actual UTC window,
observation times, source retention qualification and pagination receipts.

## Capabilities and Constraints

- Only subscription-scoped `Microsoft.ResourceHealth/events` categories
  `ServiceIssue` and `PlannedMaintenance`, with per-event `impactedResources`.
- Fixed administrator configuration and explicit user-assigned managed identity;
  no arbitrary subscription, URL, token, query, directory or identity inputs.
- Offline filters, event/resource detail, source ledger, print and full and
  filtered exports; no external libraries, fonts, images or live polling.
- A Tracking ID is not a Microsoft support-case number. Published potential
  impact is not observed workload downtime.
- No historical daily as-of reconstruction, new/changed claim without a
  baseline, composite health score, SLA calculation or savings claim.
- No tenant/security-advisory expansion, support/Jira integration, cloud
  mutation, IAM, extra infrastructure or runtime scheduling by this package.
- Only this case folder changes. Deployment, source acceptance, recurrence
  creation, publication and real captures belong to the authorized operator.

## Brand Commitments

The supplied direction is binding: a distinctive readable yellow/charcoal
identity, sparse yellow navigation/branding, neutral evidence sheets and named
independent risk/Unknown colors. Generic source says `CLIENTE` with a visible
customer-logo frame and no embedded logo. Private configured deployment may
use an authorized validated customer raster. Source-sampled colors are not
represented as an official brand specification.

## Evidence on Hand

Official REST/schema, ARG examples and history documentation are source
references, not live acceptance. Earlier cases are method references only.
This case's test fixtures are permanently `SIMULATED`. Actual source access,
normal/default and manual-monthly native downloads were verified in the
approved lab on 2026-10-14 UTC. The README records their distinct 22:14:58Z and
22:21:09Z references, complete returned-page qualification, actual monthly
10:00 UTC recurrence and real masked screenshots. Raw private configuration,
exports, credentials, receipts and unmasked captures remain outside Git.
The generic tool source is frozen. The generic package and masked lab captures
are published in the private repository; customer deployment/acceptance and
future timer-fired completion remain separate gates.

## Product Principles

1. Keep source facts, derived classifications and unknowns distinguishable.
2. Preserve complete in-scope records and partial-page evidence.
3. Prefer an explicit blind spot to a reassuring empty or healthy fallback.
4. Keep read-only runtime capability separate from operator setup authority.
5. Make the evidence useful without turning brand color into risk semantics.
