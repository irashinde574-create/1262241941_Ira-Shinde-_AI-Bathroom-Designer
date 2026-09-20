# Kohler AI Bathroom Designer & Planner

An AI-assisted bathroom design system that takes a customer's room dimensions,
budget, and aesthetic preference, and produces a personalized, physically
valid product bundle (toilet, washbasin, faucet, showerhead, mirror) — with
the reasoning behind every choice.

Track 1 submission — KOHLER-MITWPU AI Research Lab Program.

## How it works

The system is split into two deliberately separate stages, so each part does
what it's actually good at:

**Stage A — Hard Constraint Engine (this repo, currently)**
Pure deterministic code. No AI calls. Given a room size and budget, it:
1. Checks whether the room can physically fit a toilet, vanity, and shower
   zone side by side (a single-wall linear layout — see assumptions below)
2. Filters every product in the catalog by whether its real footprint and
   required clearance fit the space
3. Runs an exhaustive search (small enough search space to be exact, not
   approximate) to find the combination of products that maximizes quality
   within budget
4. Outputs a validated shortlist per category — never a single guess —
   along with a clear reason for every excluded product

**Stage B — LLM Reasoning Layer (`src/stage_b.py`)**
Takes the top 5 budget-valid, spatially-valid *complete bundles* that
Stage A produces (not individual products) and asks an LLM to choose the
single most aesthetically coherent one, explaining why in plain language.
The LLM never assembles a bundle itself and never sees price or dimension
numbers — it only ever picks between whole options Stage A has already
fully validated. This makes it structurally impossible for the LLM to
produce an over-budget or spatially invalid recommendation, no matter how
it reasons.

**Stage C — 2D Floorplan Renderer (`src/stage_c.py`)**
Takes the room dimensions, Stage A's zone layout, and Stage B's final
bundle, and draws a labeled, to-scale top-down floorplan as an SVG file
— no external image libraries needed. Each fixture is drawn to its real
footprint size within its allotted (clearance-inclusive) zone, and any
genuinely leftover floor space is labeled rather than left blank, so the
diagram never looks like a rendering error.

**Interface — Web UI (`src/app.py`, `src/templates/`, `src/static/`)**
A Flask-based browser interface for the full pipeline. A single page
collects room dimensions, budget, and style, then displays the rendered
floorplan, the selected bundle with pricing, and the AI's design
rationale — all generated from one "Generate design" click. Every edge
case Stage A/B can return (room too small, no products fit, over budget,
AI reasoning unavailable) is shown as a clear on-page notice rather than
a raw error.

**Stage D — Conversational Refinement (`src/stage_d.py`)**
Lets the customer adjust one item in an already-generated bundle with a
plain-language request ("show me a cheaper vanity", "a different mirror")
without regenerating the whole design. Intent parsing is deliberate
rule-based keyword matching (not another LLM call) — this keeps
refinement instant, free, and immune to API failures, since the request
vocabulary here (a category name + cheaper/pricier/different) is small
and well-defined. The actual replacement decision is 100% deterministic
code: it only ever picks from products already confirmed to fit the room
and keep the total bundle within budget — same principle as Stage A.

**3D visualization (`stage_c.get_3d_scene_data`, rendered client-side with Three.js)**
The web UI includes a toggleable 3D view alongside the 2D floorplan.
Floor footprints (toilet, vanity, shower zone) are exactly to scale,
matching Stage A's real constraint math — this is not a separate,
looser visualization, it's the same validated geometry viewed in 3D.
Fixture heights and small accessories (faucet, mirror, showerhead) use
documented standard placement assumptions (e.g. a 32in vanity counter
height, an assumed 8ft ceiling), since exact mounting heights aren't in
the product catalog — this is a stylized visualization, not a
CAD-precision model. Three.js is vendored locally in
`static/vendor/` rather than loaded from an external CDN, so the tool
works even on a restrictive network and doesn't depend on a third-party
CDN being reachable during a demo.

**Available options panel**
Alongside the selected bundle, the UI shows every spatially- and
budget-valid alternative for each category (not just the one chosen),
so the customer can see the full pool Stage A considered — with the
selected item highlighted.

**3D fixture rendering: a three-tier fallback system**
The 3D view can display fixtures at three quality levels, chosen
automatically per category with zero risk of failure:

1. **Real AI-generated mesh** (`static/product_meshes/{category}.glb`,
   optional) — a genuine 3D reconstruction generated from a real product
   photo using TripoSR (single-image-to-3D reconstruction). If present,
   this is what renders.
2. **Procedural shape** (always available, the guaranteed fallback) —
   a recognizable silhouette (rounded toilet bowl, basin bowl, gooseneck
   faucet, etc.) built from a handful of Three.js primitives per
   `shape_family`, scaled to the product's real catalog dimensions. Free,
   instant, and has zero external dependencies or failure modes.
3. If a `.glb` file is present but fails to load (missing texture,
   malformed export, etc.), the procedural shape already in the scene is
   left untouched — there is no failure mode where a fixture disappears.

