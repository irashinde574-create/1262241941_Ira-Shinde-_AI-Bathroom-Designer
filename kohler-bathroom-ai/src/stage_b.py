"""
Stage B: LLM Reasoning Layer
Kohler AI Bathroom Designer — Track 1

This module makes exactly one AI call. It receives the top-K budget-valid,
spatially-valid bundles produced by Stage A (stage_a.py) and asks an LLM
to:
  1. Choose the single most aesthetically coherent bundle for the given
     style theme (matching finishes, materials, and overall design language
     across the chosen products)
  2. Explain the reasoning in plain language, referencing specific
     attributes (finish, material) of the chosen products

CRITICAL DESIGN CONSTRAINT: the LLM never assembles a bundle itself and
never sees budget or dimension numbers to reason about. It only ever
chooses an index from a pre-validated list of complete bundles that
Stage A has already guaranteed are physically and financially valid.
This makes it structurally impossible for Stage B to produce an invalid
recommendation, no matter how the LLM reasons.

Requires: pip install google-genai
Requires: GEMINI_API_KEY environment variable set
(Get a free key with no credit card at https://aistudio.google.com)
"""

import os
import json
from google import genai

MODEL = "gemini-3.6-flash"  # current Gemini Flash model, free-tier available

SYSTEM_PROMPT = """You are a bathroom design consultant for Kohler.

You will be given a style theme and a list of pre-validated, complete
bathroom product bundles. Every bundle listed is ALREADY confirmed to fit
the customer's room and budget — you do not need to check space or price.

Your only job:
1. Choose the ONE bundle (by its index) that best matches the given style
   theme, based on finish, material, and overall design coherence across
   the products in that bundle.
2. Write a short, customer-facing explanation (3-5 sentences) of why this
   bundle works well together for that style — mention specific finishes
   or materials that reinforce the coherence.

Rules:
- You MUST choose one of the bundle indexes given. Never invent a new
  combination or suggest a product that isn't already in the chosen bundle.
- Do not comment on price or whether something "fits" — that has already
  been verified. Focus purely on aesthetic and material coherence.
- Respond ONLY with valid JSON matching this exact schema, no other text:

{
  "selected_bundle_index": <integer>,
  "rationale": "<string>"
}
"""


def build_user_prompt(style, top_bundles):
    """
    Formats Stage A's top_bundles into a compact, LLM-readable prompt.
    Only the attributes relevant to style reasoning are included
    (finish, material, style_tags) — price and dimensions are deliberately
    left out, since Stage B should never need to reason about them.
    """
    bundles_for_prompt = []
    for i, tb in enumerate(top_bundles):
        bundle_view = {}
        for category, product in tb["bundle"].items():
            bundle_view[category] = {
                "name": product["name"],
                "finish": product.get("finish"),
                "material": product.get("material"),
                "style_tags": product.get("style_tags"),
            }
        bundles_for_prompt.append({"index": i, "products": bundle_view})

    return json.dumps({
        "style_theme": style,
        "bundles": bundles_for_prompt,
    }, indent=2)


def run_stage_b(style, top_bundles):
    """
    Calls the LLM with the constrained prompt above, parses the JSON
    response, and validates that the chosen index actually exists.
    Returns the full selected bundle (merged back from Stage A's data,
    including price/dimensions) plus the LLM's rationale.
    """
    if not top_bundles:
        return {"status": "error", "message": "No bundles provided to Stage B."}

    user_prompt = build_user_prompt(style, top_bundles)

    try:
        client = genai.Client()  # reads GEMINI_API_KEY from environment
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt,
            config={
                "system_instruction": SYSTEM_PROMPT,
                "max_output_tokens": 500,
            },
        )
        raw_text = response.text.strip()

        # Defensive parsing: strip markdown code fences if the model adds them
        # despite instructions, before attempting JSON parsing.
        cleaned = raw_text.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)

    except json.JSONDecodeError:
        return {
            "status": "error",
            "message": "LLM did not return valid JSON.",
            "raw_response": raw_text,
        }
    except Exception as e:
        return {"status": "error", "message": f"API call failed: {e}"}

    selected_index = parsed.get("selected_bundle_index")
    rationale = parsed.get("rationale", "")

    # Validate the index is one Stage A actually offered — this is the
    # safety check that makes the whole system robust even if the LLM
    # misbehaves: an out-of-range index is caught here, not trusted blindly.
    if not isinstance(selected_index, int) or not (0 <= selected_index < len(top_bundles)):
        return {
            "status": "error",
            "message": f"LLM returned an invalid bundle index: {selected_index}",
            "raw_response": raw_text,
        }

    selected = top_bundles[selected_index]

    return {
        "status": "ok",
        "selected_bundle_index": selected_index,
        "final_bundle": selected["bundle"],
        "total_price": selected["total_price"],
        "rationale": rationale,
    }


if __name__ == "__main__":
    # Quick standalone test using a fabricated Stage A output shape.
    # In real use, top_bundles comes from stage_a.run_stage_a(...)["optimization_result"]["top_bundles"]
    from stage_a import run_stage_a

    stage_a_result = run_stage_a("../data/kohler_catalog.json", 10, 7, 80000, style="Modern")

    if stage_a_result["status"] != "ok":
        print("Stage A did not return a usable result:", stage_a_result)
    else:
        top_bundles = stage_a_result["optimization_result"]["top_bundles"]
        result = run_stage_b("Modern", top_bundles)
        print(json.dumps(result, indent=2, default=str))
