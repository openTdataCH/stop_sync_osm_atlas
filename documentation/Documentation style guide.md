# Documentation style guide

This page defines how the documentation of both projects is written, linked and illustrated. Follow it when you add or change a page in `documentation/` (review application) or `engine/documentation/` (matching engine). The portal renders both trees together, so they must read as one manual.

## Write for a newcomer

Assume the reader knows Python and web applications, but not this project, Swiss public transport data or OpenStreetMap tagging.

- **Open with the purpose.** The first paragraph says what the page explains and when someone needs it.
- **Define terms before using them.** Link the first use of a project term on each page to the [glossary](0.1%20Glossary.md), or define it in the sentence. Never assume that "profile", "bundle", "stop unit" or "capability" is understood.
- **Describe the current behaviour.** Write "the importer validates the bundle", not "the importer now validates" or "no longer reads CSV files". History belongs in the changelogs.
- **One idea per paragraph, short sentences, active voice, present tense.**
- **Be exact.** Give real values with units (`50 m`, `3 s`), real identifiers and the code location that implements a rule. When a sentence simplifies, say so.
- **Separate rules from data.** Engine pages document rules and contracts, not the numbers of one run. App pages may show live values through `{{stat:…}}` placeholders.
- **Mark plans as plans.** A page or section that describes unimplemented work starts with a `> [!NOTE]` or `> [!WARNING]` alert that says so.

## Use the project's terms consistently

| Use | Avoid | Why |
|---|---|---|
| source stop (engine), ATLAS platform (Swiss) | ATLAS stop when you mean any source | The engine is source-neutral; ATLAS is one source. |
| OSM element; OSM node when it is a node | OSM stop for a single node | An OSM stop unit can combine several nodes. |
| matching rule (predicate in code) | stage, pass, step for the same thing | Rules are configured by name in a profile. |
| match type | method, rule name | The exported field is `method`; the UI and SQL say match type. |
| dataset profile | data profile, config | Not the review app's presentation config. |
| result bundle | export, dump, result files | The bundle is a versioned contract. |
| publish a snapshot | import into the database | Publication is the atomic switch, after staging. |

The [glossary](0.1%20Glossary.md) is the reference for every term. Add new terms there first.

## Structure every page the same way

1. A level-one heading with the owner-scoped number and a sentence-case title: `# E2.1 Exact matching`, `# A1.1 Bundle import and publication`. Unnumbered pages (changelogs, guides) have no number.
2. An opening paragraph: purpose and audience.
3. When the page explains a flow or a structure, a diagram near the top, followed by one sentence on what to look at.
4. The content, in sections with sentence-case headings. Use tables for reference values and numbered lists for sequences.
5. A short **Code** section that names the implementing files, and a **Related pages** list.

Use sentence case for every heading: capitalize the first word, proper nouns (ATLAS, OpenStreetMap, PostGIS) and identifiers only. Navigation titles are taken from the level-one heading, so the heading is the page's public name.

## Link precisely

| From | To | Write |
|---|---|---|
| Any page | A page in the same tree | `[Global statistics](2.3%20Global%20Stats.md)` |
| A page | A section of a page | `[dataset profile](0.1%20Glossary.md#dataset-profile)` |
| Application page | Engine page | `[E2 Matching](../engine/documentation/2.%20Matching%20process.md)` |
| Engine page | Application page or code | The public GitHub URL, `https://github.com/openTdataCH/stop_sync_osm_atlas/blob/main/…` |
| Any page | A code file | The path in backticks, for example `backend/importing/importer.py` |

- Encode spaces in file names as `%20`. Section anchors follow GitHub's rule: lowercase, punctuation removed, spaces replaced by hyphens.
- The portal turns links to served pages into `/docs/<slug>` routes and links code paths in prose to GitHub. Code inside fenced blocks is never rewritten.
- Application pages link to engine pages through the logical path `../engine/documentation/`, which is how the portal and the PDF see both trees. The engine repository can be private, so links to engine source files render as plain text unless `DOCS_ENGINE_BLOB_BASE` is set (see [A2.8](2.8%20Documentation%20Page%20Delivery.md)).
- `tests/test_docs_links.py` fails on a broken link between pages, and `tests/test_docs_rendering.py` on any link or section anchor that does not resolve in the portal or the PDF.

## Illustrate with the diagram kit or Mermaid

Choose the lightest form that shows the idea:

| Form | Use for | Source |
|---|---|---|
| Table | Values, rules, mappings, comparisons | Markdown |
| Mermaid | Short linear flows and decision trees, up to about 10 nodes | A `mermaid` fenced block in the page |
| Kit diagram | Overviews, ownership boundaries, domain illustrations, anything larger or needing exact layout | `documentation/diagrams/catalog.py` |

### The visual vocabulary

The kit (`documentation/diagrams/kit.py`) is a small library of drawing macros. Every kit diagram uses the same shapes, colours and arrows, so a reader learns them once.

| Element | Means | Macro |
|---|---|---|
| Rounded box | A component or process | `box()` |
| Box with title at the top | A container with parts inside | `box(…, valign='top')` |
| Large tinted area with a tab | Who owns the parts inside | `zone()` |
| Cylinder | A database or durable store | `store()` |
| Sheet with folded corner | A file or set of records | `document()` |
| Browser window | A user interface | `browser()` |
| Chevron | A phase in a sequence | `chevron()` |
| Rounded tag | A value, label or state | `pill()` |
| Dark numbered circle | The order of events, explained below the figure. Where nothing happens in sequence, number in reading order: top to bottom, then left to right | `step()` |
| Circle, optionally lettered | A map marker (P platform, S stop position) | `node()` |
| Solid arrow | Data moves | `arrow(kind='flow')` |
| Dashed arrow | One part starts or calls another | `arrow(kind='invoke')` |
| Dotted arrow | Optional input, reuse or a human action | `arrow(kind='optional')` |
| Line without arrowhead | An association, such as a match | `arrow(…, end_head=False)` |

