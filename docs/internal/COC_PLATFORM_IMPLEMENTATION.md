# CoC platform implementation and acceptance

Agreed 2026-10-30 (Europe/London). Upstream baseline: c0944bb, DiceFrame v3.0.3 + two commits. Fork: https://github.com/0S0d1uM0/diceframe. This is an internal implementation record, not a statement that the features below have shipped.

## Product contract

This fork prioritizes private use as a CoC platform. Standard seventh-edition mechanics are the default; optional house rules must be named and explicit. The existing freeform_coc entry and old saves remain usable. A new coc7e entry owns the stricter rules. Existing generic services may be reused, but specific CoC rules stay in their owning domain.

The priority experience is an AI Keeper with mixed human/AI investigators or three AI investigators. Human Keeper configurations remain supported. AI investigators are loyal to the party: no betrayal, stealing from allies, or adversarial objectives. PvP scenarios are out of scope. They may disagree and propose alternatives without overriding human choices. Madness does not authorize malicious inter-party behavior.

Discussion is not an action. Party planning must not advance time, roll checks, consume resources, discover facts, or trigger Keeper narration. Players agree on the plan and explicitly submit their own actions. AI proposals are shown for mixed-table discussion before they become actions. Full AI play must likewise separate deliberation from committed actions and be bounded and pausable.

The Keeper may autonomously adjudicate ordinary play, subject to server rules and facts. Humans can pause, correct, or take over. New facts must not silently rewrite established truth. Module play preserves core truth, motives, and clues; original regular campaigns start from an outline, while endless campaigns have no predetermined finale. Failed rolls may have meaningful costs and bad endings, but the default avoids a single failed check making all progress impossible.

Manual and AI character creation fill the same validated form. Desktop comes first. Natural language is the main interaction, with useful character, clue, notebook, inventory, and rules panels. Private perceptions, secrets, and split parties require character-level knowledge boundaries; spectator access must be explicit. Death and permanent insanity remain real outcomes, with replacement investigators rather than automatic resurrection.

## Delivery sequence

1. Establish fork and branch, record decisions, restore application concurrency to three. Add the CoC domain, validated character builder, explicit new rule entry, and correct rules primitives. Keep unsupported mechanics visibly unsupported.
2. Separate discussion/proposals from action commitment. Give AI investigators authorized knowledge retrieval and party-loyal behavior. Maintain existing actor/run/round/control-revision fences, privacy, persistence, and rollback.
3. Integrate deterministic CoC checks, opposed checks and combat reactions, damage/armor/wounds, SAN/insanity and recovery through explicit runtime contracts. Build player-facing rule controls and AI decision paths; no fake completed automation.
4. Add scenario and campaign truth/knowledge progression, regular/endless original modes, structured planning and NPC behavior. Extend pursuit, magic, equipment/economy, development and campaign play in coherent increments.
5. Run a complete original short scenario with one AI Keeper and three AI investigators, capture decision/roll/state/narration evidence, save/reload and conclusion. Create a separate human-play acceptance game. Report omissions and quality limitations explicitly.

## Verification and local model scheduling

DSH local is the only delegated model and always runs one task at a time. Do not start DiceFrame model tests until DSH has completed its current task. DiceFrame may use three concurrent requests; cloud inference is not used in development acceptance. Automatic tests use fakes/seeded RNG wherever possible. Rule and isolation tests, API integration tests, frontend type/build checks and an actual local-model playthrough serve different acceptance purposes. Existing regression success alone is not evidence of standard CoC fidelity.

Rules sources: Chaosium's official rules wiki, especially /rules/combat.html, /rules/opposed-skill-rolls.html, /rules/sanity.html and /rules/hit-points-wounds-and-healing.html. Critical success is 01. Major wound compares a single injury with half maximum HP, not SIZ. Successful and failed SAN losses are distinct formulas; successful SAN is not generally half failed SAN.

## Work ownership and progress

Codex owns integration, application flow, API/UI, runtime registration, template, and acceptance. DSH receives bounded exclusive file ownership before editing and must not modify other files. No recursive delegation. Final important conclusions and acceptance are checked by Codex.

- [x] Read predecessor record and verify main paths; 137 focused baseline tests passed.
- [x] Create/reuse personal GitHub fork; branch codex/coc7e-platform based on c0944bb.
- [x] CoC domain and builder integrated (four occupations, ages 20–39).
- [x] Deliberation separated from commit and available in UI.
- [x] CoC rules subset integrated and tested; unsupported surfaces documented.
- [ ] Full-AI scenario acceptance completed.
- [x] Separate human acceptance game ready, first round unplayed.

This checklist is updated with actual implementation and observed results, never with estimated completion.

## First live playthrough and memory review