This tiering means the 3D view is **always guaranteed to work** even if
no AI meshes are ever generated, while still being able to show a real
AI-reconstructed shape wherever one exists. To add a real mesh for a
category, generate a `.glb` (see below) and drop it in
`static/product_meshes/{category}.glb` — no code changes needed.

### Generating real AI meshes (optional, TripoSR)

This is an optional visual upgrade on top of the guaranteed procedural
shapes above — not required for the app to work.

1. Set up TripoSR locally (requires Python 3.10/3.11, a 64-bit C++
   compiler such as MSVC via Visual Studio Build Tools, and ~2GB of
   model weights downloaded on first run):
   ```
   git clone https://github.com/VAST-AI-Research/TripoSR.git
   ```
2. Install `torch`/`torchvision` (CPU build), then `torchmcubes` from
   its GitHub source with `--no-build-isolation` (it has no prebuilt
   PyPI wheel and must compile native code):
   ```
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   pip install scikit-build-core pybind11
   pip install git+https://github.com/tatsy/torchmcubes.git --no-build-isolation
   ```
   This compile step needs a genuine 64-bit toolchain — use the "x64
   Native Tools Command Prompt for VS" on Windows, not a generic
   terminal, or it silently builds a 32-bit binary that fails to link.
3. Install TripoSR's own `requirements.txt` (comment out its
   `torchmcubes` line first, since it's already installed above and
   re-installing it re-triggers the same build).
4. Run inference on one representative product photo per category:
   ```
   python run.py photos/washbasin.jpg --output-dir output/ --model-save-format glb
   ```
5. Copy each resulting `.glb` into
   `kohler-bathroom-ai/src/static/product_meshes/{category}.glb`, using
   the exact category names: `washbasin`, `toilet`, `bathroom_faucet`,
   `shower_fixture`, `mirror`.

Single-photo 3D reconstruction has a real quality ceiling — it produces
a plausible approximate shape, not a CAD-precision model. Judge each
result honestly; the procedural shape is a perfectly good fallback for
any category where the AI mesh doesn't look right.

A single end-to-end LLM call can't reliably do precise arithmetic (budget
totals) or spatial reasoning (does this fit in the room), and it can
hallucinate products that don't exist. Splitting the system into a
deterministic constraint layer (Stage A) and an LLM judgment layer (Stage B)
means the AI is only ever used for what it's actually good at — aesthetic
judgment and natural-language explanation — while every hard constraint is
enforced in code and is fully auditable.

## Room model — key assumption

