# rooms-app

You photograph a room, type its width, length and ceiling height, and describe what you want: what the room is for, the style, a
budget, the pieces you must have, what to keep and what to remove. A team of model-backed agents and deterministic steps then
**furnishes the room with real catalog items** and places them in a layout that is checked to be buildable: nothing overlaps,
nothing blocks a door, window or radiator, every piece can be walked up to and the total stays within the budget. You get a floor
plan, a shopping list with prices and alternatives, the reasons behind the design, a 3D view, the new furniture drawn into your own
photo, and a chat in which you ask for changes ("make it cheaper", "move the desk closer to the window") that are checked the same
way before they are applied, and can be undone.

The stack is a [LangGraph](https://langchain-ai.github.io/langgraph/) graph (the model-backed steps are the Room Analyst, the
Designer, the Architect and the chat edit; the solver, the Critic and the rest are plain Python) behind a FastAPI API that streams
each run as Server-Sent Events, Postgres with pgvector for LangGraph's checkpoints, its store (the catalog's embeddings) and the
projects registry, S3-compatible object storage (MinIO locally) for the photos, models through [OpenRouter](https://openrouter.ai/),
and a Next.js 16 frontend with a react-three-fiber 3D view.

The room photos in `fixtures/` and in the eval dataset are **synthetic placeholders** (an empty room drawn with Pillow and labeled
PLACEHOLDER, see [fixtures/README.md](fixtures/README.md)): nothing has been measured on real photos yet.

[![The 3D view of a design; click to download the demo video](docs/img/3d-orbit.png)](docs/demo/demo.webm)

[Demo video](docs/demo/demo.webm) (webm, 6.8 MB, 77 s, recorded on `make dev-stub`: fixture replay, no model calls; GitHub offers
it as a download) · [Slides](docs/slides.md) ([PDF](docs/slides.pdf)) · [Contributing](CONTRIBUTING.md) ·
[Project board](https://github.com/users/Nelev/projects/1)

## The workflow

1. **Describe the room.** **New project** opens a three-step wizard: 1 to 3 photos (drag and drop or the camera; an iPhone's HEIC
   photo is stored as a JPEG), the room's width, length and ceiling height in meters, then the brief. **Design my room** uploads
   the photos, creates the project and starts its design run; the page moves to the project's workspace as soon as the run has
   started, and the run goes on without it.

   ![The wizard's brief step](docs/img/wizard-brief.png)

2. **Follow the run.** The **Room** tab's timeline lists each step as it starts and ends, with its summary, its time and its model
   cost, and groups the Critic's rounds. Reload the page or come back later: it rejoins the run from its first event.

   ![The run timeline](docs/img/run-timeline.png)

3. **Confirm the room.** After the Room Analyst has read the photos, the run **pauses** for you. **Accept as analyzed** on the
   timeline continues with the room as read. **Confirm the room** opens the editor instead: the photos next to an editable plan, where you
   drag doors, windows and radiators along the walls, type their sizes, add or delete features, and add the furniture you keep
   (the analyst ignores furniture, so kept pieces are added here). Features the analyst was unsure of (confidence under 0.8) are
   highlighted, and the room cannot be confirmed while it has problems (a feature off its wall or above the ceiling, furniture
   outside the room); the editor lists them.

   ![The room editor](docs/img/room-confirm.png)

4. **The design runs.** Designer, Architect, Refiner, Sourcer, solver and Critic, about a minute with live models (see
   [Evaluation](#evaluation)). The timeline shows each Critic round.

5. **Read the design.** The **Design** tab has the rationale, the Critic's review (every rule, passed or failed, with its reason),
   the floor plan and the shopping list with the total against the budget. Selecting an item in the plan or the list highlights it
   in both and shows the Sourcer's alternatives for it, with a link to the product page when the catalog has one.

   ![The Design tab](docs/img/design.png)

6. **Look at it in 3D.** The **3D** tab orbits the room from above, stands you at eye level (1.6 m, turning in place), or, once a
   photo is matched (next step), shows the room from that photo's camera. Items with a 3D model in the catalog are drawn with it;
   the others are grey boxes of the item's real size.

7. **See it in your photo.** **See it in your photo** (on the **Photo** tab) opens the photo view. The first time, you match the
   photo's camera to the room: pick a corner (floor A to D, or the ceiling above them), click where the photo shows it, and so on
   for at least 4 corners; **Match camera** solves the camera, draws the room's edges over the photo with the reprojection error,
   and you confirm or redo. Then the new furniture is drawn into the photo, hidden where the furniture you keep stands in front of
   it, with a before/after slider and **Export PNG** at the photo's own resolution.

   | Camera matching | The design in the photo |
   | --- | --- |
   | ![Camera matching](docs/img/camera-match.png) | ![The design in the photo](docs/img/photo-composite.png) |

8. **Ask for changes.** The chat panel beside the tabs takes a message ("Make it cheaper", "Move the desk closer to the window",
   "Add a plant" are offered as suggestions). Clicking an item in the floor plan or the 3D view, or on its **Mention** chip under the
   chat, adds `@<item id>` to the message.
   The reply streams in, with a chip per tool the model ran (red when the edit was refused, with the reason). An applied edit
   updates every tab, highlights the items it changed for 4 seconds and offers **Undo**, which reverts the project to the
   checkpoint before the edit.

   ![A chat edit](docs/img/chat-edit.png)

## How the agent works

One **thread** is one project. Its first run designs the room; each chat message starts another run on the same thread, so the
design, the chat history and the usage live in one state (`backend/app/graph/state.py`), saved by the checkpointer after every
node. `backend/app/graph/graph.py` builds the graph, `routing.py` holds the conditional edges, and each node is a module in
`backend/app/graph/nodes/`.

```
design run (input: photo_keys, dimensions, brief)

START → route_input → analyze_room → confirm_room → design → architect → refine → source → solve → critic → present → END
                                     (interrupt)               ▲                     ▲                 │
                                                               ├── relation fixes ───┼─────────────────┤   round < 3
                                                               │                     └── swaps only ───┤   round < 3
                                                                                                       └→ present: all rules pass, or round 3;
                                                                                                          the best round's design is kept
        no_critic flag: solve → present

chat run (input: chat_message)

START → route_input → chat_edit ─┬→ solve → present → END     (the edit changed something)
                                 └→ END                       (every edit refused, or none asked)
```

The routing is plain Python (`after_route_input`, `after_solve`, `after_critic`, `after_chat_edit`), so the order of the steps is
fixed: only the Critic's loop and the chat branch choose where to go. A run is capped at `RECURSION_LIMIT = 25` graph steps; the
longest, a resumed design run with three Critic rounds, takes 18.

| Node | Uses a model? | What it does |
|---|---|---|
| `route_input` | no | Sets the run's `mode`: a chat message is moved into `messages` and goes to `chat_edit`; any other input starts a design. |
| `analyze_room` | yes, vision (`analyze_room` role) | Reads the walls, doors, windows, radiators and other fixed features from the photos, wall by wall, three times in parallel, and keeps what at least two readings agree on. The typed dimensions are the room's. |
| `confirm_room` | no | `interrupt()`: the run pauses until the user confirms or corrects the room, and resumes with the confirmed `RoomSpec`. |
| `design` | yes (`design` role) | The Designer: zones, a palette and the objects to add. Code then adds any must-have the model left out and drops optional objects until the objects fit the free floor area. |
| `architect` | yes (`architect` role) | Turns the design into a scene graph: the nodes come from the room and the design, the model gives only the edges, from a fixed set of relations. Validated and repaired once; in a later round, applies the Critic's relation fixes to the existing graph. |
| `refine` | no | The Refiner: adds a `right_of` edge between siblings that share a parent item and a relation, so the solver has one reading of them. |
| `source` | no (embedding search) | The Sourcer: a catalog item per object, within the object's share of the budget, found by embedding search plus hard filters; the item's real size replaces the object's box. Applies the Critic's swaps. |
| `solve` | no | Places the scene graph by seeded backtracking (`app/geometry/solver.py`), through a fallback that shrinks or drops what does not fit (`fallback.py`), then validates the layout. A chat edit is only validated. |
| `critic` | no (rule-based) | Turns the validation into hard rules, adds soft rules, scores the round, keeps the best round, and sends actions to the Architect or the Sourcer, for at most three rounds. |
| `present` | no | Builds the render-ready `Scene` (`app/scene/builder.py`), the shopping list's total and the rationale. |
| `chat_edit` | yes, tool calling (`chat_edit` role) | A small tool-calling loop inside the node: the model edits the design with seven tools, each checked against the room and the other items. Ends with a `LayoutDiff`. |

Each node streams a `step` event when it starts and ends (`StepEvent`: node, status, round, summary, duration, cost), which the
run timeline shows; `chat_edit` also streams a `tool` event per tool call (`ToolEvent`).

### Stub and live nodes (`backend/app/graph/stub.py`)

The whole graph runs without a model key. `stub.live(node)` decides, per node, whether it calls the model: it is true when
`OPENROUTER_API_KEY` or `LLM_RECORDINGS` is set. A node that is not live replays its step from `fixtures/small-bedroom/`: its output
(sent through `FakeLLM`, so the run still streams a model message) and its recorded stream events, paced by `STUB_PACE` seconds per
second of the fixture step's duration. The deterministic nodes (`refine`, `source`, `solve`, `critic`, `present`) always run their
real code; `refine` and `source` (and a chat turn's `solve` and `present`) take their step events from the fixture. Whatever photos and brief you enter in stub mode, the
model-backed steps replay the 3.2 x 3.4 m small bedroom.

This is what `make dev-stub` serves (free and offline), what CI and most tests run, and what the demo was recorded on. Because
every node calls `stub.live(...)` through the module, a test makes a single node real with
`monkeypatch.setattr(stub, "live", lambda node: node == "architect")` and keeps the rest replayed. The other choice, a separate
fake graph, would have had to be kept in step with the real one by hand.

**Recorded model I/O (`backend/app/llm/recorded.py`).** With `LLM_RECORDINGS` set to a folder, `get_llm(role)` returns
`RecordedChatOpenAI` and the catalog's embeddings come from `RecordedEmbeddings`: every node runs its real code (`stub.live` is
true) and only what goes over the network is replayed. A chat call's recording is `<role>-<hash>.json`, the hash covering the model,
the messages (images included) and the bound tools; embeddings are kept in `embeddings.json` by text hash, as int8 (cosine
similarity ignores scale). With a key, a call not recorded yet is made and recorded, one at a time, and refused once the recordings
cost `LLM_RECORD_MAX_COST` (default 0.4 USD); without one, a missing recording raises `MissingRecording`. `LLM_REPLAY_DELAY` paces each
replayed reply. The E2E suite runs on it (see [Testing](#testing-and-ci)). It sits at the gateway rather than in the nodes because the
gateway is the one place every model call passes through: the prompts, the parsing, the repair retry and the tools all run for real,
so the suite tests the code that ships. The price is that any change to a prompt, a tool, a role's model or the catalog changes a
hash and invalidates the recordings.

### The Room Analyst (`nodes/analyze_room.py`, `prompts/analyst/room.md`)

The vision model is told the typed dimensions ("exact: scale every size you estimate to them"), the coordinate convention and how
the walls are named (wall A is the one the first photo shows most of), and goes wall by wall, A to D. For each feature it gives the
offset along the wall as a fraction, the width, height and sill height, the door's swing and hinge, a confidence per estimate and
one for the feature itself, and `null` for anything it cannot see instead of a guess. The reply is a `RoomReading` (structured
output).

The room is read `RUNS = 3` times in parallel. Features of the same type on the same wall whose centers are within `TOLERANCE = 0.5`
m are the same feature; one seen in at least `MIN_VOTES = 2` readings is kept, with the median of its sightings and a confidence
scaled by the share of readings that saw it. A dropped feature, and every unknown value (replaced by a per-type default size), become
a warning on the `RoomSpec`, which the editor shows. Voting costs three calls instead of one; the `analyst_mode` flag (the
single-pass ablation) reads the photos once. Whatever the model reads, the room's dimensions are the typed ones.

The prompt and `analyze()` accept detection overlays (boxes a detector drew on the photos), but no detector exists yet (B-06):
`confirm_room` always sends `overlay_keys: []`.

### Confirming the room (`nodes/confirm_room.py`)

The node is one `interrupt()` with the analyzed room as its payload (`ConfirmRoom`); the API resumes it with a `Command(resume=room)`.
It calls no model, on purpose: when a run is resumed, LangGraph runs the interrupted node again from its start, so a model call
placed before the `interrupt()` would be made, and paid for, twice. The analysis is its own node before it.

### The Designer (`nodes/design.py`, `prompts/designer/design.md`)

The model plans zones, a 3 to 5 color palette and the objects, each with a category from the catalog's categories, a bounding box,
a quantity and a priority (`must` or `nice`). The prompt states the limits; code then enforces them, because a model does not
reliably follow them:

- **Must-haves.** `add_must_haves` checks each must-have of the brief against the objects (`covers`: all its words in the object's
  name, and the same catalog category, so a "desk lamp" is no "desk"). A matching `nice` object becomes `must`; a missing one is
  added with the size of its category's median catalog item.
- **Object count scaled to the room.** I-Design's main failure is overfilling a room. `fit` drops optional objects, one unit at a
  time, nice-to-haves first and the last listed first, until there are at most one object per `AREA_PER_OBJECT = 1.5` m2 of free
  floor and their footprints cover at most `MAX_FILL = 0.4` of it (rugs excluded, kept furniture subtracted from the floor). The
  brief's must-haves are never dropped here; if they alone overfill the room, the solver's fallback reports it.

### The Architect (`nodes/architect.py`, `prompts/architect/`)

The scene graph's nodes are not the model's to invent: the four walls, the room's doors and windows (fixed roots) and the design's
objects are listed for it, and it returns only edges. The relation vocabulary is fixed (`Relation` in `app/schemas/design.py`):
`against_wall`, `in_corner`, `left_of`, `right_of`, `in_front`, `behind`, `on`, `adjacent` and `facing`. Positions are never asked
of the model: a solver turns relations into coordinates, which is what makes the layout checkable.

`left_of` and `right_of` are the left and right **of a viewer facing the parent's front** (so `left_of` is the parent's own right).
This was an owner decision (commit `a0ab737`), so the prompt's rule and the solver read sides the same way; `test_solver.py` pins it.

The graph is checked by the B-07 validator (`app/geometry/graph_validate.py`: duplicate or unknown nodes, cycles, `against_wall` to
something that is not a wall, children pushed out of the room by a wall, too many children along a side, something between two
`adjacent` items, an item against a wall that would block a door or window wherever it stands) plus the Architect's own rules: a
fixed node is never a source, every object has exactly one `facing` edge, and every object is placed relative to a wall, door or
window, directly or through other objects. If anything fails, one repair call (`revise`) gets the messages; whatever is left goes on
to the solver and the Critic.

When the Critic sends relation fixes, the Architect does not draw a new graph: `revise` gets the current graph and the instructions,
and the reply's edges replace only those of the objects they place. A redraw would lose what was already good and give the
Critic a different layout to judge each round.

### The Refiner (`nodes/refine.py`)

Siblings that share a parent item and a relation (three things `on` a desk, two chairs `in_front` of a table) can be read several
ways. The Refiner, with no model, adds a `right_of` edge from each to the one before it in graph order, skipping pairs already linked
and edges that would close a loop. Children of walls, doors and windows are left alone (the solver spreads them along the wall), and
so are items with a quantity over 1 (the validator lines their copies up). The edges are appended, so each node's first placing
edge, the one the solver places it by, stays the one to its parent.

That is also the limit: since the solver enforces only a node's first placing edge, these ordering edges do not change layouts yet;
they record the order and feed the validator's footprint checks. The Critic therefore counts an unmet ordering edge as **soft** and
asks for no fix, since asking the Architect for something the solver ignores would only spend rounds.

### The Sourcer (`nodes/source.py`, `app/catalog/`)

The catalog is 223 items in 15 categories (`data/catalog/<category>.json`, each a `CatalogItem`: size, price in EUR, style tags,
color, an optional GLB model, product page and image). At startup it is loaded into LangGraph's store, in the `("catalog",)`
namespace, with an embedding of each item's name, description, style tags and color (`openai/text-embedding-3-small`, 1536
dimensions, through OpenRouter): an `AsyncPostgresStore` (pgvector) with `DATABASE_URL` and a key, otherwise an empty
`InMemoryStore`. The seed runs once, when the namespace is empty.

For each object, the store ranks the items of its category by similarity to a query (the swap instruction, the name, the style and
the material), and the **hard filters** are applied in code (`app/catalog/search.py`): width, depth and height within 10% of the
object's box, the footprint's aspect ratio within 10% of the box's (an item stretched to a box of another shape looks distorted,
I-Design's resize problem), and the price within the object's budget share. When nothing passes, an item of another shape is
accepted if it fits inside the box. Items are placed at their real size, never scaled: the chosen item's size overwrites the box.

The **budget share** is a provisional heuristic. Items the design keeps are charged first. Each object still to source gets a
share of what is left in proportion to its category's median catalog price times its quantity, swaps first, then must-haves, then
nice-to-haves, so the total stays within the budget unless the kept items already exceed it. An object for which nothing fits keeps
its box (rendered as a grey box, priced at nothing).

**Swaps** are the Critic's `sourcer` actions ("shorter wardrobe", "smaller sofa"): the current item is excluded and the instruction's
words set the constraint (cheaper: a lower price; shorter: a lower height; smaller or larger: a smaller or larger footprint). If no
other item fits, the object keeps its item when the budget allows. Up to `ALTERNATIVES = 4` other candidates per object are kept
for the Design tab.

### The solver and its fallback (`app/geometry/solver.py`, `fallback.py`, `nodes/solve.py`)

An edge places its source relative to its target. Each object's **first placing edge** (not `facing`; `adjacent` last; none that
closes a loop) picks its parent; walls, doors and windows are fixed parents; an object with no placing edge may stand anywhere.
Objects are placed **depth group by depth group**, each at a position sampled inside the box its relation allows in the parent's
frame (`child_box`; up to `GAP = 0.2` m from an item parent), and rejected if it collides, blocks an opening, is too tall, or leaves
no room inside the room for its cluster (it and its children). After `TRIES = 50` failed samples the group is a dead end: it is
cleared and the group above is re-sampled, one group further up after every `RETRIES = 3` dead ends. A node with quantity n is
placed n times, the copies as `<id>_2`, `<id>_3`, and so on.

The search is **seeded** (the seed is the Critic round: 1, 2, 3) and stops after `STEPS = 5000` sampled positions. The step limit
decides the outcome, so the same input gives the same layout on any machine; the wall-clock budget (`BUDGET = 30` s in the solve
node) is only a safety net, far above the 0.1 to 0.4 s a failing solve takes on an idle machine. A time limit would have made the
result depend on the machine's load. The tradeoff: 5000 steps bound how deep the backtracking goes, so a graph that is solvable but
needs a longer search is reported as not fitting.

When the whole graph is unsolvable, the **fallback** adds items back one at a time (must-haves before nice-to-haves, parents before
children, each group in the Designer's order of importance), re-solving each time. An item whose addition makes the set unsolvable
is replaced by the next smaller catalog item of its category (same height within 10%, no wider, no deeper), else dropped; an item
placed only relative to dropped items is dropped with them. The `FallbackReport` says what was resized or dropped and why
(`too_big`: does not fit even alone; `no_space`: not beside the items kept; `depends_on_dropped`; `out_of_time`), and the Critic and
the rationale pass it on.

The solve node then validates the layout: the graph's issues, the layout checks (`app/geometry/checks.py`: collisions, blocked
doors, windows and radiators, items above the ceiling, and items a person cannot walk up to through a 0.6 m walkway from a door),
and every edge of the graph against the layout (`relation_unmet`), since the solver only honoured each node's first one.

### The Critic (`nodes/critic.py`, `routing.keep_best`)

The Critic is **rule-based on purpose**: its verdict is deterministic, costs nothing, runs offline and is tested like any other
function. A vision model reading renders was the other option (the `critic` role exists, with a vision model, and the eval's VLM
judge uses it); it would have made each round's verdict vary and cost money, and on box renders it has little to see.

| Rule | Kind | Fails when | Action |
|---|---|---|---|
| `graph_valid` | hard | the B-07 validator finds an error | Architect: fix it |
| `relations_kept` | hard | an edge (other than a sibling ordering edge) is not kept by the layout | Architect: make the relations agree, or drop this one |
| `no_collisions` | hard | items overlap, or an item is above the ceiling | Architect: place it elsewhere; Sourcer: a shorter item for the ceiling |
| `openings_clear` | hard | an item blocks a door's swing, or the strip in front of a window or radiator | Architect: place it elsewhere |
| `reachable` | hard | an item cannot be reached through a 0.6 m walkway | Architect: leave a walkway to it |
| `everything_fits` | hard for a dropped must-have, soft otherwise | the fallback dropped or resized something | Sourcer: a smaller item, for a must-have dropped as too big or with no space |
| `siblings_ordered` | soft | a Refiner ordering edge is not kept | none (the solver does not enforce it) |
| `desk_near_light` | soft | a desk is more than `NEAR_LIGHT = 1.0` m from every window's zone (when the room has a window) | Architect: move it near a window |
| `bed_not_facing_door` | soft | a door's swing is centered straight ahead of a bed's foot, within the bed's width | Architect: turn or move it |
| `visual_balance` | soft | the footprint-weighted center of the furniture (kept pieces included) is more than `BALANCE = 0.25` of the room's width or length off its center | Architect: spread it more evenly |

A round's score is (hard issues, soft issues). `keep_best` keeps the best round so far: fewer hard issues, then fewer soft ones, and
ties keep the earlier round. The run goes back when the critique has actions and the round is under `MAX_ROUNDS = 3`: to the
Architect if any action is for it (the Sourcer runs after it anyway), else straight to the Sourcer, so only the stages that need to
change run again. When the critique asks for nothing, or after the third round whatever it asks, the **best** round's scene graph,
candidates, layout, validation and fallback report are restored, not the last round's; its summary says when the issues were not
fixed, or when an earlier round won. The loop therefore always ends after at most three rounds.

### The Presenter (`nodes/present.py`, `app/scene/builder.py`)

Deterministic. The `Scene` is the confirmed room, each placement with its catalog item (the GLB URL and which axis is the model's
front; no item renders as a box), one area light per window (`WINDOW_LIGHT = 5.0`) and the cameras matched to the user's photos so
far: cameras come only from camera matching, never from the graph. The rationale is assembled in code from the design's summary,
the item count and total against the budget, the objects without a catalog item, the fallback's summary and the Critic's verdict:
a model would only reword these, at a cost, and with nothing to replay offline. A chat run keeps `chat_edit`'s answer as its
rationale. The run's output (`RunOutput`) carries the scene, the layout, the critique, the last chat diff, the rationale, the total
(the price of every placed item, copies included) and the brief's budget.

### The chat edit (`nodes/chat_edit.py`, `graph/chat_tools.py`, `prompts/chat_edit/system.md`)

As in CoA's ReAct agent, but as a loop inside one node: the `chat_edit` model is called with the tools bound, each tool it calls
runs on the design as edited so far, and the loop ends when the model answers in plain text (at most `MAX_CALLS = 8` model calls per
message; it sees the last `HISTORY = 10` chat entries). The system prompt lists the design's items by id and names the `@`-mentions
in the message, flagging ids that are not items of the design. Each tool takes the state through `InjectedState` and returns a
`Command`: its state update (scene graph, layout, candidates) plus a short `ToolMessage` for the model. A refused edit returns no
update and a `ToolMessage` with status `error` and the reason.

| Tool | What it does |
|---|---|
| `get_layout` | The room (walls, features, kept furniture) and every item: id, catalog item and price, position, rotation, size, relations |
| `move_item` | Moves an item's center to (x, y), carrying the items placed relative to it; relations the new place breaks are dropped |
| `rotate_item` | Turns an item in place, with what it carries |
| `swap_item` | Another catalog item of the same category within the budget left, by request ("cheaper", "white", "larger oak") or by id; kept in place when it fits there, else re-solved locally |
| `add_item` | A new catalog item placed by a relation to an item, wall, door or window, re-solved locally |
| `remove_item` | Removes an item and what stands `on` it |
| `explain` | An item's relations, catalog item, alternatives and failing checks |

Every other item stays **pinned**. An edit is checked against them with the same layout checks as the solve node (plus: inside the
room, and no item left unreachable that was reachable before) before it is applied. An added item, or a swapped one that no longer
fits where the old one stood, is placed by the solver with the other placements pinned (`place`, `SEEDS = 3` seeds, up to
`OPTIONS = 5` catalog items tried). The prompt tells the model not to retry another position or item on its own after a refusal,
but to tell the user why and suggest what could work; kept furniture, walls, doors and windows cannot be edited.

The node ends with a `LayoutDiff` (placement ids added, removed and changed). An empty diff ends the run with the answer and the
design unchanged; otherwise `solve` validates the edited layout (it does not re-solve it) and `present` rebuilds the scene.

### Guardrails around the model calls (`backend/app/llm/__init__.py`)

Every model call goes through this gateway (B-02), ported from CoA's tools.

- **Structured output.** `ask_structured(schema, prompt, role=...)` uses `with_structured_output(..., method="function_calling",
  include_raw=True)`. Function calling, not `json_schema`, because `ChatOpenAI` raises `json_schema` validation errors without the
  raw reply, and its usage would be lost. Every schema forbids unknown fields (`app/schemas/base.py`), so a typo in the model's JSON
  is an error, not a dropped field.
- **One repair retry.** An invalid reply is asked for again once, with the parse error; a second invalid reply fails the run.
- **A cut-off reply fails.** A reply with `finish_reason == "length"` raises `TruncatedReply` (in `ask_structured` and in the chat
  loop): a truncated structure or tool call is never used.
- **Per-role model, max tokens and timeout** (`ROLES`). Replies are not streamed (`disable_streaming`), because a streamed
  OpenRouter reply carries no cost; LangGraph's `messages` stream still gets each whole reply.

  | Role | Model | Max tokens | Timeout | Used by |
  |---|---|---|---|---|
  | `analyze_room` | `openai/gpt-6.1-sol` | 16 000 | 180 s | the Room Analyst (vision) |
  | `design` | `openai/gpt-5-mini` | 8 000 | 90 s | the Designer |
  | `architect` | `openai/gpt-6.1-sol` | 16 000 | 180 s | the Architect, and the eval's single-LLM baseline |
  | `refine` | `openai/gpt-5-mini` | 8 000 | 90 s | nothing: the Refiner is deterministic |
  | `critic` | `openai/gpt-6.1-sol` | 16 000 | 180 s | the eval's VLM judge (the graph's Critic is rule-based) |
  | `chat_edit` | `openai/gpt-5-mini` | 8 000 | 90 s | the chat edit |

- **Usage and cost.** `call_usage` reads each reply's tokens and the cost OpenRouter charged (0 when the provider reports none); a
  node adds its calls' usage (retries included) to its update, and `RunState`'s `cost`, `input_tokens` and `output_tokens` are
  summed with `operator.add`, so the checkpoint holds the project's total across its runs. With LangSmith tracing on,
  `app/observability/tracing.py` tags each run's trace with its thread, run id and ablation flags and passes OpenRouter's cost to
  LangSmith as `total_cost`.
- **Tests never call a model** unless marked `live` (`backend/tests/conftest.py` unsets the key and `LLM_RECORDINGS` for every other
  test); `FakeLLM` (`app/llm/fake.py`) stands in, queued replies in, prompts recorded.

### State (`backend/app/graph/state.py`)

`RunState` is kept per thread across its runs; it is also the `values` the API returns.

| Field | Content |
|---|---|
| `photo_keys`, `dimensions`, `brief` | the design run's input (`NewDesign`): up to 3 photo keys, the typed dimensions, the brief |
| `chat_message` | a chat run's input; `route_input` moves it to `messages` and clears it |
| `mode` | `design` or `chat`: the current run's kind |
| `room_spec` | the room: dimensions, wall colors, floor material, features, kept furniture, warnings (analyzed, then confirmed) |
| `design_brief` | the Designer's zones, palette, objects and summary |
| `scene_graph` | the nodes (walls, doors, windows, objects with their chosen `item_id` and size) and the relation edges |
| `candidates` | per object node: the chosen catalog item first, then the alternatives |
| `layout` | one `Placement` per placed object (copies as `<id>_2`...): center, base height, rotation, size, item |
| `validation` | the solve node's issues (graph, layout, unmet relations) |
| `fallback` | what the solver fallback dropped or resized, and why |
| `critique` | the Critic's rules, actions and summary, tagged with its round |
| `best` | internal: the best round of the Critic loop so far; cleared when the run ends |
| `round` | the Critic round, from 1 |
| `scene` | the render-ready scene, with the matched cameras |
| `layout_diff` | what the last chat edit changed |
| `rationale` | the design's rationale, or the chat edit's answer |
| `messages` | the chat history (`operator.add`: append-only, which the frontend's undo detection relies on) |
| `cost`, `input_tokens`, `output_tokens` | the project's model usage across runs, in USD and tokens (`operator.add`) |

The checkpointer's serializer (`serde()` in `graph.py`) loads only LangGraph's safe types and the app's own models.

### The coordinate convention (`backend/app/schemas/coords.py`)

One convention for every model, node and view, and its docstring is pasted into every prompt:

- Meters and degrees. The room is a rectangle seen from above; the origin is the floor corner where walls A and D meet; x runs
  along wall A, y along wall D into the room, z up.
- Walls go counterclockwise: A from (0, 0) to (width, 0), B to (width, length), C to (0, length), D back to (0, 0). A feature's
  `offset` is the fraction of its wall from the wall's start corner to its center.
- An item's (x, y) is the center of its footprint and z its base; `size` is width (side to side), depth (front to back) and height
  in its own frame; `rotation` turns it counterclockwise, and at 0 its front faces +y.
- three.js is y-up: room (x, y, z) is three.js (x, z, -y) (`frontend/src/components/scene3d/core/geometry.ts`).

A node with a quantity over 1 is placed once per unit, the copies named `<id>_2`, `<id>_3`...; the Critic, the chat tools and the
layout diff map a copy back to its node by that suffix.

## The API (`backend/app/api/`)

The routes are named and shaped like the LangGraph Agent Server's threads and runs, and the stream sends the same events, so the frontend could later talk to an Agent Server deployment with few changes. Open-source
LangGraph cannot search threads, so a `projects` table (one row per thread: id, owner, title, times; Alembic migration
`backend/migrations/versions/0001_projects.py`) lists them. The contract is `contracts/openapi.json`, generated from the routes.

| Route | What it does |
|---|---|
| `POST /threads` | Create a project; only `metadata.title` is kept |
| `GET /threads` | Every project, most recently updated first, with its status (`new`, `running`, `needs_input`, `done`, `error`) |
| `GET /threads/{id}/state` | The current state: `values` (`RunState`), `next`, the open interrupt (`interrupts`), `checkpoint_id`, `created_at`, status |
| `GET /threads/{id}/history` | Every checkpoint, newest first |
| `POST /threads/{id}/revert` | Make an earlier checkpoint current (a new checkpoint forked from it); 409 while a run is active |
| `POST /threads/{id}/runs/stream` | Start a run and stream it: `input` (a `NewDesign` or a `ChatMessage`), `command.resume` (the confirmed room), or `input: null` to continue a run a restart cut off; `config.configurable` carries the ablation flags |
| `GET /threads/{id}/runs/current/stream` | Rejoin the thread's latest run from its first part (at once if it is over); 404 before any run |
| `GET /threads/{id}/runs/{run_id}/result` | A finished run's `RunOutput`, from its last checkpoint; 409 while it has not finished |
| `POST /threads/{id}/camera-pose` | Solve a photo's camera from at least 4 clicked corners and save it in the scene |
| `POST /uploads` | Store a room photo, return its key |
| `GET /uploads/{key}` | A photo by its key |
| `GET /catalog/items/{item_id}` | A catalog item (stub: only the items of the fixture scenes) |
| `GET /health` | `{"status": "ok"}` |

**The stream.** Each Server-Sent Event's name is the part's kind and its data is JSON (`StreamPart` in `app/api/models.py`):

| Event | Data |
|---|---|
| `metadata` | the first part: `run_id` |
| `updates` | what a node changed, by node name; `__interrupt__` holds the interrupt the run paused at |
| `custom` | a node's `step` or `tool` event (the run timeline, the chat's chips) |
| `messages` | a model reply with the node that called the model (whole replies: streaming is off for cost reporting) |
| `error` | the run failed; the stream ends |

**The run manager (`backend/app/runs/__init__.py`).** In process, one active run per thread. A run is a background task that
writes its parts into an in-memory buffer; any number of clients follow it from the first part, so a reload rejoins the run
(`/runs/current/stream`) instead of starting another. A second run on a busy thread is refused with 409, as is a resume without an
open interrupt or a continue without a cut-off run. The latest run of the last 100 finished threads is kept for rejoining. The
checkpointer saves the state after every node, so a run cut off by a restart is lost from the buffer but not from Postgres: its
thread's status is `error`, and streaming with `input: null` continues it from the last checkpoint. Revert (the chat's Undo) forks
a new checkpoint from an earlier one. The API's `run_id` is passed to LangGraph as the run's id (`traced()` in
`app/observability/tracing.py`), so each checkpoint keeps it in its metadata, as in the Agent Server: that is how `/result` finds a
run's last checkpoint, and with LangSmith on it is also the trace's root run id.

**Uploads (`backend/app/api/uploads.py`, `backend/app/storage/`).** `POST /uploads` takes one image (415 otherwise; SVG is refused as
active content), up to 20 MB (413), stores it at `uploads/<uuid><ext>` (never the client's path) and converts HEIC to JPEG with its
EXIF kept (the camera's focal length). With `STORAGE_ENDPOINT_URL` set, it goes to the S3-compatible bucket (MinIO in docker compose,
Cloudflare R2 or any S3); otherwise to `UPLOAD_DIR` (default `backend/.uploads/`). The bucket stays private: `GET /uploads/{key}`
answers with a 307 redirect to a signed URL valid for an hour, or with the local file. `fixtures/...` keys are served from the
repository, for the stub runs' photos. Graph state holds only keys; the Room Analyst reads the bytes itself and sends them to the
model as data URLs.

**Camera matching (`backend/app/api/camera.py`, `backend/app/vision/camera.py`).** The body is the photo's key and size, the
optional EXIF 35 mm focal length, and at least 4 distinct corners (a floor corner A to D, or the ceiling above it) with their pixel
positions. OpenCV's `solvePnP` (SQPnP, refined with Levenberg-Marquardt) solves the pose against the room's known corners; without
a focal length it searches 0.3 to 1.5 times the image's longer side for the lowest reprojection error. A pose more than 2% of the
image diagonal off is refused (400: probably a corner clicked in the wrong place). The pose is converted to three.js and saved in
the scene's `cameras` (a new match for the same photo replaces the old one); 409 before the thread has a scene or while a run is
active.

Every request gets an `X-Request-ID` and the API logs one JSON line per request (`app/observability/`).

## The frontend (`frontend/`)

Next.js 16 (App Router, React 19 with the React Compiler), Tailwind 4 and shadcn/ui on Base UI. The browser calls the API directly
(`NEXT_PUBLIC_API_URL`, default `http://localhost:8000`).

| Route | What it shows |
|---|---|
| `/` | Placeholder: "No projects yet" and **New project** (the project list is not wired yet, see Known limitations) |
| `/projects/new` | The wizard |
| `/projects/{id}` | The workspace: Room (timeline, photos, plan), Design, 3D and Photo tabs, and the chat panel |
| `/projects/{id}/room` | The room editor that answers `confirm_room` |
| `/projects/{id}/photo` | Camera matching, then the composite |
| `/projects/{id}/design` | The Design tab's view on its own page |
| `/render/{runId}` | A bare 3D render from corner A or C (`?view=cornerC`), with no app chrome, for headless capture |

**Data layer (`src/lib/`).** `lib/api` is the one way to call the API: types generated from `contracts/openapi.json`
(`openapi-typescript`, `make gen`), a 15 s timeout (none for a run's stream), one retry after a 401 (for the sign-in to come; there is
no token yet), typed errors (`ApiError`: auth, network or server), and `streamParts`, which reads the Server-Sent Events with
`eventsource-parser`. `useRunStream` follows a thread's run: it rejoins the latest run on mount, folds the parts into the run's
events, model replies, updates and interrupt, and has a retry that rejoins or starts again depending on what failed. `useThread`
and `useHistory` fetch the state and history again whenever a run on the thread ends. The run timeline rebuilds earlier runs' steps
from the history.

**Mock mode.** The tests run the hooks and views against `lib/mocks/stub-api.ts`, a `fetch` that replays what the stub API answered
for one project (`lib/mocks/stub/`: the thread, its states and histories, the SSE of the design run, the resumed run and two chat
turns), recorded with `lib/mocks/record.sh` against `make dev-stub`. Streams arrive in small chunks and can be held mid-run, so a
test can leave a run and rejoin it. Re-record when the API or the fixtures change.

**The workspace store (`components/workspace/sync/`).** One `WorkspaceProvider` per project holds the thread's state, its run (one
stream for the timeline and the chat), the chat's draft and the latest chat edit. When a new state arrives whose `messages` grew and
whose `layout_diff` is not empty, that was a chat edit: its added and changed items are highlighted for 4 s in every view and
**Undo** reverts to the checkpoint seen before it. An item clicked in the floor plan or the 3D view is added to the draft as `@<id>`.

**3D (`components/scene3d/`).** react-three-fiber with drei. `core/` is the viewer: walls extruded with holes for doors and
windows, floor, ceiling, and each item as its GLB (scaled to the catalog size and turned so its front faces forward) or a box; views
are orbit, eye level (1.6 m, turning in place), each matched photo's camera (letterboxed to the photo's aspect) and the two fixed
corners of the render route. `look/` is the lit look: three's procedural `RoomEnvironment` as the environment map, a
`RectAreaLight` per window, a low sun with shadows through at most two main windows, and a floor pattern (planks, tiles or carpet)
read from the free-text floor material. The canvas renders on demand (`frameloop="demand"`), so an idle view costs no GPU time. The
pure math (`geometry.ts`, `look.ts`) is kept apart from react-three-fiber and tested without WebGL.

**Camera match and composite (`scene3d/camera-match/`, `scene3d/composite/`).** The match view sends the clicked corners to the
camera-pose route and draws the room's wireframe from the returned pose for the user to confirm. The composite draws the new
furniture on a transparent canvas over the photo, from the matched camera: the floor only catches their shadows, and the kept
furniture (already in the photo) is drawn first into the depth buffer alone, so whatever stands behind it is hidden. A slider
wipes between the photo and the composite. **Export PNG** renders once more at the photo's resolution and draws photo and canvas
into one PNG; the photo is loaded with `crossOrigin="anonymous"` for that. A photo whose aspect ratio differs from the one the camera
was matched to is refused (the furniture would not line up), and the user can open the original from their device instead.

**Headless render (`app/render/[runId]/`).** The eval's capture script (`eval/scripts/capture.ts`, Playwright Chromium with software
WebGL) opens `/render/<thread id>?view=cornerA` and `cornerC` to take the two corner renders the VLM judge grades.

