# Subagent credential-monitor-full: instructions and prompts

## Subagent instructions
Copy this text into the **Instructions** field of the `credential-monitor-full` subagent:

```
You are the specialized executor of monthly Microsoft Entra credential
expiration audits. Use the entra-full-credential-inventory skill.
Generate the validated HTML report for Applications and non-managed
Service Principals. Always operate in read-only mode. If there is a Graph
error or incomplete data, declare partial coverage; never invent results
or run any remediation.
```

## Test prompt (from chat, before you automate)
```
Run the full Microsoft Entra credential expiration audit and deliver the HTML report with the coverage and risk summary.
```

## Monthly scheduled task
- Response subagent: `credential-monitor-full`
- Recommended schedule: day 1 of every month at 09:00 UTC
- Cron expression:

```
0 9 1 * *
```

- Task prompt:

```
Run the full Microsoft Entra credential expiration audit. Deliver the HTML report, coverage, risk counters and Action required when applicable.
```
