# MTG MCP Cookbook

Practical workflows for getting the most out of the MTG MCP server. Each recipe shows the prompts you would type and how the server's tools chain together behind the scenes. For installation, see the [README](../README.md).

All examples use natural language. The server's tools are invoked automatically by your AI assistant based on your request -- you never need to call tool names directly.

---

## Commander

### Get to Know a Commander

You are considering building a deck around a commander and want the full picture before committing.

**Tools involved:**
- `commander_overview`
- `spellbook_find_combos`

**Prompts:**

> Tell me everything about Muldrotha, the Gravetide as a commander.

This pulls card data from Scryfall, top combos from Commander Spellbook, and staple cards from EDHREC into a single overview. Follow up to dig deeper into combos:

> What other combos does Muldrotha enable in Sultai? Show me up to 20.

**What you get:** A commander profile with mana cost, type, oracle text, EDHREC rank, top 5 combos with step-by-step instructions, and the 10 most-played cards with synergy scores and inclusion rates.

**Tips:** If you want to see how a commander stacks up against alternatives, jump to the "Compare Commanders" recipe below.

---

### Upgrade a Precon on a Budget

You bought a precon and have $30 to improve it.

**Tools involved:**
- `precon_upgrade`
- `deck_validate`

**Prompts:**

> Here is my Enduring Enchantments precon decklist with Daxos the Returned as commander. Suggest 10 upgrades under $30 total:
>
> 1 Daxos the Returned
> 1 Sol Ring
> 1 Sigil of the Empty Throne
> ... (paste full decklist)

The server identifies the weakest cards by synergy score and pairs each cut with a budget-friendly replacement. Once you have made swaps:

> Validate this updated decklist for Commander with Daxos the Returned as commander:
>
> (paste updated decklist)

**What you get:** Ranked swap pairs (cut this, add that) with reasoning, followed by a legality check covering deck size, color identity, copy limits, and banned cards.

**Tips:** Adjust the budget parameter by being specific: "under $50 total" or "no card over $5". Use the `upgrade_precon` prompt for a guided multi-step session.

---

### Build a Commander Deck from Scratch

Starting from zero with a commander in mind.

**Tools involved:**
- `commander_overview`
- `theme_search`
- `build_around`
- `complete_deck`
- `suggest_mana_base`
- `deck_validate`

**Prompts:**

Start with the big picture:

> Give me a commander overview for Atraxa, Praetors' Voice.

Identify your theme:

> Search for cards with a "proliferate" theme in WUBG colors, legal in Commander, under $5 each.

Build around your key pieces:

> Find cards that synergize with Atraxa, Deepglow Skate, and Doubling Season for Commander.

Fill gaps in your partial list:

> Here are my 45 cards so far. What am I missing to complete this Commander deck with Atraxa?
>
> (paste partial decklist)

Add lands:

> Suggest a mana base for this Commander decklist.

Validate everything:

> Validate this decklist for Commander with Atraxa, Praetors' Voice.

**What you get:** A complete 100-card deck built step by step -- theme cards, synergy pieces, gap analysis with category suggestions (removal, card draw, ramp), land base with dual land recommendations, and a final legality check.

**Tips:** The `build_deck` prompt walks you through this entire flow interactively. You can also use `tribal_staples` instead of `theme_search` if building a tribal deck.

---

### Compare Commanders Before Choosing

Torn between 2-3 commanders for a new deck.

**Tools involved:**
- `commander_comparison`

**Prompts:**

> Compare Muldrotha, Meren of Clan Nel Toth, and Karador Ghost Chieftain as graveyard commanders.

**What you get:** A side-by-side comparison table with mana cost, color identity, type, EDHREC rank, combo count, top staples, and unique strengths for each commander.

**Tips:** Follow up with `commander_overview` on whichever one interests you most. The `compare_commanders` prompt adds combo and staple analysis on top.

---

### Find Budget Upgrades

You want to improve an existing deck without spending much.

**Tools involved:**
- `budget_upgrade`
- `evaluate_upgrade`
- `card_comparison`

**Prompts:**

> Suggest budget upgrades for my Atraxa deck where each card costs under $3.

Review the top suggestions in detail:

> Evaluate adding Flux Channeler to my Atraxa deck.

Compare your top candidates head-to-head:

> Compare Flux Channeler, Grateful Apparition, and Thrummingbird for Atraxa.

**What you get:** A ranked list of upgrades sorted by synergy-per-dollar, followed by detailed per-card evaluations with combo potential and EDHREC data, then a comparison table for your finalists.

**Tips:** The `find_upgrades` prompt automates this full flow. Adjust the budget ceiling to match your comfort level.

---

## Draft and Limited

### Prepare for Draft Night

You want to study a format before sitting down to draft.

**Tools involved:**
- `set_overview`
- `draft_archetype_stats`

**Prompts:**

> Show me the top commons and uncommons for Foundations Premier Draft.

> What are the best color pair archetypes in Foundations? Use dates from February 1 to March 15, 2025.

**What you get:** Top 10 commons and top 10 uncommons ranked by Games-in-Hand Win Rate, a list of trap rares (those performing below the median), and archetype win rates by color pair.

**Tips:** The `draft_strategy` prompt gives you a structured study session including heuristic thresholds for what counts as a good ALSA or IWD. Use `keyword_explain` if you encounter unfamiliar set mechanics.