## Repository layout

```
Makefile                 install, dev, dev-stub, test, lint, gen, eval, ablate, e2e, e2e-record
docker-compose.yml       the stack: Postgres with pgvector (db), MinIO and its bucket (minio, minio-init), the API, the frontend
.env.example             the root .env's template (the .env itself is gitignored)
backend/                 FastAPI + LangGraph (uv; Python 3.12+, developed on 3.14); its Dockerfile is the API's image
  app/main.py            the app: lifespan (store, checkpointer, projects registry, graph), routers, CORS, /health
  app/api/               routes: threads, runs (SSE), uploads, camera pose, catalog; models.py is the API contract; export.py writes openapi.json
  app/runs/              the in-process run manager (one active run per thread, rejoinable buffers)
  app/graph/             graph.py, routing.py (incl. keep_best), state.py, stub.py, chat_tools.py, nodes/ (one module per node)
  app/prompts/           the prompts: analyst/, designer/, architect/ (draft, revise, rules), chat_edit/
  app/llm/               the model gateway (get_llm, ask_structured, ROLES), recorded.py (record/replay), fake.py (FakeLLM)
  app/geometry/          room.py (Shapely room model), checks.py (layout checks), graph_validate.py (B-07), solver.py, fallback.py
  app/catalog/           loader.py (data/catalog), embed.py (the store and its seed), search.py (hard filters)
  app/scene/builder.py   the render-ready scene, the total, the rationale
  app/vision/camera.py   camera pose from clicked corners (OpenCV)
  app/storage/           S3-compatible storage, local uploads, HEIC to JPEG
  app/db/                the projects registry; migrations/ holds its Alembic migration
  app/schemas/           the domain models (Pydantic v2): coords, room, design, layout, scene, run; export.py writes contracts/schemas/
  app/observability/     JSON logs with request ids, LangSmith run tagging and cost
  tests/                 pytest, offline (fixtures, FakeLLM, fake embeddings); `-m live` for real models
frontend/                Next.js 16 (pnpm); its Dockerfile builds the production image
  src/app/               routes: (routes)/ (projects, wizard, workspace, room editor, photo view), render/[runId]
  src/components/        wizard/, run/ (timeline), plan/ (floor plan, room editor), results/, scene3d/ (core, look, camera-match, composite), chat/, workspace/sync/ (the store), ui/
  src/lib/               api/ (client, generated types), hooks/ (useRunStream, useThread...), mocks/ (stub API replay)
contracts/               JSON Schema and OpenAPI generated from the backend (`make gen`); CI fails when they are stale
fixtures/                three room cases (small-bedroom, home-office, living-room), each one consistent example of every model;
                         negative/: schema-valid data that must be rejected or handled downstream
data/catalog/            the furniture catalog: 223 items in 15 categories
eval/                    dataset (data/), metrics/, baselines/single_llm.py, judge/vlm.py, runner.py, ablation.py, agreement.py, results/pilot/
e2e/                     the Playwright suite (tests/), its compose override (compose.yml) and the recorded model calls (recordings/)
docs/                    slides, the demo video and its recording script (demo/record.ts), screenshots (img/)
.github/workflows/       backend.yml, frontend.yml, e2e.yml
```

