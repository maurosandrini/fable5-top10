# Fable 5 — Top 10 Most Useful Use Cases (last 24h)

**Live page:** https://maurosandrini.github.io/fable5-top10/

A small, honest leaderboard of the **10 most useful real-world use cases of Claude Fable 5
spotted in the last 24 hours**, refreshed roughly every 12 hours during the first two weeks
after launch (June 10-24, 2026). Each entry links to the original post and explains in
plain English why the pattern is useful to people building with Claude Code and agents.

> **Honesty disclaimer.** This list is curated and ranked by an AI (Claude, supervised by
> [@maurosandrini](https://x.com/maurosandrini)) from public posts on X, Hacker News,
> GitHub, Google News and Substack. Engagement numbers are measured from the APIs at fetch
> time; any figure marked **"claimed"** is self-reported by the post's author and NOT
> verified. This project is not affiliated with Anthropic. Use your own judgment.

## Ranking criteria

1. **Transferability**: a replicable pattern beats a flashy demo.
2. **Evidence**: repos, videos, measured numbers; self-reported figures are flagged.
3. **Anti-recency**: a minutes-old post with zero engagement only enters if corroborated
   across sources.
4. **Anti-slop**: clusters of near-identical posts across accounts are disqualified
   entirely.
5. **Freshness vs the previous run**: returning items must show maturing engagement
   (tracked with a `streak` field).

If fewer than 10 use cases pass the bar, the list is published short. No filler.

## Current top 10

<!-- TOP10:START -->
| # | Use case | Source | Link |
|---|----------|--------|------|
| 1 | One-prompt audit of an entire knowledge vault with parallel agents | X | [post](https://x.com/tomcrawshaw01/status/2064699738545701371) |
| 2 | The Auditor pattern: a fresh session that distrusts the agent's own memory | X | [post](https://x.com/c_neumann20/status/2064571422681321956) |
| 3 | Tell the orchestrator explicitly which model its subagents must use | X | [post](https://x.com/RickTDing/status/2064755333625512301) |
| 4 | Real-world burn rates: 107 subagents and 975k tokens in 10 minutes | X | [post](https://x.com/thejordanwood/status/2064725683893576077) |
| 5 | Measure cost per thinking-effort level with a fixed benchmark artifact | X | [post](https://x.com/simonw/status/2064502387952570853) |
| 6 | Harness beats model: the environment is still the multiplier | X | [post](https://x.com/GuangyuRobert/status/2064750035443876012) |
| 7 | Spec-interview first, then autonomy on week-sized tasks | X | [post](https://x.com/shamshudein/status/2064754187234341212) |
| 8 | goal-prompt-coach: a plugin that turns rough ideas into self-verifying prompts | X | [post](https://x.com/dontcallmejames/status/2064571668622663922) |
| 9 | Curated component libraries as working context for design tasks | X | [post](https://x.com/K_leeeb/status/2064752585131663543) |
| 10 | Text to rendered explainer videos with Claude Code + Remotion | X | [post](https://x.com/farxxxxx1/status/2064756668232090110) |
<!-- TOP10:END -->

## How it works

- `data/latest.json`: the current ranked list (the web UI reads this file).
- `data/ledger.json`: the **cumulative ledger** of every use case that ever passed the
  quality bar, with `first_seen`, `last_seen`, `best_rank` and `runs_in_top10`. The top 10
  is a moving window over this list: items drop out of the ranking but are never forgotten.
- `data/archive/`: every previous run, timestamped.
- `data/raw/`: full raw dumps of every API response used in a run, so every number in the
  list can be traced back to its source (no orphan numbers).
- `scripts/verify_top10.py`: a deterministic gate that blocks publication if any link or
  number is not present in the raw dumps, if descriptions are not grounded in the source
  post, or if repeated items don't show maturing engagement.

## Author

Curated by **Mauro Sandrini** — teacher, author, independent researcher.
Follow me on X: [@maurosandrini](https://x.com/maurosandrini)
