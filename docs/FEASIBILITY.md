# Feasibility assessment

## What the machine can establish

The current machine has a Ryzen 5 9600X (6 physical / 12 logical cores), about 32 GB RAM, and an RTX 5060 Ti with 16 GB VRAM. PyTorch 2.11.0+cu128 successfully performed a GPU matrix operation. Hardware details and available memory/storage at inspection time are in `reports/machine.json`.

This supports compact recurrent models and meaningful skill-learning experiments. It does not demonstrate enough simulation capacity or experience to reach expert play. The immediate bottleneck is an operational game bridge. No DE episodes/second or speed multiplier has been measured.

At one decision per 0.5 game-seconds, a 40-game-minute match contains 4,800 transitions. At an effective 1 / 10 / 50 transitions per wall-second, one million transitions would require approximately 34.7 / 3.47 / 0.69 eight-hour nights. These are scenarios, not measured speeds or sample requirements. Eight-hour sessions for fourteen days provide 403,200 wall-seconds, including resets, training, crashes and evaluation.

The GPU is not sufficient evidence for the overall goal: AlphaStar used thousands of parallel games and substantial distributed training. Its early published league ran for 14 days with 16 TPUs per agent. This is context, not a transferable AoE budget: https://deepmind.google/blog/alphastar-mastering-the-real-time-strategy-game-starcraft-ii/.

## How Extreme AI is built

The installed `PromiDE.per2` entry point loads separate scripts for initialization, threats, escrow, economy, scouting, boar hunting, research, buildings, units, trade, and resignation. `reports/machine.json` records the inspected filenames, SHA-256 hashes, line counts, rule counts and Extreme-specific conditional branches.

The inspected files contain **7,604 `defrule` declarations in total**. This is an on-disk inventory including alternative modules/branches, not a count of rules active during any single game. The core behavior is a rule-based expert system. `gatherers.per` contains an Extreme-specific branch at line 5133 in this installation. Other modules coordinate attack groups, unit production and thresholds.

Accordingly, “how was Extreme trained?” is not an RL training-budget question. Its shipped behavior is expressed through scripts, with developer updates revising concrete behaviors. The installation provides no published neural-network training recipe or sample-count benchmark we could reproduce. This inspection does not establish every internal tool used by the developers or prove perfect human-information parity.

Sources: https://airef.github.io/ and https://www.ageofempires.com/news/age-of-empires-ii-definitive-edition-update-107882/. The local installed scripts are the direct evidence for this build.

## Algorithm decisions

| Method | Use in this project | Main limitation |
|---|---|---|
| Scripted baseline | Transparent execution and a control for measuring learned improvement | Strength depends on hand-coded choices |
| Behavior cloning | Learn sequences from the same observation/action interface | Inherits teacher mistakes and distribution shift |
| Recurrent PPO | Learn from outcomes, maintain memory across partial observations | Needs many environment samples; single-episode pilot updates have high variance |
| Cloning then PPO | Primary candidate; imitation uses the first 20% of the per-run budget | Improvement beyond the teacher is not guaranteed |
| DQN | Potential compact decision selector later | A flat action list does not scale naturally to full-game parameterized commands |
| Evolution strategies | Possible script parameter search later | Population evaluations compete for the scarce simulation budget |
| Dreamer/world models | Deferred | Requires reliable data and validating imagined dynamics; no evidence of full AoE feasibility here |

The recurrent network uses a 64-unit encoder and GRU state with actor and value heads. The pilot's tiny discrete action space intentionally tests one component; macroeconomy and full-game entity/action representations are not implemented. PPO uses clipped policy updates, time-aware GAE, entropy regularization and gradient clipping. Algorithms share the observation filter, teacher interface, action mask and backend.

Primary references:

- PPO: https://arxiv.org/abs/1707.06347
- Action masking: https://arxiv.org/abs/2006.14171
- DQN: https://www.nature.com/articles/nature14236
- Evolution strategies: https://arxiv.org/abs/1703.03864
- Dreamer: https://arxiv.org/abs/2301.04104

## Decision criteria and milestones

Proceed beyond feasibility only with reliable live resets, verified information/command constraints, and reproducible learning improvements. Compare wall-clock budgets across three seeds, report all outcomes including failures, and freeze policies before held-out evaluation. Wilson intervals in the pilot reports are nominal per-game binomial intervals; mirrored games share map seeds, so a final performance claim also needs analysis grouped by map seed and training run.

Then add economic tasks, integrate macro and combat, and train against a mixture of scripted opponents and frozen past policies. Full-game self-play and opponent-league management are not implemented in this first pilot.

Milestones remain distinct: 80% wins over 200 held-out Extreme matches in a declared Arabia setting; then private evaluations against multiple consenting 2,000+ ranked players. Neither this prototype nor a win against Extreme establishes expert human strength. Professional performance remains an uncertain long-term research objective.