## Running it

You need [uv](https://docs.astral.sh/uv/), Node 24 with [pnpm](https://pnpm.io/) (`corepack enable`), Docker, and `make` (each
target is a few lines of the [Makefile](Makefile) if you would rather type them). Settings live in **one `.env` at the repository
root**, copied from `.env.example` and gitignored, never in `backend/` or `frontend/`: `make dev`, `make dev-stub`, `make eval`,
`make ablate` and docker compose read it.

### Without a key: `make dev-stub` (free, offline)

```sh
git clone https://github.com/Nelev/rooms-app.git && cd rooms-app
make dev-stub        # the API on :8000, the frontend on :3000, with reload
```

Open <http://localhost:3000> and click **New project**. The API runs with `DATABASE_URL` and `OPENROUTER_API_KEY` emptied and
`STUB_PACE=0.3`: the checkpointer, the store and the projects live in memory (and are lost whenever the API restarts, a reload on a
code change included), every model-backed node replays the small bedroom, and nothing is spent. If ports 8000 or 3000 are taken,
run the two by hand with another port, pointing the frontend at the API and letting the API accept the frontend's origin:

```sh
(cd backend && DATABASE_URL= OPENROUTER_API_KEY= STUB_PACE=0.3 CORS_ORIGINS=http://localhost:3001 uv run uvicorn app.main:app --port 8001) &
(cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8001 pnpm dev --port 3001)
```

