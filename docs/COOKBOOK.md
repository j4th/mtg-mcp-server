# MTG MCP Cookbook

Practical workflows for getting the most out of the MTG MCP server. Each recipe shows the prompts you would type, the real tool output you will see, and how the server's tools chain together behind the scenes. For installation, see the [README](../README.md).

All examples use natural language. The server's tools are invoked automatically by your AI assistant based on your request -- you never need to call tool names directly. The example outputs below are real responses from the server.

---

## Commander

### Get to Know a Commander

You are considering building a deck around a commander and want the full picture before committing.

**Tools involved:**
- `commander_overview`
- `spellbook_find_combos`

**Prompts:**

> Tell me everything about Muldrotha, the Gravetide as a commander.

This pulls card data from Scryfall, top combos from Commander Spellbook, and staple cards from EDHREC into a single overview.

**Example output:**

```
Muldrotha, the Gravetide {3}{B}{G}{U}
Legendary Creature — Elemental Avatar (6/6)
EDHREC Rank: #1137 · Price: $0.69

During each of your turns, you may play a land and cast a permanent spell
of each permanent type from your graveyard.

--- Top Combos ---
1. Muldrotha + Kaya's Ghostform + Altar of Dementia + Lotus Petal
   → Infinite death triggers, Infinite ETB, Infinite LTB
2. Muldrotha + Displacer Kitten + Lotus Petal
   → Infinite colored mana, Infinite storm count
3. Muldrotha + Mindslaver
   → Control one opponent on each of their turns (Lock)
4. Muldrotha + Phyrexian Altar + Kaya's Ghostform
   → Infinite death triggers, Infinite ETB, Infinite LTB
5. Muldrotha + Displacer Kitten + Lion's Eye Diamond
   → Infinite colored mana, Infinite storm count

--- EDHREC Staples (22,460 decks) ---
High Synergy:
  Spore Frog              synergy +53%  inclusion 60%  (13,486 decks)
  Seal of Primordium      synergy +45%  inclusion 49%  (11,116 decks)
  Kaya's Ghostform        synergy +43%  inclusion 48%  (10,887 decks)
Top Cards:
  Eternal Witness          synergy +27%  inclusion 53%  (11,971 decks)
  Animate Dead             synergy +29%  inclusion 42%  (9,416 decks)
  The Gitrog Monster       synergy +27%  inclusion 42%  (9,368 decks)
```

Follow up to dig deeper into combos:

> What other combos does Muldrotha enable in Sultai? Show me up to 20.

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

**What you get:** Ranked swap pairs (cut this, add that) with reasoning. The server scores each card by EDHREC synergy and inclusion rate, protects combo pieces, and suggests replacements ranked by synergy improvement. This is followed by a legality check covering deck size, color identity, copy limits, and banned cards.

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

**Example output** (from `theme_search`)**:**

```
Theme: counters (mapped from "proliferate")
10 cards found in WUBG, Commander-legal, under $5.00

  Greta, Sweettooth Scourge      {1}{B}{G}  Legendary Creature   $0.16
  Pteramander                     {U}        Creature             $0.09
  Warden of the First Tree        {G}        Creature             $0.25
  Yorvo, Lord of Garenbrig        {G}{G}{G}  Legendary Creature   $0.33
  Long List of the Ents           {G}        Enchantment — Saga   $0.17
  ...
```

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

**Example output:**