The room is modeled as a rectangle (width x depth, in feet). Three zones —
**toilet**, **vanity** (the washbasin sits on top of it, so the basin
doesn't need separate floor width), and **shower enclosure** — are arranged
side by side along one wall. This is a standard layout for small/mid-sized
bathrooms and keeps the constraint logic exact and explainable.

This is a deliberate MVP scope decision, not an oversight. Full 2D
bin-packing for arbitrary/irregular room shapes (L-shaped rooms, multiple
walls, door swing clearance) is noted as future work.

Clearance and footprint values are taken from the catalog's
`category_spatial_rules`, which are themselves either sourced directly from
Kohler product documentation or from documented NKBA (National Kitchen &
Bath Association) planning standards where per-product data wasn't
available — see `data_policy` inside the catalog JSON for full provenance.

## Project structure

```
kohler-bathroom-ai/
├── README.md
├── requirements.txt
├── data/
│   └── kohler_catalog.json     # Product catalog with real Kohler India
│                                 data + documented spatial/material rules
├── output/
│   └── example_bathroom_layout.svg   # Sample rendered floorplan
└── src/
    ├── app.py                    # Flask web interface (recommended entry point)
    ├── templates/index.html      # Web UI page
    ├── static/style.css          # Web UI styling
    ├── static/app.js             # Web UI frontend logic
    ├── stage_a.py                 # Constraint engine + budget optimizer
    ├── stage_b.py                  # LLM reasoning layer (Gemini)
    ├── stage_c.py                   # 2D floorplan renderer (SVG)
    └── run_cli.py                    # Interactive CLI (Stage A only)
```

## Requirements

- Python 3.9 or later
- Stage A (`stage_a.py`) uses only the Python standard library — no
  install needed to run it alone
- Stage B (`stage_b.py`) requires the `google-genai` package and a free
  Gemini API key:

```bash
pip install -r requirements.txt
```

Then set your API key as an environment variable (never hardcode it in
the code):

```bash
# Mac/Linux
export GEMINI_API_KEY="your-key-here"

# Windows (Command Prompt)
set GEMINI_API_KEY=your-key-here

# Windows (PowerShell)
$env:GEMINI_API_KEY="your-key-here"
```

Get a **free** key (no credit card required) at
https://aistudio.google.com — click "Get API key" → "Create API key".

Note: on Gemini's free tier, Google may use your API inputs to help
improve their models. This is fine for this project's synthetic/public
catalog data, but worth knowing if you ever send anything sensitive.

## How to run

Clone the repo, then from the `src/` folder:

```bash
cd src
python run_cli.py
```

You'll be prompted for:
- Room width (ft)
- Room depth (ft)
- Budget (INR)
- Style preference (Modern / Classic Luxury / Japanese Zen)

Example session:

```
Room width in feet (e.g. 10): 10
Room depth in feet (e.g. 7): 7
Budget in INR (e.g. 60000): 60000
Style preference (Modern / Classic Luxury / Japanese Zen): Modern

✅ BUNDLE FOUND WITHIN BUDGET

Total price: INR 55680

Selected products:
  [washbasin] Brive Plus 540mm wall mount basin — INR 4400 (quality tier 1)
  [toilet] Reach Eco wall hung toilet — INR 17000 (quality tier 3)
  [shower_fixture] Rain Duet round 203mm Katalyst rainhead — INR 8900 (quality tier 5)
  [bathroom_faucet] Vive single-control tall basin faucet — INR 11880 (quality tier 5)
  [mirror] Essential capsule mirror - matte black — INR 13500 (quality tier 5)
```

### Running the web interface (recommended)

The easiest way to use the full system is through the browser interface:

```bash
cd src
python app.py
```

Then open **http://127.0.0.1:5000** in your browser. Enter room
dimensions, budget, and style, and click "Generate design" — the page
calls Stage A, then Stage B, then Stage C, and displays the floorplan,
the selected bundle, and the AI's design rationale, all in one page.

This requires `GEMINI_API_KEY` to be set (see Requirements above). If
it's missing or the AI call fails for any reason, the interface
gracefully falls back to Stage A's top-quality bundle with a clear
on-page notice, instead of showing an error page.

### Running the full pipeline from the command line

`run_cli.py` above only runs Stage A. To see the complete pipeline —
constraint filtering, AI style reasoning, and the rendered floorplan —
run `stage_c.py` directly, which chains all three stages:

```bash
cd src
python stage_c.py
```

This requires the `GEMINI_API_KEY` environment variable to be set (see
Requirements above), since it calls Stage B internally. It prints the
AI's design rationale and saves a floorplan image to
`bathroom_layout.svg` in the `src/` folder — open it in any browser or
image viewer. A sample output is included at
`output/example_bathroom_layout.svg`.

To customize the room/budget/style for this full pipeline run, edit the
constants at the top of the `if __name__ == "__main__":` block in
`stage_c.py` (`ROOM_WIDTH_FT`, `ROOM_DEPTH_FT`, `BUDGET_INR`, `STYLE`).

You can also run `stage_a.py` directly for a quick smoke test using
hardcoded example values at the bottom of the file:

```bash
python stage_a.py
```

## What Stage A handles as edge cases

- **Room too small**: if the room can't physically fit all three zones,
  the system returns `room_infeasible` with a specific reason (which
  zone doesn't fit and by how much) instead of guessing.
- **No products fit the space**: if the room technically has room for a
  zone but every catalog product for that category is still too large,
  returns `no_valid_products` naming the empty categories.
- **Budget too low**: if no valid combination fits within budget, the
  system doesn't fail — it returns the cheapest possible valid combination
  and clearly flags it as an over-budget fallback rather than silently
  picking something the user didn't ask for.

## Data provenance

The catalog (`data/kohler_catalog.json`) uses real Kohler India product
names, prices, and specifications sourced from official product
documentation. Fields not published per-SKU (e.g. some material and
clearance values) are filled using documented industry-standard planning
rules (NKBA guidelines), clearly separated from real per-product data via
the `data_policy`, `category_spatial_rules`, and `category_material_rules`
sections of the JSON. This is a synthetic-but-grounded catalog built for
demonstration purposes, not Kohler's live pricing or an official dataset.

## Roadmap (not yet in this repo)

- [ ] Arbitrary/L-shaped room layouts (currently single-wall linear only)

## Future production vision: full plumbing-engineering layer

The current MVP intentionally does not model plumbing at all — it assumes
standard fixtures that can be installed in the assumed layout without
plumbing being a selection factor. A production version of this system
would add real spatial plumbing validation:

- **Plumbing nodes as coordinates**: representing existing waste stacks
  and water supply points as (x, y) locations on the floor plan, rather
  than a single yes/no flag
- **Gravity/slope validation**: waste lines must slope downward toward
  the main stack (typically 1:40 to 1:50) — a real engine would compute
  whether a proposed fixture placement is reachable within that
  constraint, and flag layouts that would require running pipe through
  structural walls
- **A product dependency graph**: real fixtures often require specific
  companion parts (e.g., a smart toilet needing a compatible in-wall tank
  carrier, or a thermostatic shower valve needing a matching rough-in
  valve) — modeling this as a graph would let Stage A auto-include
  required "child" components and their true installed cost, not just
  the visible fixture price
- **Snap-to-node rendering**: a 2D/3D renderer that automatically aligns
  fixture placement to real plumbing anchor points

This was scoped out of the current MVP deliberately: it requires
engineering-grade plumbing data (pipe slope rules, product dependency
mappings) that isn't available in Kohler's public product documentation
and would need to be sourced from licensed plumbing codes and internal
product engineering data in a real deployment. Building it accurately
matters more than building it quickly — it's the natural next investment
for a production version of this tool, not a gap in the current design.