### With models: `make dev` (costs money)

```sh
cp .env.example .env   # set OPENROUTER_API_KEY in it
make dev               # Postgres in Docker, then the API on :8000 and the frontend on :3000, with reload
```

`DATABASE_URL` in `.env.example` points at the compose database on `localhost:5432`. At startup the API migrates the projects
table, sets up the checkpointer's tables and seeds the catalog store (one embeddings request for 223 items). Without
`OPENROUTER_API_KEY`, `make dev` still works on Postgres with stub nodes, and the catalog store stays in memory and empty (with a
warning). Without `STORAGE_*`, photos go to `backend/.uploads/`.

> **Live runs cost money.** With a key, every design run calls real models through OpenRouter. The pilot measured $0.042 per run for
> the full graph, $0.033 without the Critic and $0.025 for the single-LLM baseline. `make eval` and `make ablate` also read the root
> `.env`, so with a key they run live over many cases. To stay offline, leave the key unset or pass `--fake`
> (`make ablate ARGS="--fake"`, or `python -m eval run --fake` directly, see Evaluation).

### Everything in containers: docker compose

```sh
cp .env.example .env
docker compose up -d --build --wait   # Postgres, MinIO and its bucket, the API, the frontend; open http://localhost:3000
```

Compose sets `DATABASE_URL` and `STORAGE_*` for its own `db` and `minio` services (bucket `rooms`, made by the one-shot `minio-init`)
and reads everything else from the root `.env`: **with an `OPENROUTER_API_KEY` there, design runs call real models and spend
money**; without one, the nodes replay the fixtures. The API container mounts `fixtures/` and `data/catalog/` read-only. Postgres and
MinIO are published on `127.0.0.1` only (their passwords are development defaults). `docker compose up -d db` alone starts just the
database, which is what `make dev` does.

