"""
Stage A: Hard Constraint Engine + Budget Optimization
Kohler AI Bathroom Designer — Track 1

This module contains NO AI calls. It is pure deterministic logic:
1. Checks whether the room can physically fit toilet + vanity + shower zones
2. Filters each purchasable category's products by spatial fit
3. Runs a multi-choice knapsack optimization to pick the best combination
   of products (one per category) that maximizes quality within budget
4. Returns a validated shortlist per category for Stage B (LLM reasoning)
   to reason over, plus excluded items with reasons for explainability.

Layout assumption (documented, not hidden): the room is a rectangle and the
three floor zones — toilet, vanity (basin sits on top of it), and shower
enclosure — are arranged using one of a small set of layout templates
(single wall, L-shaped with corner shower, opposite walls), defined in
layouts.py. The template is either chosen by the customer or picked
automatically from the room's proportions. Full 2D bin-packing for arbitrary
room shapes is still out of scope for this MVP.
"""

import json
from itertools import product as cartesian_product

from layouts import (
    AUTO, DEFAULT_LAYOUT_ID, LAYOUTS,
    evaluate_layout, preference_order, auto_reason,
)

# Categories that consume floor space and need spatial reservation
SPATIAL_ZONE_CATEGORIES = ["toilet", "vanity", "shower_enclosure"]

# Categories that are actually purchased (have real SKUs in the catalog)
PURCHASABLE_CATEGORIES = ["toilet", "washbasin", "bathroom_faucet", "shower_fixture", "mirror"]

FT_TO_IN = 12


def load_catalog(path):
    with open(path, "r") as f:
        return json.load(f)


def ft_to_in(feet):
    return feet * FT_TO_IN


# ---------------------------------------------------------------------------
# STEP 1: Room-level spatial feasibility (zone reservation)
# ---------------------------------------------------------------------------

def compute_zone_requirements(catalog, room_width_ft, room_depth_ft, layout_id=DEFAULT_LAYOUT_ID):
    """
    Computes effective width/depth needed for the vanity and shower zones
    using category_spatial_rules, and checks whether the room can fit all
    three zones in the given layout template (see layouts.py).

    Returns a dict with feasibility status and per-zone budgets that later
    steps use to filter specific products. `toilet_budget` is the space the
    layout leaves for the toilet zone: max_width_in along its wall and
    max_depth_in out from it. (`max_toilet_width_in` is kept as an alias of
    the former, for older callers.)
    """
    rules = catalog["category_spatial_rules"]
    room_width_in = ft_to_in(room_width_ft)
    room_depth_in = ft_to_in(room_depth_ft)

    # Vanity zone: fixed proxy footprint (no real SKUs, just spatial reservation)
    vanity = rules["vanity"]
    vanity_w = vanity["planning_proxy_footprint_in"]["width"]
    vanity_d = vanity["planning_proxy_footprint_in"]["depth"] + vanity["front_clearance_in"]["minimum"]

    # Shower zone: fixed proxy footprint + entry clearance
    shower = rules["shower_enclosure"]
    shower_w = shower["planning_proxy_footprint_in"]["width"]
    shower_d = shower["planning_proxy_footprint_in"]["depth"] + shower["shower_entry_clearance_min_in"]

    vanity_zone = {"width": vanity_w, "depth": vanity_d}
    shower_zone = {"width": shower_w, "depth": shower_d}

    evaluation = evaluate_layout(layout_id, room_width_in, room_depth_in, vanity_zone, shower_zone)

    return {
        "feasible": evaluation["feasible"],
        "layout_id": layout_id,
        "room_width_in": room_width_in,
        "room_depth_in": room_depth_in,
        "vanity_zone": vanity_zone,
        "shower_zone": shower_zone,
        "toilet_budget": evaluation["toilet_budget"],
        "max_toilet_width_in": evaluation["toilet_budget"]["max_width_in"],
        "reason": evaluation["reason"],
    }


def _toilet_effective_size(catalog, toilet):
    """Zone size a toilet needs: footprint plus side and front clearance."""
    rules = catalog["category_spatial_rules"]
    fp = toilet["footprint_in"]
    return (
        fp["width"] + rules["toilet"]["centerline_to_sidewall_min_in"],
        fp["depth"] + toilet["clearance_required_in"]["front_min_in"],
    )