---

### Get Help During a Draft

Mid-draft, staring at a pack, not sure what to take.

**Tools involved:**
- `draft_pack_pick`

**Prompts:**

> Rank these cards for my Foundations draft pack: Pacifism, Goblin Striker, Air Elemental, Giant Growth, Divination, Elite Vanguard, Llanowar Elves, Mind Rot, Serra Angel, Cancel, Raging Goblin, Pillarfield Ox, Raise Dead, Naturalize. Set code is FDN. My picks so far are Pacifism, Serra Angel, Swords to Plowshares, Elite Vanguard.

**What you get:** A table ranking each card by GIH Win Rate with color, rarity, ALSA, and IWD. When you provide your current picks, cards are tagged as on-color or off-color based on your draft direction.

**Tips:** Include your current picks for color-fit analysis. Cards with fewer than 500 games in the 17Lands dataset will show "no data."

---

### Build a Sealed Pool

You opened your sealed pool and need help building the best 40-card deck.

**Tools involved:**
- `sealed_pool_build`

**Prompts:**

> Build a sealed deck from this Foundations pool (set code FDN):
>
> Serra Angel, Pacifism, Air Elemental, Llanowar Elves, Giant Growth, ... (list all 84-90 cards)

**What you get:** Up to 3 two-color build suggestions ranked by total card quality score, with each build showing the full card list grouped by type, mana curve, and counts of bombs and removal. Scoring uses 17Lands GIH Win Rate data when available, with a heuristic fallback.

**Tips:** The `sealed_session` prompt guides you through the full session including sideboard planning.

---

### Review Your Draft Afterward

You want to learn from a completed draft.

**Tools involved:**
- `draft_log_review`
- `draft_signal_read`

**Prompts:**

> Review my Foundations draft picks in order from P1P1 to P3P14:
>
> Serra Angel, Pacifism, Air Elemental, ... (list all 42 picks in draft order)

Then analyze what signals you may have missed:

> Read the draft signals from those same picks for Foundations.

**What you get:** A pick-by-pick table with each card's GIH Win Rate and a verdict (great pick, fine, questionable), an average quality score, and a letter grade (A through F). The signal read shows which colors were open based on ALSA data and whether you stayed in the right lane.

**Tips:** The `draft_review` prompt chains both tools together automatically.

---

## Deck Building

### Validate and Fix a Decklist

You have a decklist and want to make sure it is legal and has a solid mana base.

**Tools involved:**
- `deck_validate`
- `suggest_mana_base`

**Prompts:**

> Validate this decklist for Modern:
>
> 4 Lightning Bolt
> 4 Monastery Swiftspear
> 4 Goblin Guide
> ... (paste full decklist)

If it passes, optimize the lands:

> Suggest a mana base for this Modern decklist.

**What you get:** A VALID/INVALID verdict with specific issues (banned cards, too many copies, wrong deck size), followed by a land base recommendation showing color pip analysis, basic land counts, and format-legal dual land suggestions.

**Tips:** For Commander, include the commander name: "Validate this for Commander with Muldrotha as commander." For Pauper, the validator also checks rarity restrictions. Use `rotation_check` to see which cards are about to rotate out of Standard.

---

### Audit Deck Health

Your deck feels off and you want a comprehensive health check.

**Tools involved:**
- `deck_analysis`
- `suggest_cuts`

**Prompts:**

> Analyze this Commander deck with Muldrotha as commander:
>
> 1 Muldrotha, the Gravetide
> 1 Sol Ring
> 1 Spore Frog
> ... (paste full decklist)

Then find what to cut:

> What are the 5 weakest cards I should cut from this deck?

**What you get:** A full health report with mana curve distribution, color pip requirements, combo and bracket analysis, total deck budget, the 5 lowest-synergy cards, and a data sources summary. The cut suggestions rank cards by synergy and inclusion rate while protecting combo pieces.

**Tips:** The `deck_health_check` prompt runs both analyses together and provides prioritized recommendations. Follow up with `budget_upgrade` to find replacements for the cards you cut.

---

## Rules

### Settle a Rules Argument

Mid-game, someone played a card and nobody is sure how it works.

**Tools involved:**
- `rules_interaction`
- `rules_scenario`
- `keyword_explain`

**Prompts:**

Start with the mechanic interaction:

> How do deathtouch and trample interact when blocking?

Get a ruling for the specific board state:

> My opponent attacks with a 6/6 trample creature. I block with a 2/2 deathtouch creature. How is damage assigned and what happens?

If a keyword is unfamiliar:

> Explain the ward keyword and how it works.

**What you get:** Rules citations from the Comprehensive Rules for each mechanic, an explanation of how they interact, and a step-by-step walkthrough of your specific scenario with rule numbers. Keyword explanations include the glossary definition, related rules, and example cards that have the keyword.

**Tips:** The `rules_question` prompt guides a full rules inquiry with citations. Use `combat_calculator` for complex multi-creature combat scenarios where you need the full step-by-step combat phase breakdown.

---

## What's Next

This cookbook covers the most common workflows. For the full list of all 51 tools, 17 prompts, and 18 resource templates, see [TOOL_DESIGN.md](TOOL_DESIGN.md).