| Port | Service | Variable |
|---|---|---|
| 3000 | frontend | `FRONTEND_PORT` |
| 8000 | API (`/health`) | `BACKEND_PORT` (the frontend image is built for it: rebuild after changing it) |
| 5432 | Postgres (`127.0.0.1`) | `DB_PORT` |
| 9000 | MinIO S3 API (`127.0.0.1`; the browser reads photos from signed URLs on it) | `MINIO_PORT` |

### Settings

| Variable | Where | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | backend | models and embeddings; without it every model-backed node replays the fixtures |
| `DATABASE_URL` | backend | Postgres with pgvector: checkpointer, store, projects; without it all three are in memory |
| `STORAGE_ENDPOINT_URL`, `STORAGE_BUCKET`, `STORAGE_ACCESS_KEY_ID`, `STORAGE_SECRET_ACCESS_KEY` | backend | the S3-compatible bucket for photos; without them, `UPLOAD_DIR` |
| `STORAGE_PUBLIC_URL` | backend | the endpoint as the browser reaches it, for signed URLs, when the API reaches it at another address (compose sets it) |
| `UPLOAD_DIR` | backend | where photos go without object storage, default `backend/.uploads/` |
| `CORS_ORIGINS` | backend | allowed browser origins, comma-separated, default `http://localhost:3000` |
| `EMBEDDING_MODEL` | backend | default `openai/text-embedding-3-small`; another model must also return 1536 dimensions |
| `STUB_PACE` | backend | seconds slept per second of a replayed fixture step, default 0 (`make dev-stub`: 0.3) |
| `LLM_RECORDINGS`, `LLM_RECORD_MAX_COST`, `LLM_REPLAY_DELAY` | backend | recorded model I/O (see above): the folder, the recording cap (default 0.4 USD), the delay per replayed reply (default 0) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | backend | optional tracing to LangSmith; the eval runner turns it off |
| `NEXT_PUBLIC_API_URL` | frontend | the API's address, default `http://localhost:8000`; written into the bundle at build time |
| `DB_PORT`, `MINIO_PORT`, `BACKEND_PORT`, `FRONTEND_PORT` | compose, `make e2e` | host ports, default 5432, 9000, 8000, 3000 |
| `TEST_DATABASE_URL`, `TEST_STORAGE_ENDPOINT_URL` | tests | Postgres and MinIO for the tests that need them; skipped when unset (CI sets both) |