def resolve_layout(catalog, room_width_ft, room_depth_ft, requested=AUTO):
    """
    Turns the customer's layout choice into a concrete layout id.

    An explicit choice is honoured as-is (even if the room can't fit it —
    run_stage_a then reports why). "auto" tries the layouts in the order
    suited to the room's proportions and takes the first one that is
    geometrically feasible AND leaves room for at least one toilet in the
    catalog. If none qualifies it falls back to the default layout so the
    usual "room too small" messaging applies.
    """
    if requested != AUTO:
        if requested not in LAYOUTS:
            raise ValueError(f"Unknown layout: {requested!r}")
        return {"layout_id": requested, "auto": False, "reason": LAYOUTS[requested]["summary"],
                "others_fit": None}

    order = preference_order(ft_to_in(room_width_ft), ft_to_in(room_depth_ft))
    toilets = [p for p in catalog["products"] if p["category"] == "toilet"]

    viable = []
    for layout_id in order:
        zr = compute_zone_requirements(catalog, room_width_ft, room_depth_ft, layout_id)
        if not zr["feasible"]:
            continue
        budget = zr["toilet_budget"]
        if any(w <= budget["max_width_in"] and d <= budget["max_depth_in"]
               for w, d in (_toilet_effective_size(catalog, t) for t in toilets)):
            viable.append(layout_id)

    if not viable:
        return {"layout_id": DEFAULT_LAYOUT_ID, "auto": True, "reason": None, "others_fit": False}

    return {"layout_id": viable[0], "auto": True, "reason": auto_reason(viable[0], order),
            "others_fit": True}


# ---------------------------------------------------------------------------
# STEP 2: Per-category spatial filtering
# ---------------------------------------------------------------------------

def filter_by_space(catalog, zone_reqs):
    """
    For each purchasable category, returns (valid_products, excluded_products)
    based on whether each product's footprint fits within its reserved zone.
    Faucets, showerheads, and mirrors have no floor footprint, so they always
    pass spatial filtering (per category_spatial_rules floor_footprint: false).
    """
    rules = catalog["category_spatial_rules"]
    max_toilet_width_in = zone_reqs["toilet_budget"]["max_width_in"]
    max_toilet_depth_in = zone_reqs["toilet_budget"]["max_depth_in"]

    result = {}

    for cat_data in catalog["categories"]:
        cat = cat_data["id"]
        if cat not in PURCHASABLE_CATEGORIES:
            continue

        valid, excluded = [], []
        products = [p for p in catalog["products"] if p["category"] == cat]

        for p in products:
            if not p.get("floor_footprint_relevant", False):
                # Faucets, showerheads, mirrors: no floor constraint
                valid.append(p)
                continue

            fp = p["footprint_in"]
            clearance = p["clearance_required_in"]

            if cat == "toilet":
                eff_width = fp["width"] + rules["toilet"]["centerline_to_sidewall_min_in"]
                eff_depth = fp["depth"] + clearance["front_min_in"]
                too_wide = eff_width > max_toilet_width_in
                too_deep = eff_depth > max_toilet_depth_in
                fits = not too_wide and not too_deep
                if fits:
                    reason = None
                else:
                    shortfalls = []
                    if too_wide:
                        shortfalls.append(f"{max_toilet_width_in:.1f}in width")
                    if too_deep:
                        shortfalls.append(f"{max_toilet_depth_in:.1f}in depth")
                    reason = (
                        f"Toilet needs {eff_width:.1f}in width x {eff_depth:.1f}in depth "
                        f"(incl. clearance); only {' and '.join(shortfalls)} available."
                    )
            elif cat == "washbasin":
                vanity_zone = zone_reqs["vanity_zone"]
                fits = fp["width"] <= vanity_zone["width"] and fp["depth"] <= 21
                reason = None if fits else (
                    f"Basin footprint {fp['width']}x{fp['depth']}in exceeds the "
                    f"vanity zone it must sit on ({vanity_zone['width']}x21in)."
                )
            else:
                fits, reason = True, None

            if fits:
                valid.append(p)
            else:
                excluded.append({"id": p["id"], "name": p["name"], "reason": reason})

        result[cat] = {"valid": valid, "excluded": excluded}

    return result


# ---------------------------------------------------------------------------
# STEP 3: Budget-aware optimization (multi-choice knapsack)
# ---------------------------------------------------------------------------

