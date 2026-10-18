# Jason OS — Anki / Spaced Repetition v1

Status: DESIGN
Owner: Jason OS Knowledge Brain
Target: Anki card generation with source provenance and optional original-page images

## 1. Product decision

Jason OS will not attempt to make image/diagram understanding a mandatory ingestion dependency.

Multimodal ingestion remains an optional enrichment path. The next learning feature is an Anki card-generation layer built on top of the existing Knowledge Brain.

For v1:

- Jason OS generates the learning material.
- Anki owns spaced-repetition scheduling, review history, intervals, ease and due dates.
- Every generated card should preserve a path back to the original source.
- Image cards should prefer the original PDF/page image over an AI-generated visual description.
- Vision-model output may assist selection later, but it is not required for card generation.

This keeps the Knowledge Brain focused on reliable retrieval and provenance while using Anki for the scheduling problem it already solves well.

## 2. Goals

The v1 system should be able to:

1. Generate concise, atomic Anki questions and answers from Knowledge Brain evidence.
2. Produce text-only cards for ordinary facts, concepts and definitions.
3. Produce visual-recall cards that include an original PDF page image when a source page is useful for learning.
4. Show document title and page number on every card when available.
5. Include a source URL or source locator so the user can open the original material.
6. Preserve chunk/source identifiers for auditability.
7. Export an Anki-compatible package without changing the Knowledge Brain database.
8. Regenerate cards deterministically enough to detect duplicates and avoid repeatedly adding the same note.

## 3. Non-goals for v1

The first version will not:

- replace Anki's scheduler;
- maintain its own SM-2/FSRS scheduling database;
- require vision-model understanding for every image;
- automatically crop every diagram to a perfect bounding box;
- write generated cards back into the Knowledge Brain;
- automatically generate cards from the whole knowledge base without user scope;
- treat AI-generated explanations as authoritative when they are not supported by source evidence.

## 4. Existing provenance that can be reused

The current retrieval path already exposes useful provenance from `hybrid_search_v3.py`:

- `chunk_id`
- `document`
- `page_start`
- `page_end`
- `source_type`
- `source_file_id`
- `source_url`

This is enough to form the first Source Locator contract.

Additional provenance that is useful for media extraction may exist in document metadata, including:

- source filename;
- Google Drive path;
- document checksum;
- ingestion version;
- evidence origin.

The card generator must never invent missing provenance. If a source PDF cannot be resolved, the card may still be generated as a text card, but image generation must fail closed.

## 5. Source Locator v1

Every candidate card should carry a source locator.

Example:

```json
{
  "document_title": "Construction Drawing",
  "document_id": 21,
  "document_checksum": "...",
  "chunk_ids": [23636],
  "page_start": 44,
  "page_end": 44,
  "source_type": "google-drive",
  "source_file_id": "...",
  "source_url": "...",
  "source_filename": "Construction-Drawing.pdf",
  "source_path": "06_Knowledge/..."
}
```

Only fields that are actually known should be populated.

Display rule:

- Always show title when known.
- Show `p.N` or `pp.N-M` when page data exists.
- Show an "Open original" link when `source_url` exists.
- Otherwise show the available filename/path so the user can locate the document manually.

The source URL does not need to deep-link to a PDF page in v1. Page number remains an explicit locator.

## 6. Card types

### 6.1 Text Recall

Use for facts, definitions, rules, figures and conceptual relationships.

Front:

```text
What is the assessment scheme for the Construction Drawing class?
```

Back:

```text
Coursework 50%; Examination 50%.
```

Source:

```text
Construction Drawing — p.2
```

### 6.2 Visual Recall

Use when the original page/diagram itself is useful as a memory cue.

Front:

```html
<img src="jasonos_<media-id>.png">

Which projection method is shown?
Identify the Top / Front / Side views.
```

Back:

```text
Third Angle Projection.
```

Source:

```text
Construction Drawing — p.44
```