## Testing and CI

```sh
make test   # backend pytest (offline: fixtures, FakeLLM, fake embeddings) and frontend vitest
make lint   # ruff format --check, ruff check, mypy --strict; Biome and tsc
make gen    # regenerate contracts/ and the frontend's API types after changing a schema or a route
make e2e    # the Playwright suite on the compose stack, replaying e2e/recordings/: no key, no cost
```

- **Live tests** call real models and cost money: `cd backend && uv run pytest -m live` with `OPENROUTER_API_KEY` in the
  environment. Every other test unsets the key, so `make test` never spends, whatever the shell holds.
- **E2E** (`e2e/tests/design.spec.ts`): `make e2e` builds the compose stack under the project name `rooms-e2e` with `e2e/compose.yml`
  on top (`LLM_RECORDINGS=/recordings`, the key overridden to empty, `LLM_REPLAY_DELAY=1`), so the real graph answers from the
  recorded calls. One test creates a project, confirms the room, reads the design, makes and undoes a chat edit, opens the 3D view,
  matches the photo's camera and checks the composite's photo loads through the signed-URL redirect with CORS; the other reloads
  the page mid-run, twice, and checks the run is rejoined and finishes. The stack's logs go to `e2e/test-results/stack.log` and the
  stack is removed afterwards. A change to a prompt, a tool, a role's model or the catalog invalidates the recordings:
  `make e2e-record` (with `OPENROUTER_API_KEY` exported in the shell, not only in `.env`) records the missing calls, which **costs
  money** (capped by `LLM_RECORD_MAX_COST`); commit the new recordings. Only that target passes the key to the stack.
