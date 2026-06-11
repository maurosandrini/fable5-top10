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
| 1 | Persistent context across sessions for every agent (claude-mem) | GitHub | [repo](https://github.com/thedotmack/claude-mem) |
| 2 | ECC: agent harness with skills, instincts, memory and security baked in | GitHub | [repo](https://github.com/affaan-m/ECC) |
| 3 | gstack: 23 specialized agent roles in one Claude Code setup | GitHub | [repo](https://github.com/garrytan/gstack) |
| 4 | cc-switch: single desktop app to manage Claude Code, Codex, Gemini CLI and others | GitHub | [repo](https://github.com/farion1231/cc-switch) |
| 5 | Study extracted system prompts from Fable 5, Opus 4.8, and Claude Code to calibrate your own agent design | GitHub | [repo](https://github.com/asgeirtj/system_prompts_leaks) |
| 6 | graphify: turn any codebase or schema into a queryable knowledge graph | GitHub | [repo](https://github.com/safishamsi/graphify) |
| 7 | open-design: local-first open-source Claude Design with 259+ skills | GitHub | [repo](https://github.com/nexu-io/open-design) |
| 8 | ClaudeCode GodMode: declare intent, let 15 specialized agents decide execution | GitHub | [repo](https://github.com/cubetribe/ClaudeCode_GodMode-On) |
| 9 | Curated awesome list of Claude Fable 5 use cases with benchmark evidence | GitHub | [repo](https://github.com/Anil-matcha/awesome-claude-fable-5) |
| 10 | Fix: explicitly allow reasoning effort when calling Fable 5 in task pipelines | GitHub | [PR](https://github.com/PostHog/posthog/pull/62949) |
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