```
                     Muldrotha            Meren               Karador
Mana Cost            {3}{B}{G}{U}         {2}{B}{G}           {5}{W}{B}{G}
Color Identity       BGU (Sultai)         BG (Golgari)        BGW (Abzan)
Stats                6/6                  3/4                  3/4
EDHREC Rank          #1,137               #1,476              #9,894
Total Decks          22,460               19,919              6,305
Combo Count          10                   1                   10

Top Staples:
  Muldrotha           Spore Frog (+53%), Sakura-Tribe Elder (+36%), Eternal Witness (+27%)
  Meren               Spore Frog (+70%), Sakura-Tribe Elder (+55%), Viscera Seer (+52%)
  Karador             Karmic Guide (+51%), Satyr Wayfinder (+49%), Sun Titan (+48%)

Shared across all:   Sakura-Tribe Elder, Eternal Witness, Spore Frog
Unique to Muldrotha: Blue card advantage, plays ANY permanent type from graveyard
Unique to Meren:     Lower mana cost, experience counter scaling
Unique to Karador:   White removal/recursion, cost reduction from graveyard size
```

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

**Example output** (from `budget_upgrade`)**:**

```
Budget Upgrades for Atraxa, Praetors' Voice (under $3.00/card)

Rank  Card                    Synergy  Inclusion  Price   Synergy/$
1     Thrummingbird           +20%     51%        $0.20   0.80
2     Astral Cornucopia       +19%     45%        $0.30   0.63
3     Tezzeret's Gambit       +20%     48%        $0.32   0.63
```

Review the top suggestions in detail:

> Evaluate adding Thrummingbird to my Atraxa deck.

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

**Example output** (from `set_overview`)**:**

```
Foundations (FDN) — PremierDraft
Median GIH WR: 54.7%

--- Top 10 Commons ---
Rank  Card               Color  GIH WR   ALSA   IWD      Games
1     Bake into a Pie    B      58.4%    3.1    +5.3%    354,741
2     Burst Lightning    R      58.2%    3.3    +3.0%    338,888
3     Refute             U      58.1%    5.3    +4.3%    321,280
4     Stab               B      57.9%    3.4    +4.5%    376,569
5     Dazzling Angel     W      57.8%    3.2    +2.4%    317,648
6     Luminous Rebuke    W      57.7%    3.9    +2.4%    293,089
7     Helpful Hunter     W      57.6%    3.5    +2.0%    346,467
8     Bigfin Bouncer     U      57.6%    4.5    +3.8%    330,544
9     Banishing Light    W      57.5%    2.8    +2.5%    302,846
10    Felidar Savior     W      57.4%    3.7    +2.1%    304,559

--- Top 10 Uncommons ---
Rank  Card                 Color  GIH WR   ALSA   IWD      Games
1     Dreadwing Scavenger  UB     61.4%    4.1    +9.2%    133,795
2     Mischievous Mystic   U      60.4%    2.7    +6.8%    152,402
3     Micromancer          U      59.3%    4.5    +5.1%    124,194
4     Faebloom Trick       U      59.3%    3.2    +5.1%    151,980
5     Empyrean Eagle       WU     59.2%    4.2    +4.0%    100,637

--- Trap Rares (below median GIH WR) ---
  Doubling Season        G      39.4%  ← Iconic card, terrible in limited
  Thousand-Year Storm    UR     35.2%  ← Lowest win rate in the set
  Painful Quandary       B      45.0%
  Niv-Mizzet, Visionary  UR     47.0%
  ...and 25 more rares/mythics below 54.7%
```

> What are the best color pair archetypes in Foundations? Use dates from February 1 to March 15, 2025.

**Tips:** The `draft_strategy` prompt gives you a structured study session including heuristic thresholds for what counts as a good ALSA or IWD. Use `keyword_explain` if you encounter unfamiliar set mechanics.

---

### Get Help During a Draft

Mid-draft, staring at a pack, not sure what to take.

**Tools involved:**
- `draft_pack_pick`

**Prompts:**

> Rank these cards for my Foundations draft pack: Serra Angel, Pacifism, Air Elemental, Giant Growth, Llanowar Elves, Mind Rot, Cancel, Elite Vanguard. Set code FDN. My picks so far are Pacifism and Serra Angel.

**Example output:**

