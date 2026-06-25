---
name: calib
description: Measure what the user half-knows about concepts in play, then teach the gaps interactively. Probes with real questions to rate each concept (none/heard-of/can-use/solid), then teaches the weak ones via leading-question bets. Use when the user invokes /calib.
disable-model-invocation: true
argument-hint: "[concept ...] (optional — omit to infer gaps from the conversation)"
---

The user is about to build with concepts they only partly understand. Calibrate
what they actually know, then teach only the gaps. Four phases. Keep the whole
thing grounded in what we are actually working on — not generic textbook material.

Match the `no-bs` output style throughout: terse, example-first, no throat-clearing.

## Phase 1 — Resolve the concept list

- If `$ARGUMENTS` is non-empty, those are the concepts (e.g. `/calib oidc alb`).
  Skip the scan.
- If empty, scan your own context — the conversation is already loaded, so this
  is cheap. List up to 6 concepts the user has been working with that they show
  signs of only partly understanding (they asked about it, hedged, restated it
  wrong, or leaned on you to drive it). Present them with `AskUserQuestion`
  (multiSelect: true) so the user checks which to calibrate; the "Other" field
  lets them add ones you missed. If nothing stands out, ask the user to name the
  concept directly.

  Do NOT spawn a subagent for this. Subagents start with fresh context and can't
  see the conversation, and even fed the transcript they'd only re-read what you
  already hold — that adds cost, it doesn't save it. A cheap subagent only pays
  off when it keeps bulk *new* material (large files, web pages, logs) out of
  this model's context, which is not the case here.

## Phase 2 — Calibrate (the interview panel)

For each concept, gauge the user's real level — do NOT ask them to self-rate.

- Pose **1–2 real probe questions** via `AskUserQuestion` — questions whose
  answer reveals whether they actually get it ("what happens if X?", "which of
  these is true about Y?"). Make the options plausible; a wrong pick should be
  tempting, not obviously silly.
- Ground every probe in what we are building right now, not a generic case.
- The "Other" field is where the user volunteers an assumption or hedge ("I'm
  guessing it's X", "I assumed Y"). Treat anything they write there as signal —
  fold it into the rating and address it in teaching.
- From their answers, assign a level:

  | level | meaning |
  |---|---|
  | `none` | wrong or blank — no working model |
  | `heard-of` | knows the word, not the mechanics |
  | `can-use` | right answer, shaky on edges/why |
  | `solid` | correct and explains it — no teaching needed |

State each rating in one line so the user can object before you teach.

## Phase 3 — Teach the gaps

Teach **only** concepts rated below `solid`. Skip the solid ones — say you're
skipping them.

Teach interactively, never as a lecture. Deliver explanation as a **deck of
slides** — one idea per slide — presented as ONE `AskUserQuestion` panel the user
flips through and submits once, like a slide deck. Never dump a multi-point
explanation as prose.

- Open each concept with a **leading question** as its own panel
  (`AskUserQuestion`, real answer options) so the user bets an answer first, then
  reveal the answer in your message. The bet is what makes it stick — they
  commit, then learn.
- Then teach the clarification as a deck. Bundle the slides into a single
  `AskUserQuestion` call with **one question per slide** (up to 4 — the panel's
  max; more slides means a second deck after this one). For each slide:
  - `header` = a short slide title (the panel shows it as a chip).
  - `question` = the slide body: one idea, a few terse lines, tied to the current
    task (the way `/idk` does).
  - options = **Got it** / **Lost me**, nothing more. Option labels are acks, not
    explanations — do NOT pack teaching into them.
  The user reads all slides and submits the whole deck at once.

- **The panel IS the slide. Teach nothing outside it.** Emit NO preamble, prose,
  or ascii diagram in the message before/around the deck — the user does not read
  the message body, they read the panel. If you catch yourself writing an
  explanation before calling `AskUserQuestion`, stop: that text belongs inside a
  slide's `question` field. The message around the call should be empty or a
  single orienting line at most. Anything that won't fit and read cleanly inside
  the panel is too big for a slide — cut it or split it.
- After submit, re-teach only the slides marked **Lost me** — a follow-up deck
  that reframes them from a different angle (new example, simpler framing — not
  louder). Repeat until nothing is lost.

- **Every teaching turn is a deck — no exceptions.** This is true for the WHOLE
  loop, not just the first deck. When the user submits doubts or follow-up
  questions (via "Lost me" or the "Other" field), answer them as a NEW deck — one
  doubt, one slide — NOT as a prose message. The moment you find yourself about to
  write "Good questions — quick answers: 1… 2… 3…" as message text, stop: each of
  those answers is a slide. You stay inside panels until the user exits the skill
  or says they're done.
- One idea per slide — stay inside working memory. If a slide needs two acks
  worth of content, it's two slides.
- Stop when the concept's gap is closed; move to the next.

## Phase 4 — Log

Append one entry per calibrated concept to `~/.claude/calib-log.md` (create it
with an `# Calib log` header if missing). This is a durable, standalone catalogue
— capture the context now, since the conversation may be deleted. Append only;
never rewrite or reorder existing entries. Use today's date and the current
project.

```md
## <concept> — <YYYY-MM-DD>
**Level:** none | heard-of | can-use | solid
**Context:** <one line: what we were doing>
**Project:** <repo path or name, or "—">
```

Log every concept you calibrated, including the `solid` ones (the rating is the
useful record), but you need only log what you actually probed.