The original local-model table reached fourteen settled rounds, including additional rounds played by the user. It has not passed story acceptance: the Keeper and investigators remained around the same door/clock obstruction, repeatedly described the time as approaching ten, and had neither rescued the clockmaker nor stopped the anomaly. Source-accurate endings must not be claimed from successful HTTP transactions alone. The original game and its evidence are retained.

DSH reviewed the transcript read-only, with one local task at a time and no overlapping DiceFrame inference. Codex confirmed the stalled investigation, unadvanced authoritative clock and incomplete objectives. DSH's suggestions to force an investigator to act or directly manufacture a completed ending were rejected: party consent and genuine outcomes remain required. A narrative handover of the stop pin also lacks an authoritative ownership transfer; duplicating it into two inventory projections is not an acceptable repair.

The user's memory concern prompted a separate input-path review. Offline reconstruction from the fifteenth-round save includes rounds 0–14 for all three investigators, together with the public summary and facts. Approximate token estimates are about 8k per investigator and 13k for a Keeper reconstruction supplied with scenario lore; these are not saved historical requests or model-provider billing counts. A read-only production lore preview using round fourteen's actions retrieves both the public commission and the Keeper truth. Low input counts alone therefore do not establish missing history.

Concrete defects repaired: historical action text lost speaker attribution; persistent decision facts lacked a warning that later actions can supersede them; rolling summaries received the previous narrative but omitted the previous key-fact list; malformed summary responses could erase old facts. The final assembled input now emits coverage metrics without logging private text. Investigator contexts still exclude the global Keeper memory store; complete personal long-term recall requires a separately authorized character knowledge projection.

CoC Keeper state projections now remove legacy d20 modifiers and compact skill tables while preserving SAN, Luck, magic points and wound/madness states. Scenario core entries are marked constant while retaining their existing public/Keeper visibility boundaries. Neither change is evidence that model narration will reliably obey all constraints; further real-model acceptance is necessary.

Regression baseline after the first integration was 7,524 backend passes with seven skips and one deselected environment-specific case. Docker-launcher and cp311 upgrade fixtures are excluded on this Python 3.14 workstation. Frontend regression was 1,396 passes; two additional party-consent tests also pass. Build/type checks and changed-file ESLint passed. Subsequent memory changes are undergoing another regression run; focused context, summary, actor-isolation and consent tests pass.

After the memory repairs, regression passed 7,529 backend tests (same environment exclusions) and all 1,398 frontend tests. The new private-text-free diagnostic and bounded-negotiation tests pass separately. The first live round-fifteen retry confirms that every investigator actually receives history rounds 0–14, the public summary, confirmed items, authorized lore and private perceptions. All three withheld consent because the reviewer treated round fourteen's monitoring condition as permanent. The review prompt now gives current proposals the ability to supersede earlier temporary plans, and the isolated planning command permits at most three genuine proposal/review passes with preserved objections. It cannot manufacture human or AI consent.

## Post-fix live observations and remaining acceptance gate

Real round-fifteen/sixteen Keeper inputs contain the complete earlier transcript, canonical scenario lore, the public summary and 636 characters of recalled long-term memory. Coverage metrics estimate about 14k input tokens; provider tokenizer/cache metrics can differ. This disproves a blanket claim that these calls have no history, while leaving the quality of their interpretation open.

A later optimistic guard rejection identified changes in live player state. The character list/read services normalized nested live sheets and wrote display fields during GET requests. They now normalize deep-copied response projections. A regression checks that list/single reads and edits to returned sheets leave live state unchanged. The old list-normalization test existed twice and intentionally expected a read-side repair; both are updated to require a normalized response with unchanged durable state. The focused character/consent suite passes 57 cases. The following broad run passed 7,531 cases and exposed only the second copy of that old assertion; it is rerun after updating the duplicate.

Rounds sixteen through eighteen then commit and settle without that guard error while the browser continues polling. Round sixteen genuinely stops the clock. Round seventeen includes two server fumbles and the Keeper uses them to loosen the stop pin, returning the story to another approaching-ten loop. By round eighteen the clockmaker is still not rescued and the clock is running again. No finale has been prepared, committed or falsely marked complete. The full-AI story acceptance remains unchecked.

The next implementation gate is authoritative scenario progression: explicit established facts, objective completion and reopening policy, committed elapsed time and scheduled consequences, and valid alternate routes after a failed attempt. Keeper prose must be checked against that state, not become its sole authority. Investigation checks also need a distinction between an actor's suggested skill and a Keeper-authorized uncertain task, so stating a method does not automatically create another mandatory roll. Durable key-item handovers require their own authorized transfer receipt rather than a duplicated inventory entry. Personal investigator recall must use public discoveries plus that investigator's perceptions, with provenance and supersession; global Keeper memory cannot simply be injected into investigators.
