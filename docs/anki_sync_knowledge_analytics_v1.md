# Jason OS — Anki Sync & Knowledge Analytics v1

Status: DESIGN
Depends on: Anki / Spaced Repetition v1 card identity + source locator

## Purpose

Jason OS should be able to evaluate learning progress over time by connecting Anki review behavior back to Knowledge Brain topics and sources.

Anki remains the scheduler. Jason OS interprets what the reviewed cards mean.

## Core identity contract

Every exported Anki note should carry a stable Jason OS identity:

```text
CardKey
ChunkIDs
DocumentID
Topic
SourceTitle
SourcePage
SourceURL
```

`CardKey` is the primary join key between:

```text
Knowledge Brain evidence
        ↕
Anki note/card
        ↕
review history
```

Anki-specific note/card IDs may also be stored after sync, but they are not the canonical knowledge identity.

## Local sync architecture

Preferred model:

```text
Anki Desktop
   ↓
local Anki integration
   ↓
Jason OS local sync agent
   ↓ encrypted outbound connection
Jason OS
```

The local Anki interface should remain bound to the user's device. It should not be exposed directly to the public Internet.

The sync agent may push normalized review telemetry to Jason OS or provide it on demand.

## Review data to capture

The first analytics layer should normalize, when available:

```text
CardKey
AnkiNoteID
AnkiCardID
Deck
Tags
ReviewTimestamp
ReviewRating
IntervalBefore
IntervalAfter
Due
LapseCount
ReviewCount
CardState
Stability
Difficulty
Retrievability
```

Not every Anki version or scheduling mode exposes every field. Missing metrics must remain null rather than being guessed.

## Knowledge metrics

Jason OS should distinguish at least four concepts.

### 1. Coverage

How much of the selected knowledge scope has been converted into reviewable cards and actually introduced.

Examples:

- topics with at least one reviewed card;
- source documents represented;
- source pages represented;
- reviewed cards / generated cards.

### 2. Recall strength

How reliably the user currently recalls reviewed material.

Possible signals:

- recent Again/Hard/Good/Easy distribution;
- true retention over a meaningful time window;
- stability / retrievability when available;
- lapse frequency;
- repeated failures.

This is an estimate of recall strength, not a claim that Jason OS can measure absolute human knowledge.

### 3. Weak areas

Group card-level weakness back into Knowledge Brain structure:

```text
card
→ chunk
→ document
→ topic/domain
```

This allows reports such as:

```text
Weak topic: contract-administration
Evidence:
- 14 reviewed cards
- 6 repeated lapses
- lower recent retention than baseline
```

### 4. Knowledge growth

Track changes across time windows:

- new reviewed concepts;
- retained concepts;
- topics newly covered;
- topics whose recall strength improved or declined;
- repeated failure concepts resolved.

## Periodic knowledge report

A weekly report should emphasize actionable trends rather than raw review counts.

Example structure:

```text
Knowledge coverage
Recall / retention trend
Strong topics
Weak topics
Repeated failures
High forgetting-risk cards
New concepts learned
Suggested review focus
Source documents worth revisiting
```

Monthly reports may add broader domain-level trends.

## Source-aware remediation

When a weak card is detected, Jason OS should be able to trace it back to the original knowledge source.

Example:

```text
Weak concept:
Third Angle Projection

CardKey:
...

Source:
Construction Drawing — p.44

Action:
- reopen original page
- review related chunks
- regenerate or split the card if necessary
```

This is the main advantage of linking Anki to the Knowledge Brain rather than treating Anki as an isolated deck store.

## Card quality diagnostics

Repeated failure does not always mean the user lacks knowledge. It may indicate a bad card.

Jason OS should flag candidates such as:

- one card with unusually high lapse frequency;
- overly broad prompts;
- ambiguous questions;
- cards whose answer contains several independent facts;
- cards missing enough source context;
- visual cards whose image does not clearly support the prompt.

Suggested actions:

```text
keep
rewrite
split
add context
add source image
retire
```

No automatic deletion should occur without explicit user approval.

## Privacy boundary

Review telemetry is personal learning data.

The sync design should:

- send only data needed for learning analytics;
- avoid exposing a local Anki API publicly;
- avoid copying unrelated Anki decks unless selected;
- make deck scope explicit;
- keep source credentials out of card fields and analytics;
- allow sync/analytics to be disabled independently of card export.

## Implementation order

Anki sync and periodic analytics should begin only after stable `CardKey` identity exists.

Recommended phases:

```text
SR-A  architecture
SR-B  source locator
SR-C  card manifest generator
SR-D  original-page renderer
SR-E  Anki exporter
SR-F  representative import validation
SR-G  local Anki sync connector
SR-H  knowledge analytics
SR-I  periodic weekly/monthly assessment
```

## SR-G validation contract

The first Anki sync proof should demonstrate:

1. a Jason OS card can be matched back using `CardKey`;
2. review history can be read without changing Anki scheduling state;
3. review telemetry maps back to document/topic/chunk;
4. no unrelated decks are read when a deck scope is configured;
5. local integration is not exposed publicly.

## SR-H validation contract

Using a small test deck, Jason OS should correctly produce:

- reviewed-card count;
- weak-card list;
- repeated-failure list;
- topic-level aggregation;
- source locator for at least one weak card.

The report should clearly label insufficient-data cases rather than generating false precision.

## Long-term goal

The desired loop is:

```text
Knowledge Brain
      ↓
Anki cards
      ↓
daily review
      ↓
review telemetry
      ↓
Jason OS knowledge analytics
      ↓
weak-area detection
      ↓
original source / related knowledge
      ↓
better cards and targeted learning
```

This closes the learning loop without requiring Jason OS to replace Anki's scheduling engine.