def optimize_bundle(spatial_result, budget_inr, style=None, top_k=5):
    """
    Finds the top_k distinct, budget-valid, complete bundles (one product
    per purchasable category), ranked by total quality_tier (with a small
    style-match bonus). Small search space (5 categories x ~8 options each,
    <= ~33k combos) so exhaustive search is used — exact, no approximation.

    Returning multiple valid bundles (not just the single best) is a
    deliberate design choice: Stage B (the LLM reasoning layer) picks
    between these pre-validated whole bundles for style coherence. It
    never assembles a bundle itself, so it can never produce an
    over-budget or spatially invalid combination — Stage A has already
    guaranteed every option here is valid.

    Falls back to the cheapest valid combination (flagged) if nothing
    fits within budget.
    """
    categories = list(spatial_result.keys())
    option_lists = [spatial_result[c]["valid"] for c in categories]

    if any(len(opts) == 0 for opts in option_lists):
        empty_cats = [c for c, opts in zip(categories, option_lists) if not opts]
        return {"status": "no_valid_products", "empty_categories": empty_cats}

    def score(p):
        s = p["quality_tier"]
        if style:
            product_styles = [tag.lower() for tag in p.get("style_tags", [])]
            if style.strip().lower() in product_styles:
                s += 1  # style-match bonus, kept small so budget/quality still dominate
        return s

    valid_combos = []  # (total_score, total_price, combo)
    cheapest_combo, cheapest_price = None, float("inf")

    for combo in cartesian_product(*option_lists):
        total_price = sum(p["price_inr"] for p in combo)

        if total_price < cheapest_price:
            cheapest_combo, cheapest_price = combo, total_price

        if total_price <= budget_inr:
            total_score = sum(score(p) for p in combo)
            valid_combos.append((total_score, total_price, combo))

    if not valid_combos:
        return {
            "status": "over_budget_fallback",
            "message": (
                f"No combination fits within budget {budget_inr}. "
                f"Showing the cheapest possible combination at {cheapest_price} instead."
            ),
            "bundle": {p["category"]: p for p in cheapest_combo},
            "total_price": cheapest_price,
        }

    # Rank by score desc, then price desc (prefer using more of the budget
    # when quality ties), and keep only distinct bundles (dedupe by the
    # set of product ids, since cartesian_product order is deterministic
    # but ties can otherwise repeat the same combo under different scores).
    valid_combos.sort(key=lambda x: (x[0], x[1]), reverse=True)

    top_bundles = []
    for total_score, total_price, combo in valid_combos:
        bundle = {p["category"]: p for p in combo}
        if bundle not in top_bundles:
            top_bundles.append({
                "bundle": bundle,
                "total_price": total_price,
                "total_score": total_score,
            })
        if len(top_bundles) == top_k:
            break

    return {
        "status": "ok",
        "top_bundles": top_bundles,   # ranked list, top_bundles[0] is the best by score
        "bundle": top_bundles[0]["bundle"],       # kept for backward compatibility
        "total_price": top_bundles[0]["total_price"],
        "total_score": top_bundles[0]["total_score"],
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_stage_a(catalog_path, room_width_ft, room_depth_ft, budget_inr, style=None, layout=AUTO):
    catalog = load_catalog(catalog_path)

    chosen = resolve_layout(catalog, room_width_ft, room_depth_ft, layout)
    layout_info = {
        "layout_id": chosen["layout_id"],
        "layout_label": LAYOUTS[chosen["layout_id"]]["label"],
        "layout_auto": chosen["auto"],
        "layout_reason": chosen["reason"],
    }

    zone_reqs = compute_zone_requirements(catalog, room_width_ft, room_depth_ft, chosen["layout_id"])
    if not zone_reqs["feasible"]:
        reason = zone_reqs["reason"]
        if chosen["auto"]:
            reason += " No other layout (L-shaped, opposite walls) fits this room either."
        return {"status": "room_infeasible", "reason": reason, **layout_info}

    spatial_result = filter_by_space(catalog, zone_reqs)
    optimization_result = optimize_bundle(spatial_result, budget_inr, style)

    # This is the payload Stage B (LLM reasoning) will consume:
    # for each category, a validated shortlist (not just the single winner)
    # so the LLM has real choices to reason over for style coherence.
    shortlist_for_stage_b = {
        cat: [
            {
                "id": p["id"], "name": p["name"], "price_inr": p["price_inr"],
                "finish": p.get("finish"), "material": p.get("material"),
                "style_tags": p.get("style_tags"), "quality_tier": p["quality_tier"],
            }
            for p in spatial_result[cat]["valid"]
        ]
        for cat in spatial_result
    }

    return {
        "status": optimization_result["status"],
        **layout_info,
        "zone_requirements": zone_reqs,
        "shortlist_for_stage_b": shortlist_for_stage_b,
        "excluded_products": {cat: spatial_result[cat]["excluded"] for cat in spatial_result},
        "optimization_result": optimization_result,
    }


if __name__ == "__main__":
    # Quick smoke test when running this file directly.
    # For the interactive CLI, use run_cli.py instead.
    result = run_stage_a(
        catalog_path="../data/kohler_catalog.json",
        room_width_ft=10,
        room_depth_ft=7,
        budget_inr=60000,
        style="Modern",
    )
    print(json.dumps(result, indent=2, default=str))