- **The demo and screenshots** are re-recorded against a running `make dev-stub` (needs `pnpm --dir frontend exec playwright install
  chromium`): `BASE_URL=http://localhost:3000 pnpm --dir frontend exec node ../docs/demo/record.ts`.

GitHub Actions (`.github/workflows/`) run on pull requests (any base branch, since PRs are stacked) and on pushes to `main`, each
only when its paths change:

| Workflow | Runs when | Steps |
|---|---|---|
| `backend.yml` | `backend/`, `contracts/`, `fixtures/`, `eval/`, `data/` change | Python 3.12 and 3.14, with a pgvector Postgres service and MinIO: ruff format, ruff, mypy, the same for `eval/`, pytest, and an offline eval smoke (`baseline` and `full`, 3 cases) |
| `frontend.yml` | `frontend/`, `contracts/openapi.json`, `fixtures/` change | Node 24: the generated API types are current, Biome format and lint, `next build` (type-checks), vitest |
| `e2e.yml` | `e2e/`, `backend/`, `frontend/`, `fixtures/`, `data/`, `docker-compose.yml`, `Makefile` change | `make e2e`; the Playwright report and the stack's log are uploaded on failure |

## Evaluation

The eval compares the agent graph with a single-LLM baseline and with ablations of itself, on deterministic layout metrics and a
VLM judge. It lives in `eval/` and shares the backend's environment, so every command runs from `backend/`.

| Piece | Where | What it does |
|---|---|---|
| Dataset (E-01) | `eval/data/<case>/case.json`, `eval/dataset.py` | 25 cases: 20 briefs, 5 per I-Design brief category (functionality, layout, color scheme, atmosphere), on the three fixture rooms, plus 5 hard cases (`hard-tiny-room` 1.8 x 2.1 m, `hard-three-doors`, `hard-wrong-dimensions`, `hard-impossible-brief`, `hard-budget-too-low` at EUR 150). Each case is a run input plus a hand-labeled `RoomSpec` ([eval/data/README.md](eval/data/README.md)) |
| Metrics (E-02) | `eval/metrics/layout.py`, `analyst.py` | Layout: out of bounds, overlap volume, clearance pass rate (share of items a person can reach), blocked openings, cost, budget fit, must-have coverage, item count; I-Design's out-of-bounds rate and bbox loss over a set. Room Analyst: feature precision and recall against the labels, position error |
| Single-LLM baseline (E-03) | `eval/baselines/single_llm.py` | LayoutGPT-style: one call (the `architect` role) places the furniture directly as absolute positions, from the room, the brief and a catalog subset. It returns the same `Layout`, so every metric applies |
| VLM judge (E-04) | `eval/judge/vlm.py` | I-Design's protocol: a vision model (the `critic` role) sees the two corner renders and the brief, comments first, then grades functionality, layout, color scheme, atmosphere and realism from 0 to 10, asked 3 times (mean and standard deviation). A pairwise mode asks which of two designs fits the brief better, 4 times, each shown first equally often |
| Runner (E-05) | `eval/runner.py` | Runs every case `--repeats` times on a variant, in process (in-memory checkpointer and store), resumes `confirm_room` with the case's labeled room so every variant is scored on the same room, and writes `runs.csv`, `report.md` and each run's final state. Tracing and object storage are turned off on import |
| Ablations (E-06) | `eval/ablation.py` | Several variants on the same cases into one report with one SVG chart per metric; `--judge` captures the renders and grades them; `--max-cost` stops starting runs once the spend passes it; `--rebuild` remakes a report from earlier `runs.csv` files without a model call |
| Judge-human agreement | `eval/agreement.py` | Pearson, Spearman and Cohen's kappa (grades binned 0-3, 4-6, 7-10) between the judge and people's grades in `eval/data/human_ratings.csv` |
| Catalog search | `eval/catalog_search.py` | precision@5 of the Sourcer's search on 20 hand-labeled queries (needs a key) |

Variants: `baseline`, `full` (the agent graph), `no_critic` (`solve` goes straight to `present`) and `analyst_mode` (the Room
Analyst reads the photos once instead of voting over three readings). The `single_agent` flag exists in `RunConfigurable`, but no
node reads it, so the ablation leaves it out.

```sh
cd backend
# offline: fixture replay and fake models, $0; the numbers only check that the pipeline runs
PYTHONPATH=..:../eval uv run python -m eval run --variant full --limit 3 --repeats 1 --fake
PYTHONPATH=..:../eval uv run python -m eval ablate --fake --cases bedroom-calm --repeats 1
# rebuild the pilot's report and charts from its runs.csv, no model call
PYTHONPATH=..:../eval uv run python -m eval ablate --rebuild ../eval/results/pilot/runs.csv --out ../eval/results/pilot
# live (OPENROUTER_API_KEY set, costs money): one variant, or the full study with the judge and a cost cap
PYTHONPATH=..:../eval uv run python -m eval run --variant full --repeats 3
PYTHONPATH=..:../eval uv run python -m eval ablate --judge --max-cost 20
# judge-human agreement, once people have filled in eval/data/human_ratings.csv
PYTHONPATH=.:..:../eval uv run python ../eval/agreement.py report ../eval/results/pilot/runs.csv
```

`make eval VARIANT=full` and `make ablate ARGS="..."` wrap the first and second forms and pass the root `.env`: with a key there, they
run live (`make eval` defaults to `baseline`, 3 repeats, every case). `--judge` also needs Playwright's Chromium
(`pnpm --dir frontend exec playwright install chromium`). Results go to `eval/results/<variant>-<time>/` or
`eval/results/ablation-<time>/`, gitignored except the pilot.

### Pilot results (E-06, 2026-11-05)

[`eval/results/pilot/`](eval/results/pilot/) holds a small paid run that checked the pipeline end to end with live models: 4
variants, 3 rooms (`bedroom-calm`, `office-focused`, `living-airy`, one per fixture room), 1 repeat, 12 runs, none failed. It cost
**about $0.58** (OpenRouter usage: $0.38 for the runs, $0.20 for the judge). [report.md](eval/results/pilot/report.md) has every
metric; [its README](eval/results/pilot/README.md) the details.

