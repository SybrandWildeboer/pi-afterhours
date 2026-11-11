# 08 Costs and limits

**Every figure here is an estimate**, measured on one setup (the author's) and priced with the CLI's own per-call cost report. Your repos, prompts and models will differ. `python3 run.py cost` prints what your own runs cost.

## Measured on the author's setup (estimates)

| Call | Typical cost |
|---|---|
| Idle check (read Slack, last post says "no further action") | about $0.005 to $0.011 |
| A short spec for a Slack request | about $0.11 |
| One fix attempt | about $0.08 to $0.12 |
| An idle day (gate every 30 min plus the hourly runs stopping at the idle rule) | roughly $0.15 to $0.40 |

The loop's per-call caps (`budget_usd` in `config.json`) are ceilings, not typical costs: gate $0.05, post $0.05, review $0.40, spec $0.60, fix $1.50. A day's worst case is much higher than the figures above, but each call is capped and the cooldowns in [05](05-maintenance-loop.md) stop repeats.

## Subscription or API?

The loop runs `claude -p`, which uses whatever the profile is logged in with. On a subscription the dollar figures are **estimated API-equivalent cost**, not a bill, but the runs still count towards your plan's usage limits and can use up capacity you wanted for interactive work. On a pay-as-you-go API key they are real money. The dashboard labels cost "n/a" when a profile reports none.

Remote Control sessions you drive from the phone use the same account limits.

## Keeping it cheap

- Leave the idle rule on, and keep Slack configured: it is what turns a repeated hourly run into one cent.
- Keep gate and post on a small model (the default is haiku).
- Lower `budget_usd`, `max_fix_per_run`, or the number of repositories.
- Run fewer cron hours.

## Your employer

If the work account belongs to an employer, check their policy on automated agents, personal hardware, and source code leaving their machines before you point it at work repositories. Check the same for sharing screenshots of a dashboard that shows repository names.
