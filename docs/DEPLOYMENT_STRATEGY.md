# CoStaff Deployment Strategy v1

> **Decision date**: 2026-05-04
> **Status**: Active — chosen for v1
> **Re-evaluate**: when one of the trigger conditions in §4 fires.

## 1. Decision

**Path (A) — Self-hosted CLI** is the v1 deployment model.

Customers install and run CoStaff on their own machines (laptop, on-prem
server, or VPS they own) using the existing `costaff` CLI. We ship the
binary distribution + documentation; customers handle hosting.

Path (B) and (C) are deferred — see §4 for the conditions that would
re-open the discussion.

## 2. Why (A)

- **~90% already implemented.** The `costaff` CLI today supports
  `start` / `stop` / `status` / `agent add` / `channel add` etc. Going
  ship-ready is a closing task, not a green-field build.
- **Fastest path to revenue.** Days to ship vs. months for SaaS.
- **Lowest ongoing cost.** No infra, no on-call, no compliance for our
  hosting environment.
- **Naturally AGPL-compatible.** Customers run their own copy; we never
  expose a network service derived from AGPL code, so the AGPL §13 SaaS
  loophole does not apply.
- **Early-customer fit.** Buyers willing to evaluate a v1 are typically
  technical enough to run a docker-compose stack.

## 3. Why not (B) / (C) — yet

| Path | Why deferred |
|---|---|
| **(B) One-click VPS deploy** (Terraform / Ansible to DigitalOcean, Hetzner, GCP) | Useful, but no validated demand yet. Without (A) shipping first we have no customer signal on whether they want (B) or just (A). |
| **(C) Cloud-managed CoStaff (SaaS)** | Multi-tenant + 24/7 ops + SLA + compliance is a ~6-month project. We don't have the team or the validated pricing model. AGPL §13 also forces us to either re-license the SaaS layer (Open Core split) or release SaaS modifications publicly. Neither is solved. |

## 4. Triggers to re-open the decision

Move on (B) when **any** of the following fires:

- ≥ 5 self-hosted prospects bounce because they can't / won't run docker.
- A specific cloud platform (e.g. GCP Marketplace) is requested by a
  paying customer.
- We have written demand from a customer for one-click deploy (not
  speculative, an actual ask).

Move on (C) when **all** of the following are true:

- ≥ 10 paying self-hosted customers (validates the product itself).
- A pricing model where SaaS economics work (not just "host for free").
- Either Open Core split is in place, or we accept full AGPL on the
  SaaS layer.

## 5. (A) ship-ready checklist

What "shippable v1" actually means. Each item is small enough to track
as a single PR / commit. Order is approximately the right path.

- [ ] **Customer-facing README** at the top of the costaff repo, distinct
      from `CLAUDE.md` (which is for AI assistants and contributors).
      Sections: what is CoStaff, what you get, install, first run, where
      to put your secrets, where data lives, how to update, how to remove.
- [ ] **`install.sh` validated on a clean macOS 14+ VM** —
      copy-paste-ready instructions in the README, run end-to-end without
      manual fixes.
- [ ] **`install.sh` validated on a clean Ubuntu 22.04+ VM** — same.
- [ ] **Troubleshooting / FAQ** doc covering: docker not running, port
      already in use, postgres connection refused, permission denied on
      shared dir, agent shows offline in dashboard.
- [ ] **Minimum hardware / OS requirements** doc — RAM, CPU, disk, OS
      versions tested.
- [ ] **AGPL customer-facing summary** — one-page plain-language: what
      they can do, what they can't, what triggers source-disclosure
      requirements, link to full LICENSE.
- [ ] **First paying customer onboarded end-to-end** without our hands
      touching their machine. This is the real ship-ready signal.

## 6. Out of scope for v1

- Auto-update / `costaff update` polish — exists but not required for v1
- Backup / restore for customer data — manual `costaff database backup`
  is enough
- Multi-instance management — single Mac/server/VPS only
- Marketplace / plugin discovery — `costaff agent add --github <url>` is
  enough; the marketplace experience is a separate ROADMAP item

## 7. Decision review cadence

Re-read this document **monthly** for the first 3 months. After each
read, either:

- Confirm "(A) still primary" and write a one-line dated note, or
- Open a sub-decision in this doc if a trigger from §4 has fired.