```
FDN PremierDraft — Pack Rankings (current picks: Pacifism, Serra Angel → W)

Rank  Card             Color  Rarity    GIH WR   ALSA   IWD      Games
1     Llanowar Elves   G      common    56.9%    3.4    +2.9%    232,793  [off-color]
2     Serra Angel      W      uncommon  54.8%    3.3    +0.4%    87,260   [on-color]
3     Giant Growth     G      common    54.1%    6.7    -0.2%    111,372  [off-color]

No 17Lands data: Pacifism, Air Elemental, Mind Rot, Cancel, Elite Vanguard
```

**What you get:** A table ranking each card by GIH Win Rate with color, rarity, ALSA, and IWD. When you provide your current picks, cards are tagged as on-color or off-color based on your draft direction.

**Tips:** Include your current picks for color-fit analysis. Cards with fewer than 500 games in the 17Lands dataset will show "no data." Use the full card name as printed -- 17Lands uses Arena card names which may differ from some reprints.

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
> 4 Lava Spike
> 4 Rift Bolt
> ... (paste full decklist)

**Example output** (from `deck_validate`)**:**

```
Format: Modern
Status: ✓ VALID

Total cards: 60
Unique cards resolved: 14/14
Legality issues: None
Copy limit violations: None
```

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

**Example output** (from `suggest_cuts`)**:**

```
Cut Candidates for Muldrotha, the Gravetide
Sources: Spellbook ✓  EDHREC ✓

Rank  Card                 Score   Synergy  Inclusion  Combo?
1     Nihil Spellbomb      1.88    +6%      6%         No
2     Vessel of Nascency   1.87    +6%      7%         No
3     Caustic Caterpillar   1.73    +13%     14%        No
4     Reclamation Sage     1.66    +12%     22%        No
5     Life from the Loam   1.58    +13%     29%        No

Higher score = more cuttable. Combo pieces are protected (score -2.0).
```

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

**Example output** (from `rules_interaction`)**:**

```
--- Deathtouch (Rule 702.2) ---
"A creature with toughness greater than 0 that's been dealt damage by a
source with deathtouch since the last time state-based actions were checked
is destroyed as a state-based action." (702.2b)

"Any nonzero amount of combat damage assigned to a creature by a source
with deathtouch is considered to be lethal damage for the purposes of
determining if a proposed combat damage assignment is valid, regardless
of that creature's toughness." (702.2c)

--- Trample (Rule 702.19) ---
"The controller of an attacking creature with trample first assigns damage
to the creature(s) blocking it. Once all those blocking creatures are
assigned lethal damage, any excess damage is assigned as its controller
chooses among those blocking creatures and the player..." (702.19b)

--- Interaction ---
Only 1 damage needs to be assigned to each blocker for lethal (702.2c + 702.19b).
A 6/6 with deathtouch and trample blocked by a 5/5: the attacker assigns
just 1 damage to the blocker (lethal due to deathtouch per 702.2c) and
the remaining 5 tramples through to the defending player.
```

Get a ruling for the specific board state:

> My opponent attacks with a 6/6 trample creature. I block with a 2/2 deathtouch creature. How is damage assigned and what happens?

If a keyword is unfamiliar:

> Explain the ward keyword and how it works.

**Example output** (from `keyword_explain`)**:**

```
Ward (Rule 702.21)

"Whenever this permanent becomes the target of a spell or ability an
opponent controls, counter that spell or ability unless that player
pays [cost]." (702.21a)

Ward is a triggered ability, not a static one — it goes on the stack
and can be responded to. The cost varies by card (mana, life, discard, etc.).

Note: Ward only triggers from opponents' spells/abilities. Your own spells
targeting your creature with ward will not trigger it.
```

**Tips:** The `rules_question` prompt guides a full rules inquiry with citations. Use `combat_calculator` for complex multi-creature combat scenarios where you need the full step-by-step combat phase breakdown.

---

## What's Next

This cookbook covers the most common workflows. For the full list of all 51 tools, 17 prompts, and 18 resource templates, see [TOOL_DESIGN.md](TOOL_DESIGN.md).