The image should be rendered from the original source PDF. Vision-generated replacement images are not part of v1.

### 6.3 Context Card

Use when a concise answer benefits from a small amount of connected knowledge.

Front:

```text
What does this drawing demonstrate?
```

Back fields may include:

- short answer;
- explanation;
- related concepts;
- source locator.

Related information must be visually separated from the source-supported answer so supplementary context is not mistaken for evidence.

## 7. Anki note model v1

Proposed note type: `Jason OS v1`

Fields:

```text
Question
Answer
Explanation
Image
RelatedKnowledge
SourceTitle
SourcePage
SourceURL
SourceFileID
SourceFilename
ChunkIDs
CardKey
Tags
```

Front template:

```html
{{#Image}}{{Image}}{{/Image}}
<div class="question">{{Question}}</div>
```

Back template:

```html
{{FrontSide}}
<hr id="answer">
<div class="answer">{{Answer}}</div>

{{#Explanation}}
<div class="explanation">{{Explanation}}</div>
{{/Explanation}}

{{#RelatedKnowledge}}
<div class="related">{{RelatedKnowledge}}</div>
{{/RelatedKnowledge}}

<div class="source">
  {{SourceTitle}} {{SourcePage}}
  {{#SourceURL}} — <a href="{{SourceURL}}">Open original</a>{{/SourceURL}}
</div>
```

Styling can remain minimal in v1.

## 8. Canonical card manifest

Before Anki export, Jason OS should create a JSON card manifest. The manifest is the auditable intermediate format.

Example:

```json
{
  "schema_version": "anki-card-manifest-v1",
  "generator_version": "sr-v1",
  "deck": {
    "name": "Jason OS::Construction Drawing"
  },
  "cards": [
    {
      "card_type": "visual_recall",
      "question": "Which projection method is shown?",
      "answer": "Third Angle Projection.",
      "explanation": "",
      "related_knowledge": [],
      "source": {
        "document_title": "Construction Drawing",
        "chunk_ids": [23636],
        "page_start": 44,
        "page_end": 44,
        "source_url": ""
      },
      "media": [
        {
          "kind": "pdf_page",
          "page_number": 44,
          "filename": "jasonos_<media-id>.png",
          "sha256": "..."
        }
      ],
      "tags": [
        "jason-os",
        "construction-drawing",
        "visual-recall"
      ],
      "card_key": "..."
    }
  ]
}
```

The manifest should be generated before any `.apkg` output so validation is possible without importing into Anki.

## 9. Card-generation rules

Each card must follow these rules:

1. One primary recall target per card.
2. The answer must be directly supported by selected Knowledge Brain evidence.
3. Avoid broad questions whose answers require several unrelated facts.
4. Prefer short answers.
5. Preserve meaningful units, percentages, section numbers and qualifiers.
6. Do not silently correct or expand source material using general knowledge.
7. If the evidence is ambiguous, do not generate the card automatically.
8. Generated explanation may only restate or connect supported evidence unless explicitly labelled as supplementary.
9. Source locator is mandatory for exported cards.
10. Image cards must refer to a real source page and resolvable source document.

## 10. Duplicate / regeneration policy

A stable `card_key` should be calculated from source identity plus card content.

Suggested v1 input:

```text
schema_version
document checksum
page_start/page_end
source evidence hash
normalized question
card_type
```

The hash allows a future exporter to:

- skip exact duplicates;
- compare regenerated decks;
- preserve an audit trail.

Anki note GUIDs should be derived from `card_key` when possible so repeated exports do not create unnecessary duplicates.

## 11. Media strategy

### v1

Render the full relevant PDF page to PNG/JPEG.

Advantages:

- reliable;
- no vision dependency;
- preserves original context;
- easy to trace to the source page.

### later

Optional crop pipeline:

```text
source page
→ candidate image/drawing region
→ deterministic/manual/vision-assisted crop
→ visual recall card
```

Cropping is an enhancement, not a blocker for v1.

