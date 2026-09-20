"""
app.py — Web interface for the Kohler AI Bathroom Designer

Runs the full Stage A -> Stage B -> Stage C pipeline behind a simple
Flask app, so the tool can be used through a browser instead of the CLI.

Run with:
    cd src
    python app.py

Then open http://127.0.0.1:5000 in your browser.
"""

import os
from flask import Flask, render_template, request, jsonify, url_for

from stage_a import run_stage_a
from stage_b import run_stage_b
from stage_c import get_floorplan_svg, get_3d_scene_data
from stage_d import parse_refinement_request, apply_refinement

app = Flask(__name__)

CATALOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "kohler_catalog.json")
PRODUCT_PHOTOS_DIR = os.path.join(os.path.dirname(__file__), "static", "product_photos")
PRODUCT_MESHES_DIR = os.path.join(os.path.dirname(__file__), "static", "product_meshes")
PHOTO_EXTENSIONS = ["jpg", "jpeg", "png", "webp"]


def get_product_photo_url(category):
    """
    Returns the static URL for a category's representative product photo
    if the user has placed one in static/product_photos/, else None.
    """
    for ext in PHOTO_EXTENSIONS:
        if os.path.exists(os.path.join(PRODUCT_PHOTOS_DIR, f"{category}.{ext}")):
            return url_for("static", filename=f"product_photos/{category}.{ext}")
    return None


def get_product_mesh_url(category):
    """
    Returns the static URL for a category's AI-generated 3D mesh (.glb)
    if one has been placed in static/product_meshes/, else None.

    This is the top tier of a three-tier fallback for the 3D view:
    real AI mesh (if present) -> procedural shape (always available,
    guaranteed free/reliable) -> the procedural shape already IS the
    guaranteed fallback, so this check is purely additive: dropping a
    .glb file in later upgrades that category's look with zero code
    changes and zero risk to what already works.
    """
    mesh_path = os.path.join(PRODUCT_MESHES_DIR, f"{category}.glb")
    if os.path.exists(mesh_path):
        return url_for("static", filename=f"product_meshes/{category}.glb")
    return None


def attach_photo_urls(products):
    for p in products:
        p["photo_url"] = get_product_photo_url(p["category"])
    return products


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/design", methods=["POST"])
def design():
    data = request.get_json(force=True)

    try:
        room_width_ft = float(data.get("room_width_ft"))
        room_depth_ft = float(data.get("room_depth_ft"))
        budget_inr = int(data.get("budget_inr"))
        style = (data.get("style") or "").strip()
    except (TypeError, ValueError):
        return jsonify({"status": "input_error",
                         "message": "Enter valid numbers for room width, depth, and budget."}), 400

    if room_width_ft <= 0 or room_depth_ft <= 0 or budget_inr <= 0 or not style:
        return jsonify({"status": "input_error",
                         "message": "All fields are required and must be positive values."}), 400

    stage_a_result = run_stage_a(CATALOG_PATH, room_width_ft, room_depth_ft, budget_inr, style)

    if stage_a_result["status"] == "room_infeasible":
        return jsonify({"status": "room_infeasible", "message": stage_a_result["reason"]})

    if stage_a_result["status"] == "no_valid_products":
        empty_cats = stage_a_result["optimization_result"]["empty_categories"]
        return jsonify({
            "status": "no_valid_products",
            "message": f"No products fit the available space for: {', '.join(empty_cats)}. "
                       f"Try a larger room.",
        })

    opt = stage_a_result["optimization_result"]
    top_bundles = opt.get("top_bundles")

    # over_budget_fallback has no top_bundles list (only one cheapest combo) —
    # handle it directly rather than sending it into Stage B.
    if stage_a_result["status"] == "over_budget_fallback":
        final_bundle = opt["bundle"]
        total_price = opt["total_price"]
        rationale = opt["message"]
        notice = "over_budget_fallback"
    else:
        stage_b_result = run_stage_b(style, top_bundles)
        if stage_b_result["status"] == "ok":
            final_bundle = stage_b_result["final_bundle"]
            total_price = stage_b_result["total_price"]
            rationale = stage_b_result["rationale"]
            notice = None
        else:
            # Graceful degradation: if the AI reasoning call fails (no API
            # key, network issue, etc.), fall back to Stage A's top-ranked
            # bundle by quality score instead of failing the whole request.
            best = top_bundles[0]
            final_bundle = best["bundle"]
            total_price = best["total_price"]
            rationale = ("AI style reasoning is unavailable right now, so this is the "
                         "highest-quality option that fits your space and budget instead.")
            notice = "stage_b_unavailable"

    svg_markup = get_floorplan_svg(CATALOG_PATH, room_width_ft, room_depth_ft, style,
                                     final_bundle, total_price)
    scene_3d = get_3d_scene_data(CATALOG_PATH, room_width_ft, room_depth_ft, final_bundle)

    products = [
        {"category": cat, "name": p["name"], "price_inr": p["price_inr"],
         "finish": p.get("finish"), "material": p.get("material")}
        for cat, p in final_bundle.items()
    ]
    products = attach_photo_urls(products)

    # Full pool of spatially/budget-valid alternatives per category, so the
    # customer can see what else was considered, not just the final pick.
    available_options = {
        cat: attach_photo_urls([
            {"id": p["id"], "name": p["name"], "price_inr": p["price_inr"],
             "finish": p.get("finish"), "material": p.get("material"), "category": cat,
             "quality_tier": p["quality_tier"], "is_selected": p["id"] == final_bundle[cat]["id"]}
            for p in sorted(options, key=lambda x: x["price_inr"])
        ])
        for cat, options in stage_a_result["shortlist_for_stage_b"].items()
    }

    for obj in scene_3d["objects"]:
        obj["photo_url"] = get_product_photo_url(obj["category"])
        obj["mesh_url"] = get_product_mesh_url(obj["category"])

    return jsonify({
        "status": "ok",
        "notice": notice,
        "total_price": total_price,
        "products": products,
        "rationale": rationale,
        "svg": svg_markup,
        "scene_3d": scene_3d,
        "available_options": available_options,
        "raw_bundle": final_bundle,  # full product dicts, needed by /api/refine to make further edits
    })


