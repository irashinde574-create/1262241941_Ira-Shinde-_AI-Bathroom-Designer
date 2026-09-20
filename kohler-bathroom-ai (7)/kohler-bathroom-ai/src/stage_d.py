"""
Stage D: Conversational Refinement
Kohler AI Bathroom Designer — Track 1

Lets the customer adjust one item in an already-generated bundle with a
plain-language request ("show me a cheaper vanity", "I want a different
mirror") without regenerating the whole design from scratch.

DESIGN CHOICE: intent parsing here is deliberate rule-based keyword
matching, not another LLM call. This keeps refinement instant, free, and
immune to API failures — a second network-dependent AI call would add
risk without adding real value, since the vocabulary space for this
kind of request ("cheaper", "different", a category name) is small and
well-defined. The actual product-swap decision is 100% deterministic
code, following the same "hard rules, not LLM guesswork" principle as
Stage A: it only ever picks from products already proven to fit the
room and stay in budget.
"""

from stage_a import load_catalog, compute_zone_requirements, filter_by_space, PURCHASABLE_CATEGORIES
from layouts import DEFAULT_LAYOUT_ID

CATEGORY_KEYWORDS = {
    "washbasin": ["basin", "sink", "washbasin", "wash basin", "vanity"],
    "toilet": ["toilet", "wc", "commode"],
    "bathroom_faucet": ["faucet", "tap"],
    "shower_fixture": ["shower", "showerhead", "shower head", "rainhead", "rain head"],
    "mirror": ["mirror"],
}

DIRECTION_KEYWORDS = {
    "cheaper": ["cheap", "cheaper", "budget", "less expensive", "lower cost", "affordable", "reduce cost"],
    "pricier": ["expensive", "pricier", "premium", "upgrade", "nicer", "luxurious", "luxury", "better quality", "higher end"],
    "different": ["different", "another", "alternative", "change", "swap", "something else", "other"],
}


def parse_refinement_request(message):
    """
    Returns (target_category, direction) parsed from the user's free-text
    message, or (None, direction) if no known category is mentioned.
    Direction defaults to "different" if no direction keyword is found —
    e.g. "change the mirror" implies swap, not necessarily cheaper/pricier.
    """
    msg = message.lower()

    target_category = None
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            target_category = category
            break

    direction = "different"
    for d, keywords in DIRECTION_KEYWORDS.items():
        if any(kw in msg for kw in keywords):
            direction = d
            break

    return target_category, direction


def apply_refinement(catalog_path, room_width_ft, room_depth_ft, style,
                      budget_inr, current_bundle, target_category, direction,
                      layout_id=DEFAULT_LAYOUT_ID):
    """
    Finds the best replacement for target_category given the requested
    direction, keeping every other category in current_bundle fixed.
    Only ever selects from products already confirmed to fit the room
    (via the same spatial filter Stage A uses) and to keep the total
    bundle within budget. `layout_id` must be the layout the design was
    generated with, so the spatial filter uses the same toilet budget.
    """
    if target_category not in PURCHASABLE_CATEGORIES:
        return {"status": "unknown_category",
                "message": "Tell me which item to change: basin, toilet, faucet, showerhead, or mirror."}

    catalog = load_catalog(catalog_path)
    zone_reqs = compute_zone_requirements(catalog, room_width_ft, room_depth_ft, layout_id)
    spatial_result = filter_by_space(catalog, zone_reqs)

    current_product = current_bundle[target_category]
    current_price = current_product["price_inr"]

    other_categories_cost = sum(
        p["price_inr"] for cat, p in current_bundle.items() if cat != target_category
    )
    remaining_budget = budget_inr - other_categories_cost

    candidates = [p for p in spatial_result[target_category]["valid"] if p["id"] != current_product["id"]]
    candidates = [p for p in candidates if p["price_inr"] <= remaining_budget]

    if direction == "cheaper":
        candidates = [p for p in candidates if p["price_inr"] < current_price]
        candidates.sort(key=lambda p: -p["quality_tier"])  # best quality among cheaper options
    elif direction == "pricier":
        candidates = [p for p in candidates if p["price_inr"] > current_price]
        candidates.sort(key=lambda p: (-p["quality_tier"], p["price_inr"]))
    else:  # "different" — closest price, different product
        candidates.sort(key=lambda p: abs(p["price_inr"] - current_price))

    if not candidates:
        return {
            "status": "no_alternative",
            "message": (
                f"No {direction} option for that item fits your remaining budget "
                f"(INR {remaining_budget:,} after the rest of the bundle). "
                f"Try a different request, or increase your budget."
            ),
        }

    chosen = candidates[0]
    new_bundle = dict(current_bundle)
    new_bundle[target_category] = chosen
    new_total = other_categories_cost + chosen["price_inr"]

    return {
        "status": "ok",
        "bundle": new_bundle,
        "total_price": new_total,
        "changed_category": target_category,
        "old_product_name": current_product["name"],
        "new_product_name": chosen["name"],
        "price_delta": chosen["price_inr"] - current_price,
    }