Media names should be deterministic, for example:

```text
jasonos_<document-checksum-prefix>_p0044.png
```

## 12. Source resolution

Image generation requires access to the original file.

Resolution order for v1 should be:

1. explicitly supplied local source path;
2. known Google Drive source metadata / file ID;
3. known source path metadata;
4. fail image generation and keep the card text-only.

A database record pointing only to a page number is not enough to render media unless the source document can also be resolved.

No source path or URL should be fabricated.

## 13. Related knowledge

Related knowledge can be valuable during review, but it must not overwhelm the recall target.

For v1:

- `Answer` contains the required recall answer.
- `RelatedKnowledge` is optional.
- related items should come from explicit graph/retrieval relationships;
- related items should not change the correctness criteria for the card.

The UI/template should visually separate related knowledge from the answer.

## 14. Generation scopes

The first implementation should support a controlled scope rather than whole-library generation.

Recommended order:

1. one document;
2. selected pages/chunks;
3. a user query/topic;
4. later, a curated collection.

Example CLI direction:

```bash
python generate_anki_cards_v1.py \
  --document-title "Construction Drawing" \
  --pages "2,32,44" \
  --output /tmp/construction-drawing-cards.json
```

No DB writes should occur.

## 15. Export strategy

The pipeline should be split:

```text
Knowledge Brain evidence
        ↓
card manifest
        ↓
source/media resolver
        ↓
media render
        ↓
Anki exporter
        ↓
.apkg
```

This keeps question generation independent of the Anki packaging library.

Expected outputs:

```text
deck.json
media/
  jasonos_...png
deck.apkg
```

The JSON manifest remains useful for testing and audit even after the Anki package is produced.

## 16. Validation contract

The first representative prototype should prove:

### Text card

- correct question/answer;
- source page retained;
- source title retained;
- no unsupported claim.

### Visual card

- source PDF resolves;
- correct page is rendered;
- image is embedded into Anki media;
- card question is answerable from the original page;
- source locator is visible on the back.

### Export

- `.apkg` imports successfully into Anki;
- image renders on desktop/mobile Anki;
- source URL is clickable when present;
- no duplicate media names;
- repeated export produces stable note identity.

## 17. Initial representative prototype

The preferred first prototype is a small deck with approximately 5–10 cards containing both text and visual recall.

A technical drawing/training document is useful because it exercises:

- ordinary text;
- page-level provenance;
- visual page rendering;
- related concepts.

However, the source document must be resolvable from a stable local or Google Drive source before image cards are produced.

## 18. Implementation phases

### SR-A — Architecture / contracts

- freeze this card manifest and source-locator design;
- no runtime changes.

### SR-B — Source Locator adapter

- retrieve provenance for candidate chunks;
- resolve title/page/source URL/file ID/path;
- no card generation yet.

### SR-C — Card manifest generator

- generate source-grounded text/context cards;
- validate one-document prototype;
- no Anki binary dependency yet.

### SR-D — Original-page media renderer

- resolve source PDF;
- render requested pages;
- deterministic media filenames;
- no vision requirement.

### SR-E — Anki package exporter

- create `Jason OS v1` note model;
- bundle card manifest + media into `.apkg`;
- stable note GUID/card key.

### SR-F — Representative validation

- import into Anki;
- verify text card;
- verify image card;
- verify source locator;
- verify repeated-export behavior.

Only after SR-F should automatic/bulk deck generation be considered.

## 19. Relationship to multimodal ingestion

Multimodal v2 remains available, but it is no longer a prerequisite for spaced repetition.

The preferred relationship is:

```text
Knowledge Brain
  text / OCR / metadata / provenance
        ↓
Anki generator
        ├── text cards
        ├── context cards
        └── original-page image cards

Optional multimodal vision
        ↓
better candidate selection / crop hints / supplementary description
```

This preserves the successful multimodal engineering work while keeping the learning system reliable when visual understanding is imperfect.