@app.route("/api/refine", methods=["POST"])
def refine():
    data = request.get_json(force=True)

    try:
        room_width_ft = float(data.get("room_width_ft"))
        room_depth_ft = float(data.get("room_depth_ft"))
        budget_inr = int(data.get("budget_inr"))
        style = (data.get("style") or "").strip()
        current_bundle = data.get("current_bundle")
        message = (data.get("message") or "").strip()
    except (TypeError, ValueError):
        return jsonify({"status": "input_error", "message": "Something went wrong reading your request."}), 400

    if not current_bundle or not message:
        return jsonify({"status": "input_error", "message": "Generate a design first, then tell me what to change."})

    target_category, direction = parse_refinement_request(message)

    if target_category is None:
        return jsonify({
            "status": "parse_error",
            "message": "Tell me which item to change — for example \"a cheaper vanity\" "
                       "or \"a different mirror\".",
        })

    result = apply_refinement(CATALOG_PATH, room_width_ft, room_depth_ft, style,
                               budget_inr, current_bundle, target_category, direction)

    if result["status"] != "ok":
        return jsonify(result)

    svg_markup = get_floorplan_svg(CATALOG_PATH, room_width_ft, room_depth_ft, style,
                                     result["bundle"], result["total_price"])
    scene_3d = get_3d_scene_data(CATALOG_PATH, room_width_ft, room_depth_ft, result["bundle"])

    products = [
        {"category": cat, "name": p["name"], "price_inr": p["price_inr"],
         "finish": p.get("finish"), "material": p.get("material")}
        for cat, p in result["bundle"].items()
    ]
    products = attach_photo_urls(products)

    # Recompute the valid-options pool for the (possibly still-current) categories,
    # so the "available options" panel stays in sync after a refinement.
    zone_reqs_refresh = run_stage_a(CATALOG_PATH, room_width_ft, room_depth_ft, budget_inr, style)
    available_options = {}
    if zone_reqs_refresh["status"] in ("ok", "over_budget_fallback"):
        shortlist_source = zone_reqs_refresh.get("shortlist_for_stage_b", {})
        available_options = {
            cat: attach_photo_urls([
                {"id": p["id"], "name": p["name"], "price_inr": p["price_inr"],
                 "finish": p.get("finish"), "material": p.get("material"), "category": cat,
                 "quality_tier": p["quality_tier"], "is_selected": p["id"] == result["bundle"][cat]["id"]}
                for p in sorted(options, key=lambda x: x["price_inr"])
            ])
            for cat, options in shortlist_source.items()
        }

    for obj in scene_3d["objects"]:
        obj["photo_url"] = get_product_photo_url(obj["category"])
        obj["mesh_url"] = get_product_mesh_url(obj["category"])

    delta = result["price_delta"]
    delta_text = f"{'+' if delta > 0 else ''}INR {delta:,}"
    change_message = (f"Swapped \"{result['old_product_name']}\" for "
                      f"\"{result['new_product_name']}\" ({delta_text})")

    return jsonify({
        "status": "ok",
        "products": products,
        "total_price": result["total_price"],
        "svg": svg_markup,
        "scene_3d": scene_3d,
        "available_options": available_options,
        "raw_bundle": result["bundle"],
        "change_message": change_message,
    })


if __name__ == "__main__":
    app.run(debug=True)