| Variant | Runs | Cost / run | Time / run | Clearance pass | Out of bounds | Blocked openings | Budget fit | Must-haves | Judge: functionality, layout, color, atmosphere, realism (0-10) |
|---|---|---|---|---|---|---|---|---|---|
| `baseline` (single LLM) | 3 | $0.025 | 17 s | 0.97 | 0 | 0 | 1 | 1 | 3.9, 4.1, 5.7, 3.7, 1.9 |
| `no_critic` | 3 | $0.033 | 56 s | 0.92 | 0 | 0 | 1 | 1 | 3.7, 4.4, 5.3, 3.3, 2.0 |
| `full` | 3 | $0.042 | 57 s | 0.92 | 0 | 0 | 1 | 1 | 4.0, 4.7, 5.9, 3.6, 2.0 |
| `analyst_mode` | 3 | $0.027 | 47 s | 1.00 | 0 | 0 | 1 | 1 | 3.7, 4.4, 5.8, 3.4, 2.0 |

<p>
  <img src="eval/results/pilot/charts/cost_usd.svg" alt="Model cost per run: baseline $0.025, no_critic $0.033, full $0.042, analyst_mode $0.027" width="420">
  <img src="eval/results/pilot/charts/latency_s.svg" alt="Wall time per run: baseline 17 s, no_critic 56 s, full 57 s, analyst_mode 47 s" width="420">
</p>

Read these numbers with care:

- **3 rooms, 1 repeat.** The gaps between variants are anecdotes, not results. The judge cannot tell the variants apart: every gap
  is within one grade point.
- **Placeholder photos.** The Room Analyst found no features in any room: feature recall is 0, and precision is 1 only because
  nothing was predicted. `analyst_mode` measures nothing real about the analyst yet. The designs are scored on the hand-labeled room.
- **Box renders.** None of the 62 placed items (22 distinct catalog items) had a 3D model, so the judge graded grey block-outs and said so in every comment;
  realism (about 2/10) and atmosphere reflect the renders more than the designs.
- **Two sittings.** `baseline` and `no_critic` ran first; `full` then crashed seeding its catalog store (`Event loop is closed`: a
  cached embeddings client reused across event loops). After the fix, `full` and `analyst_mode` ran on the same rooms. `no_critic`'s
  cost includes about $0.012 the `source` node's stub wrapper added in live runs, fixed before the second sitting.
- **Human ratings are pending.** `eval/data/human_ratings.csv` has a blank row per judged run; judge-human agreement is not measured.

What the 12 runs do show: every design stayed in budget, covered every must-have and had nothing out of the room or blocking an
opening. The full graph costs about 70% more than the single call and takes about three times longer. A full study (4 variants x
25 cases x 3 repeats, all judged) would cost about $12 to $20.

### Related work

- **I-Design**: Ata Çelen, Guo Han, Konrad Schindler, Luc Van Gool, Iro Armeni, Anton Obukhov, Xi Wang.
  [*I-Design: Personalized LLM Interior Designer*](https://arxiv.org/abs/2404.02838), ECCV 2024 Workshops
  ([project page](https://atcelen.github.io/I-Design)). LLM agents turn a text description into a scene graph of objects and
  relations, a backtracking algorithm places the objects, assets are retrieved from a database, and a VLM evaluator grades the
  result. rooms-app follows the same scene graph and backtracking design and reuses its metrics and judge protocol. It adds real
  photos and a confirmed room (walls, doors, windows, kept furniture), a priced catalog and a budget, a closed Critic loop that keeps
  the best round, and chat edits.
- **LayoutGPT**: Weixi Feng, Wanrong Zhu, Tsu-jui Fu, Varun Jampani, Arjun Akula, Xuehai He, Sugato Basu, Xin Eric Wang, William
  Yang Wang. [*LayoutGPT: Compositional Visual Planning and Generation with Large Language Models*](https://arxiv.org/abs/2305.15393),
  NeurIPS 2023. An LLM predicts layouts directly (CSS-like boxes from in-context examples), 3D indoor scenes included. The E-03
  baseline is in this style: one call places the furniture as absolute positions.

## Known limitations

- **The photos are placeholders.** Every fixture and eval photo is synthetic, and in the live pilot the Room Analyst found no
  features at all. The analyst, and everything downstream of a room read from real photos, has not been measured.
- **No detection, no depth cross-check.** The analyst reads the photos with the vision model alone: the detection overlays its prompt
  can take are never produced (B-06), and the typed dimensions are trusted without checking them against the photos (B-22; the
  `wrong_dimensions` fixture and the `hard-wrong-dimensions` case exist for it). The analyst also ignores furniture, so the pieces
  to keep must be added by hand in the room editor; the brief's `keep` and `remove` lists are only text for the Designer.
- **No sign-in (A-01).** Every project is visible to and editable by everyone who can reach the API: `GET /threads` lists every
  project (the registry has an `owner` column, always empty), and every route takes any thread id. Run it locally.
- **The home page does not list projects.** `/` is a placeholder; `GET /threads` and the `useProjects` hook exist but nothing shows
  them, so a project is reached by its URL.
- **Mostly boxes.** Only 4 of the 223 catalog items have a GLB model (two sofas and two lounge chairs); everything else renders as a
  grey box, which is why the judge's realism grade is about 2/10.
- **The solver enforces only each node's first placing edge.** Other relations, `facing` and the Refiner's ordering edges are
  checked afterwards, not used to place: a second relation that the first one breaks costs a Critic round, and ordering edges change
  nothing yet.
- **The step limit bounds the search.** `STEPS = 5000` makes the result reproducible on any machine, but a crowded room that a
  longer search would solve is reported as not fitting, and the fallback then drops or shrinks items.
- **The budget share and the "other shape" fallback are heuristics** (marked provisional in `source.py`), and a catalog category has
  few items of each size, so objects can stay without an item (an unpriced box).
- **Single process.** The run manager's buffers live in memory: one uvicorn worker only, a restart drops the active streams (the
  runs continue from their checkpoints when streamed with `input: null`), and only the last 100 finished threads can be rejoined.
- **Recordings go stale.** Any change to a prompt, a tool's signature, a role's model or the catalog changes the hashes of the
  recorded calls; `make e2e` then fails with `MissingRecording` until `make e2e-record` is run, with a key, at a cost.
- **The fixture camera is behind the kept wardrobe.** `fixtures/small-bedroom`'s photo camera stands 10 cm beside the 2 m wardrobe,
  so in the composite the wardrobe hides every new item (`occlusion.test.ts` pins it); the demo deletes the wardrobe in the editor.
  In the stub graph the analyzed room is always this one.
- **The composite only adds.** Furniture already in the photo that the design replaces or the brief removes stays visible; only kept
  furniture is modeled, as an occluder.
- **`<img>` tags cannot send an `Authorization` header.** Photos are read through `GET /uploads/{key}` from plain `<img>` tags; once
  there is sign-in, that route needs another way to know the person (a cookie or a token in the query), as `photoUrl` in
  `frontend/src/lib/api/index.ts` notes.
- **The bucket needs CORS.** The composite loads the photo with `crossOrigin="anonymous"` to export it, so the bucket behind the
  signed URLs must allow the frontend's origin. The E2E suite checks it on compose's MinIO; another bucket (R2, S3) needs a CORS rule.
- **Human ratings are pending**, so the VLM judge's agreement with people is not measured, and the pilot is 12 runs.
- **Unused pieces.** The `refine` role in `ROLES` is never called (the Refiner has no model), the `single_agent` flag is read by no
  node, `GET /threads/{id}/runs/{run_id}/result` is not used by the frontend (it reads the thread state and sums the total itself),
  and `GET /catalog/items/{id}` only knows the items of the fixture scenes.
- **The registry and the checkpoints are not cleaned up.** `app/db/projects.delete` exists but no route calls it; projects, their
  checkpoints and their photos are kept until removed by hand.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, PR and parallel-agent rules, and [fixtures/README.md](fixtures/README.md) for
the sample data.