Colours come from the application's design tokens and have two vocabularies. **Never mix them in one diagram.**

- **System diagrams** show ownership: engine green (`ENGINE`), review application navy (`APP`), the shared result-bundle contract purple (`CONTRACT`) and outside services grey (`EXTERNAL`). These match the portal's Engine, App and Shared badges.
- **Domain diagrams** show data, with the map colours: ATLAS navy (`ATLAS`), OpenStreetMap green (`OSM`), GTFS orange (`GTFS`), unmatched red (`UNMATCHED`).

Text is 15 units for headings, 13 for body and 12 for notes, and never below 11. Code identifiers use the monospace font (`code()`). The kit measures every label and the build fails with a `LayoutError` when text does not fit its shape.

### Add or change a kit diagram

1. Add a function to `documentation/diagrams/catalog.py` that builds a `Diagram` from kit macros, and register it in `DIAGRAMS` with its name and tree (`app` or `engine`).
2. Run `python3 documentation/diagrams/build.py` from the application repository (or `npm run docs:diagrams`, or the VS Code **Docs** task, *Regenerate SVG diagrams*). It writes `<tree>/documentation/images/<name>.svg`; engine diagrams go into the sibling engine checkout. Only the Python standard library is needed; `--check` reports stale files without writing.
3. Reference the image with a meaningful alt text: `![The matching rules, in order](images/matching-rule-ladder.svg)`.
4. Below the image, say what to look at. When the figure has numbered steps, follow it with a numbered list that explains each number, in the same order.
5. Commit the generated SVG with its source change. `tests/test_docs_diagrams.py` fails when a committed SVG differs from its source or a page references a missing image.

A figure has no title of its own: the page heading above it names it, and a title inside the image would repeat it. Put a one-line summary in the text instead.

Never edit a generated SVG by hand: the next build overwrites it. Keep the canvas at most 960 units wide; the portal scales it to the article column and the PDF to the page width. The build crops each canvas to the drawing plus a 22-unit margin, and fails with a `LayoutError` when a shape comes closer than 12 units to the left or right edge or leaves the canvas height given to `Diagram`.

The kit writes self-contained SVG with presentation attributes only (no CSS, scripts, web fonts or external references), so the same file renders identically in the portal, on GitHub and in the PDF.

### Write Mermaid diagrams

- Prefer `flowchart LR` for pipelines and `flowchart TD` for decisions. Keep labels short and in sentence case; break lines with `<br/>`.
- Declare every node of a subgraph inside that subgraph, and draw edges that cross subgraphs outside of both. Mermaid nests a subgraph inside another when an edge to it is declared inside the other one, which silently changes the meaning of the picture.
- Do not put `{{stat:…}}` placeholders inside Mermaid; the PDF renderer rejects them.
- The PDF uses pre-rendered SVGs. After changing a Mermaid block, run `npm run docs:render-mermaid` before `npm run docs:build-pdf`.

## Write numbers, code and alerts

- Units after a space: `50 m`, `1.5 s`, `768MB` only when it is a literal setting value.
- Priorities as P1, P2, P3. Percentages with `%`.
- Identifiers, file paths, settings and commands in backticks. Commands that a reader runs go in fenced blocks with a language (`bash`, `python`, `json`).
- GitHub alerts render in the portal and the PDF: `> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`, `> [!CAUTION]`. Use them sparingly, for information a reader must not miss.
- Write formulas in plain text with Unicode symbols: `d₂ / d₁ ≥ 4`, `shared stops ÷ max(stops in A, stops in B)`. LaTeX (`$…$`) renders in the portal through MathJax, but the PDF prints it as raw TeX; use it only for formulas that plain text cannot express.

## Check a page before you publish it

- [ ] The first paragraph says what the page is for.
- [ ] Every project term is defined or linked to the glossary at its first use.
- [ ] Statements describe current behaviour and match the code they name.
- [ ] Headings are in sentence case; the title starts with the owner-scoped number.
- [ ] Every diagram has alt text and a sentence saying what it shows; numbered figures have a numbered explanation.
- [ ] `python -m pytest tests/test_docs_links.py tests/test_docs_diagrams.py tests/test_docs_rendering.py -q` passes.

## Code

| File | Role |
|---|---|
| `documentation/diagrams/kit.py` | Diagram macros: palette, typography, shapes, arrows, legends |
| `documentation/diagrams/catalog.py` | One function per documentation diagram |
| `documentation/diagrams/build.py` | Renders the catalog; `--check` reports stale files |
| `tests/test_docs_diagrams.py` | Keeps generated SVGs current and image references valid |
| `tests/test_docs_rendering.py` | Keeps code literal and every portal and PDF link and anchor resolvable |

## Related pages

- [A2.8 Documentation portal](2.8%20Documentation%20Page%20Delivery.md): how the portal renders, links and exports these pages.
- [Contributing](Contributing.md): where to start a code contribution.
- [Glossary](0.1%20Glossary.md): the meaning of every project term.
