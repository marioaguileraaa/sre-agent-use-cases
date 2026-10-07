# Azure SRE Agent – Use cases

Field-tested, **step-by-step use cases for [Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/overview)**, ready to reproduce in your own (or your customer's) environment.

Each use case is self-contained: an English guide with **annotated screenshots** (red boxes and numbers show exactly what to select) plus every artifact you need: Python tools, skills, subagent instructions, prompts and scripts.

## Use cases

| # | Use case | What it does | Building blocks |
|:---:|---|---|---|
| 01 | [**Microsoft Entra credential expiration audit**](01-entra-credential-expiration-audit/) | Prevents outages caused by expired app secrets and certificates. Monthly, read-only audit of App Registrations and Service Principals that delivers an interactive HTML report with risk status, filters, CSV export and links to Microsoft Entra. [Business value](01-entra-credential-expiration-audit/README.md#business-value) | Python tool · Skill · Subagent · Scheduled task · Microsoft Graph |

*More use cases coming soon.*

## How each use case is organized

```
NN-use-case-name/
├── README.md        # Step-by-step guide with annotated screenshots
├── images/          # Screenshots used by the guide
├── *.py / *.ps1     # Tools and scripts to copy into the agent or run once
├── SKILL.md         # Skill content (when the use case uses a skill)
└── *.md             # Subagent instructions and prompts
```

The guides follow the same pattern: **permissions → tool → skill → subagent → test in chat → automate**. You validate every step before you move to the next one.

## Common prerequisites

- An Azure SRE Agent deployed in your subscription. See [Create an agent](https://learn.microsoft.com/azure/sre-agent/create-agent).
- Builder permissions on the agent in the [SRE Agent portal](https://sre.azure.com).
- The specific permissions listed in each use case (for example, Microsoft Graph application permissions granted to the agent's managed identity).

## Conventions

- Values you must change are marked as placeholders, for example `<YOUR_AGENT_CLIENT_ID>`.
- Screenshots come from a lab environment. Subscription IDs, client IDs, user names and other identifiers are blurred.
- Every use case is designed **read-only first**: the agent observes and reports; remediation stays a human decision.

## Disclaimer

This is a personal repository, not an official Microsoft repository. These samples are provided **as-is**, without warranty, to illustrate how to use Azure SRE Agent. They are not official product documentation. Review the code, the permissions and the current [Azure SRE Agent documentation](https://learn.microsoft.com/azure/sre-agent/) before using them in production.

## License

[MIT](LICENSE)

---

Maintained by **Mario Aguilera**, Solution Engineer, Microsoft.
