# Learning to win AoE II: literature review and proposed direction

Reviewed 31 October 2026. This is a focused review of primary research, not a systematic survey. Recommendations below are engineering proposals for this project, not experimentally established AoE II results. No code, rewards, training runs or tests were changed for this review.

## Main decision

Optimize actual match outcomes. Keep opening, economy and combat exercises as auxiliary skills. Start with a compact recurrent PPO policy over meaningful game commands, initialize from demonstrations where available, and train against a mixture of fixed opponents and frozen historical policies. Avoid committing the full-game objective to a long list of production bonuses.

The existing opening learner cannot learn full-game wins merely by running for longer. Its actions exclude resource assignment, military production, research and combat, and its terminal objective is a three-minute opening score. It is a useful control/learning exercise, not the proposed full-game environment.

## Primary literature

| Work | Method and evidence | Relevance and limits |
|---|---|---|
| [AlphaStar, Vinyals et al., 2019](https://storage.googleapis.com/deepmind-media/research/alphastar/AlphaStar_unformatted.pdf) | Human replay imitation, recurrent policy, V-trace/TD(lambda)/UPGO, league training; win/loss and strategy-conditioned auxiliary objectives. Grandmaster-level full StarCraft II. | Supports demonstrations, memory and opponent diversity. It was not ordinary PPO from scratch with victory alone. Its distributed scale does not establish desktop feasibility. |
| [OpenAI Five, 2019](https://cdn.openai.com/dota-2.pdf) | Recurrent PPO, self-play and shaped rewards including gold, experience, structures and deaths. Sparse-reward ablation learned more slowly. | Useful evidence for long-horizon reward design; Dota is a MOBA and does not reproduce AoE economy/building control. The paper explicitly says its shaping does not satisfy policy-invariance guarantees. |
| [TStarBot-X, Han et al., 2020](https://arxiv.org/html/2011.13729) | Imitation, league training, rule-guided exploration, V-trace/UPGO and a PPO alternative. | Expert guidance and efficient engineering matter. The reported 144 V100 GPUs still put its reduced-compute system far beyond one desktop. |
| [SCC, Wang et al., ICML 2021](https://proceedings.mlr.press/v139/wang21v.html) | Full StarCraft II with imitation/RL engineering improvements and lower compute than AlphaStar. | Another efficiency-oriented full-game reference; lower relative compute is not evidence of single-GPU feasibility. |
| [Action Guidance, 2020](https://arxiv.org/html/2010.03956) | A sparse-objective main policy receives guidance from auxiliary shaped-reward policies in microRTS. | Particularly relevant: resource shaping delayed combat production until harvesting was exhausted in one task. Auxiliary skills can guide exploration without redefining the final objective. |
| [Invalid action masking, Huang and Ontanon, 2020/2022](https://arxiv.org/abs/2006.14171) | Theoretical and empirical support for masking invalid actions in policy-gradient methods. | Mask commands that cannot legally execute; do not confuse a legal-action mask with hard-coding every strategic choice. |
| [AlphaStar Unplugged, 2023](https://arxiv.org/abs/2308.03526) | Offline actor-critic and MuZero variants benchmarked using a large human-game dataset. | Supports investigating data reuse. We do not yet have an equivalent AoE dataset with reconstructed player-view observations and aligned actions. |
| [SMAC, Samvelyan et al., 2019](https://arxiv.org/abs/1902.04043) | Cooperative micromanagement benchmark with an agent per unit. | Combat benchmark success does not establish full-game strategy, economy or production skill. |

I did not identify a directly comparable, well-established full-game AoE II DE RL training recipe in this focused search. [PyAge2](https://github.com/kachayev/pyage2) is an environment for the older Conquerors game, not evidence of a trained DE champion.

## Interpret the proposed rewards

These are design judgments for AoE II, not weights copied from the papers.

| Signal | Recommended treatment | Failure to avoid |
|---|---|---|
| Verified win/loss | Main terminal objective: +1 / -1; true draw 0 | Replacing victory with an economic score |
| Cumulative gathered resources | Track deposits/gathering separately from balances; useful for skill learning and diagnostics | Economic farming without pressure; confusing trade, refunds or spending with gathering |
| Stockpile | Observation and context-sensitive capacity signal | Rewarding hoarding or punishing saving for an age/technology |
| Buildings placed | No flat full-game bonus | Foundation spam, cancellation refunds, redundant buildings |
| Completed useful buildings | Bounded capability/progress estimate if needed | Rewarding unlimited construction merely because it completes |
| Units produced | Skill objective or bounded current useful army/economy value | Producing, sacrificing and replacing units for points |
| Unit/building losses | Log costs and exchanges; use cautiously in auxiliary combat tasks | Refusing a sacrifice that wins the match |
| Relics | Observe deposited holdings and income; ownership changes should be reversible in a potential | Repeated pickup/drop/recapture rewards; double-counting relics and their gold |
| TC idle time | Diagnostic; context-conditioned opening auxiliary objective | Penalizing age-up/research, emergency defense, necessary saving or late-game worker saturation |
| Scouting | Temporary skill objective; evaluate strategically useful information | Exploring irrelevant tiles instead of fighting |

Measure elapsed game seconds, not the number of polling calls. Distinguish no-food, population-blocked, researching and genuinely avoidable TC idle time. Starting resources, refunds, tribute, trading and passive income require separate accounting if resource telemetry is used.

Enemy disappearance into fog is not a kill. Loss, conversion, deletion and garrisoning are distinct events. Prefer reliable ownership/event statistics; do not infer hidden enemy strength from information the policy should not have.

## A proposed reward experiment

Keep a terminal-only baseline. Compare it to the same policy and training budget with potential-based shaping:

`r_t = outcome_t + lambda * (discount_t * Phi(history_next) - Phi(history_now))`

Here `Phi` is a fixed, bounded progress estimate from permitted observation history. It could combine productive economic capacity, surviving military capacity and useful technological capabilities. This is not an unbounded running total of achievements. Set terminal potential to zero. Use the same elapsed-time discount in rewards and return computation. Hold lambda fixed within each experiment/episode; if it changes within an episode it must be included correctly in the time-dependent potential.

Under the applicable assumptions, potential-based shaping preserves the optimal policy of the base discounted task. It does not guarantee neural-network convergence, and arbitrary clipping, changing potential definitions, terminal partial-score bonuses or other extra rewards can invalidate that argument. The proof is in [Ng, Harada and Russell, 1999](https://ai.stanford.edu/~ang/papers/shaping-icml99.pdf).

For an initial ablation, use lambda 0, 0.05 and 0.1 with Phi normalized into [0,1]. These are proposed experiment settings, not validated AoE coefficients. Select based on held-out match results. Do not add a speculative coefficient for every available statistic at once.

An alternative worth testing after the baseline is a victory-trained main policy with shaped-reward auxiliary skills, inspired by Action Guidance. Copying its off-policy action mixing into PPO without the necessary likelihood corrections would be incorrect; ordinary imitation pretraining is a simpler first implementation.

## Algorithm and action interface

Recurrent PPO is the first practical baseline because we have its initial implementation and can use legal action masks and memory. This is an engineering choice, not a claim that PPO is universally most sample-efficient. BC followed by PPO reduces initial blind exploration but inherits teacher bias; teacher competence must be measured.

Use one player-level policy initially. Expose macro commands for worker allocation, construction, production, research, scouting, grouping, attack and retreat. Keep deterministic execution helpers for placement/pathing. Give an economic/strategic controller slower decisions than combat skills where useful. Multi-agent methods such as MAPPO or QMIX are not automatically needed simply because many units exist.

A flat DQN action list is awkward for variable unit/target/position choices. Distributed V-trace infrastructure makes more sense once multiple environment actors actually exist. Learned-world-model planning and offline RL are later alternatives after telemetry/data quality is established, not shortcuts around an unreliable game interface.

## Long-horizon issue in the existing implementation

The opening task uses gamma 0.99 per two game-seconds. That gives a reward half-life of approximately 138 game-seconds. A reward 40 game-minutes later has weight approximately 0.0000058 at the beginning of the game. This is an arithmetic consequence of the existing discount, not a benchmark result.

Full-game design must specify a time-based discount horizon and use it consistently in the critic, advantage estimator and any shaping. Longer returns/multiscale value estimates and recurrent sequence handling need consideration. Simply making episodes longer leaves this issue unresolved. Discounting terminal outcomes also favors earlier wins and delayed losses, so it is not exactly undiscounted win probability. Do not claim otherwise.

Administrative time limits are not victories or genuine draws. For a continuing task, retain the distinction between truncation and termination and bootstrap appropriately. Record censored matches separately; a crash/reset failure must not fabricate a negative game reward.

## Feasibility and staged work

The recorded machine has six physical CPU cores, about 32 GB RAM and a 16 GB RTX 5060 Ti. That is a plausible platform for small policies and a constrained hybrid agent. Actual simulation throughput is unmeasured; there is no evidence yet that it can reproduce frontier full-game results from scratch.

Illustration only: one 40-game-minute match at an effective 2x speed takes 20 real minutes. That is three games/hour, or at most 336 games in a 112-hour budget before resets, updates, failures or evaluation. More GPU capacity alone does not provide more independent games. Measure simulation throughput before committing an expensive training run.

Recommended sequence:

1. Build a full-game recorder: verified outcome, unit roles and queues, resource accounting, game settings, map seed and command timing. Preserve fog policy. Let the user run checks as requested.
2. Establish one fixed civilization/map family/ruleset and a complete scripted playable baseline. Include all actions required to finish a game.
3. Train a high-level controller that can alter economic priorities, production, attack timing and retreat while reliable execution helpers handle mechanics. Retain the opening as a skill rather than a forced final objective.
4. Compare imitation-only, imitation plus outcome-only PPO, and imitation plus potential-shaped PPO using equal wall-clock budgets and multiple learner seeds.
5. Use frozen opponents and held-out map seeds; report win/loss/true draw/censored/error separately, with uncertainty grouped by map and training seed. Select checkpoints by held-out win rate, not shaping score.
6. Expand opponents and retain historical snapshots to reduce forgetting and exploitative overfitting. Progress toward Extreme and later human evaluation only when narrower evaluations justify it.

Independent games and robust outcome telemetry are the principal unanswered feasibility questions. The new opening restart module remains untested; this review does not certify it or change the earlier validation gates.
