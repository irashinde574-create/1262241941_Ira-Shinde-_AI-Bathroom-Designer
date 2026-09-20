"""
Stage C: 2D Floorplan Renderer
Kohler AI Bathroom Designer — Track 1

Takes the room dimensions, the zone requirements computed by Stage A, and
the final product bundle chosen by Stage B, and draws a labeled, to-scale
top-down floorplan as an SVG file.

No external dependencies — pure string-based SVG generation. SVG was
chosen over a raster image because it renders natively in GitHub READMEs,
browsers, and most image viewers without needing any image library
installed, and stays crisp at any zoom level.

Layout matches the single-wall linear model from Stage A: toilet, vanity
(washbasin sits on top of it), and shower enclosure arranged left to right
along one wall, in that order.
"""

import json
from stage_a import load_catalog, ft_to_in, compute_zone_requirements

PX_PER_IN = 8       # scale factor: pixels per inch
MARGIN = 60          # margin around the room for labels


def compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle):
    """
    Computes pixel-ready rectangles for each zone (toilet, vanity, shower)
    and the actual fixture footprint inside each zone, using the same
    effective-width/depth formulas Stage A used to validate fit. Returns
    everything in inches; conversion to pixels happens at render time.
    """
    rules = catalog["category_spatial_rules"]
    zone_reqs = compute_zone_requirements(catalog, room_width_ft, room_depth_ft)

    toilet = final_bundle["toilet"]
    toilet_fp = toilet["footprint_in"]
    toilet_eff_width = toilet_fp["width"] + rules["toilet"]["centerline_to_sidewall_min_in"]
    toilet_eff_depth = toilet_fp["depth"] + toilet["clearance_required_in"]["front_min_in"]

    vanity_zone = zone_reqs["vanity_zone"]   # proxy footprint, no real SKU
    shower_zone = zone_reqs["shower_zone"]   # proxy footprint, no real SKU

    basin = final_bundle["washbasin"]
    basin_fp = basin["footprint_in"]

    # Left-to-right cumulative x positions along the fixture wall (y=0)
    x0_toilet = 0
    x1_toilet = toilet_eff_width
    x0_vanity = x1_toilet
    x1_vanity = x0_vanity + vanity_zone["width"]
    x0_shower = x1_vanity
    x1_shower = x0_shower + shower_zone["width"]

    return {
        "room_width_in": zone_reqs["room_width_in"],
        "room_depth_in": zone_reqs["room_depth_in"],
        "zones": {
            "toilet": {
                "x0": x0_toilet, "x1": x1_toilet, "depth": toilet_eff_depth,
                "footprint": toilet_fp, "label": toilet["name"], "price": toilet["price_inr"],
            },
            "vanity": {
                "x0": x0_vanity, "x1": x1_vanity, "depth": vanity_zone["depth"],
                "footprint": basin_fp, "label": basin["name"], "price": basin["price_inr"],
                "zone_note": "Vanity + basin zone (vanity is a planning allowance; basin shown to scale)",
            },
            "shower": {
                "x0": x0_shower, "x1": x1_shower, "depth": shower_zone["depth"],
                "footprint": None, "label": "Shower area (space reserved, fixtures TBD)", "price": None,
            },
        },
    }


def _rect(x, y, w, h, fill, stroke="#333", stroke_width=1.5, dash=None, opacity=1.0):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" '
            f'opacity="{opacity}"{dash_attr} rx="4"/>')


def _text(x, y, content, size=13, anchor="middle", weight="normal", color="#222"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, sans-serif" '
            f'font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" '
            f'fill="{color}">{content}</text>')


def _wrap_label(text, max_chars=22):
    """
    Wraps a product name onto at most two lines at a word boundary
    (never mid-word), for labels drawn under floorplan zones.
    """
    words = text.split()
    line1, line2 = "", ""
    for word in words:
        candidate = (line1 + " " + word).strip()
        if len(candidate) <= max_chars and not line2:
            line1 = candidate
        else:
            line2 = (line2 + " " + word).strip()
    return line1, line2


def generate_floorplan_svg(layout, style, total_price):
    room_w_in = layout["room_width_in"]
    room_d_in = layout["room_depth_in"]
    room_w_px = room_w_in * PX_PER_IN
    room_d_px = room_d_in * PX_PER_IN

    svg_w = room_w_px + 2 * MARGIN
    svg_h = room_d_px + 2 * MARGIN + 60  # extra space for title

    parts = []
    parts.append(f'<svg width="{svg_w:.0f}" height="{svg_h:.0f}" '
                  f'viewBox="0 0 {svg_w:.0f} {svg_h:.0f}" xmlns="http://www.w3.org/2000/svg">')
    parts.append(f'<rect width="{svg_w:.0f}" height="{svg_h:.0f}" fill="#fafafa"/>')

    title_y = 30
    parts.append(_text(svg_w / 2, title_y, f"Bathroom Layout — {style} Style", size=18, weight="bold"))
    parts.append(_text(svg_w / 2, title_y + 22,
                        f"Room: {room_w_in/12:.1f}ft x {room_d_in/12:.1f}ft &#8226; Total: INR {total_price:,}",
                        size=13, color="#555"))

    origin_x = MARGIN
    origin_y = MARGIN + 60

    # Room outline
    parts.append(_rect(origin_x, origin_y, room_w_px, room_d_px, fill="#ffffff", stroke="#222", stroke_width=2.5))

    zone_colors = {"toilet": "#e8f0fe", "vanity": "#fef6e0", "shower": "#e6f7f1"}
    fixture_colors = {"toilet": "#4a86e8", "vanity": "#e0a721", "shower": "#3aa88a"}

    for zone_name, zone in layout["zones"].items():
        zx = origin_x + zone["x0"] * PX_PER_IN
        zw = (zone["x1"] - zone["x0"]) * PX_PER_IN
        zh = zone["depth"] * PX_PER_IN

        # Zone allowance (includes clearance) — light fill, dashed border
        parts.append(_rect(zx, origin_y, zw, zh, fill=zone_colors[zone_name],
                            stroke=fixture_colors[zone_name], dash="4,3", opacity=0.6))

        # Actual fixture footprint, drawn to scale against the wall, if known
        if zone["footprint"]:
            fw = zone["footprint"]["width"] * PX_PER_IN
            fd = zone["footprint"]["depth"] * PX_PER_IN
            fx = zx + (zw - fw) / 2   # centered horizontally within the zone
            fy = origin_y             # flush against the wall
            parts.append(_rect(fx, fy, fw, fd, fill=fixture_colors[zone_name], stroke="#222", stroke_width=1))

        # Label (wrapped onto two lines at a word boundary, never mid-word)
        label_line1, label_line2 = _wrap_label(zone["label"])
        label_y = origin_y + zh + 18
        parts.append(_text(zx + zw / 2, label_y, label_line1, size=11, weight="bold"))
        next_y = label_y
        if label_line2:
            next_y += 14
            parts.append(_text(zx + zw / 2, next_y, label_line2, size=11, weight="bold"))
        if zone["price"]:
            parts.append(_text(zx + zw / 2, next_y + 15, f"INR {zone['price']:,}", size=10, color="#555"))

    # Leftover open floor space to the right of the last zone, if any
    last_zone = layout["zones"]["shower"]
    used_width_in = last_zone["x1"]
    leftover_in = room_w_in - used_width_in
    if leftover_in > 6:  # only label if it's a meaningfully sized gap
        lx = origin_x + used_width_in * PX_PER_IN
        lw = leftover_in * PX_PER_IN
        parts.append(_rect(lx, origin_y, lw, room_d_px, fill="#ffffff", stroke="#ccc",
                            stroke_width=1, dash="3,3", opacity=0.5))
        parts.append(_text(lx + lw / 2, origin_y + room_d_px / 2, "Open", size=11, color="#999"))
        parts.append(_text(lx + lw / 2, origin_y + room_d_px / 2 + 14, "floor", size=11, color="#999"))
        parts.append(_text(lx + lw / 2, origin_y + room_d_px / 2 + 28, "space", size=11, color="#999"))

    # Dimension labels along the outside edges
    parts.append(_text(origin_x + room_w_px / 2, origin_y - 10, f"{room_w_in/12:.1f} ft", size=11, color="#777"))
    parts.append(_text(origin_x - 15, origin_y + room_d_px / 2, f"{room_d_in/12:.1f} ft",
                        size=11, color="#777", anchor="middle"))

    parts.append('</svg>')
    return "\n".join(parts)


def run_stage_c(catalog_path, room_width_ft, room_depth_ft, style, final_bundle, total_price,
                 output_path="bathroom_layout.svg"):
    svg_content = get_floorplan_svg(catalog_path, room_width_ft, room_depth_ft, style, final_bundle, total_price)

    with open(output_path, "w") as f:
        f.write(svg_content)

    return output_path


def get_floorplan_svg(catalog_path, room_width_ft, room_depth_ft, style, final_bundle, total_price):
    """
    Returns the SVG markup as a string without writing to disk — used by
    the web interface (app.py) to embed the floorplan directly in a page
    response instead of serving a separate file.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle)
    return generate_floorplan_svg(layout, style, total_price)


# ---------------------------------------------------------------------------
# 3D scene data (consumed by Three.js on the frontend — see static/app.js)
# ---------------------------------------------------------------------------

# The tool only collects room width/depth, not ceiling height, so a
# standard residential ceiling height is assumed for the 3D view. This is
# a documented visual assumption, not a measured input.
ASSUMED_CEILING_HEIGHT_IN = 96   # 8 ft, standard residential ceiling
VANITY_COUNTER_HEIGHT_IN = 32    # typical vanity counter height
SHOWER_ENCLOSURE_HEIGHT_IN = 78  # typical enclosure/glass height
MIRROR_MOUNT_HEIGHT_IN = 40      # height of mirror's bottom edge above floor
FAUCET_MOUNT_HEIGHT_IN = 32      # approx faucet base height above floor, on the counter
SHOWERHEAD_MOUNT_HEIGHT_IN = 80  # approx rainhead height near ceiling

CATEGORY_COLORS_3D = {
    "toilet": "#4a86e8",
    "washbasin": "#e0a721",
    "vanity_counter": "#d8c9a3",
    "shower_zone": "#3aa88a",
    "bathroom_faucet": "#8b8b8b",
    "shower_fixture": "#8b8b8b",
    "mirror": "#b7c4c9",
}


def classify_shape_family(category, name):
    """
    Maps a product to a simple procedural shape family based on its real
    catalog name (e.g. "vessel", "wall mount", "capsule", "rainhead").
    This drives which handful of Three.js primitives the frontend combines
    to represent it — a recognizable silhouette per family, not a full
    per-SKU mesh. Every product in a family still renders at its own real
    dimensions_in from the catalog; only the shape template is shared.
    """
    n = name.lower()

    if category == "toilet":
        return "wall_hung_toilet"

    if category == "washbasin":
        if "wall mount" in n:
            return "wall_mount_basin"
        if "under counter" in n:
            return "undercounter_basin"
        return "vessel_basin"

    if category == "bathroom_faucet":
        return "tall_faucet" if "tall" in n else "standard_faucet"

    if category == "mirror":
        if "capsule" in n:
            return "capsule_mirror"
        if "round" in n:
            return "round_mirror"
        return "rectangular_mirror"

    if category == "shower_fixture":
        return "rainhead" if ("rainhead" in n or "rain head" in n) else "showerhead"

    return None  # vanity_counter, shower_zone: architectural allowances, not products


def get_3d_scene_data(catalog_path, room_width_ft, room_depth_ft, final_bundle):
    """
    Returns a JSON-serializable description of the room and every fixture
    as simple 3D boxes (position + dimensions, in inches), for the
    frontend to render with Three.js. This is a stylized visualization,
    not a CAD-precision model — the floor footprints (toilet, vanity,
    shower zone) are exactly to scale, matching Stage A's real constraint
    math, but fixture heights and small accessories (faucet, showerhead,
    mirror) use reasonable standard placement assumptions documented
    above, since exact mounting heights aren't in the product catalog.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle)

    room_width_in = layout["room_width_in"]
    room_depth_in = layout["room_depth_in"]

    objects = []

    toilet_zone = layout["zones"]["toilet"]
    toilet_product = final_bundle["toilet"]
    toilet_fp = toilet_product["footprint_in"]
    toilet_height = toilet_product["dimensions_in"].get("height") or 15
    toilet_x = toilet_zone["x0"] + (toilet_zone["x1"] - toilet_zone["x0"] - toilet_fp["width"]) / 2
    objects.append({
        "name": toilet_product["name"], "category": "toilet",
        "color": CATEGORY_COLORS_3D["toilet"],
        "shape_family": classify_shape_family("toilet", toilet_product["name"]),
        "x": toilet_x, "y": 0, "z": 0,
        "w": toilet_fp["width"], "h": toilet_height, "d": toilet_fp["depth"],
    })

    vanity_zone = layout["zones"]["vanity"]
    vanity_width = vanity_zone["x1"] - vanity_zone["x0"]
    # The vanity counter itself (a planning allowance, no real SKU in the catalog)
    objects.append({
        "name": "Vanity counter (planning allowance)", "category": "vanity_counter",
        "color": CATEGORY_COLORS_3D["vanity_counter"],
        "x": vanity_zone["x0"], "y": 0, "z": 0,
        "w": vanity_width, "h": VANITY_COUNTER_HEIGHT_IN, "d": 21,
    })

    basin_product = final_bundle["washbasin"]
    basin_fp = basin_product["footprint_in"]
    basin_height = basin_product["dimensions_in"].get("height") or 6
    basin_x = vanity_zone["x0"] + (vanity_width - basin_fp["width"]) / 2
    objects.append({
        "name": basin_product["name"], "category": "washbasin",
        "color": CATEGORY_COLORS_3D["washbasin"],
        "shape_family": classify_shape_family("washbasin", basin_product["name"]),
        "x": basin_x, "y": VANITY_COUNTER_HEIGHT_IN, "z": 0,
        "w": basin_fp["width"], "h": basin_height, "d": basin_fp["depth"],
    })

    faucet_product = final_bundle["bathroom_faucet"]
    objects.append({
        "name": faucet_product["name"], "category": "bathroom_faucet",
        "color": CATEGORY_COLORS_3D["bathroom_faucet"],
        "shape_family": classify_shape_family("bathroom_faucet", faucet_product["name"]),
        "x": basin_x + basin_fp["width"] / 2 - 1, "y": FAUCET_MOUNT_HEIGHT_IN, "z": basin_fp["depth"] - 2,
        "w": 3, "h": 12, "d": 3,
    })

    mirror_product = final_bundle["mirror"]
    mirror_width = mirror_product["dimensions_in"]["width"]
    mirror_height = mirror_product["dimensions_in"].get("depth") or 32  # catalog quirk: mirror's vertical extent is stored in "depth"
    mirror_x = vanity_zone["x0"] + (vanity_width - mirror_width) / 2
    objects.append({
        "name": mirror_product["name"], "category": "mirror",
        "color": CATEGORY_COLORS_3D["mirror"],
        "shape_family": classify_shape_family("mirror", mirror_product["name"]),
        "x": mirror_x, "y": MIRROR_MOUNT_HEIGHT_IN, "z": 20.5,
        "w": mirror_width, "h": min(mirror_height, 40), "d": 1.5,
    })

    shower_zone = layout["zones"]["shower"]
    shower_width = shower_zone["x1"] - shower_zone["x0"]
    objects.append({
        "name": "Shower area (space reserved)", "category": "shower_zone",
        "color": CATEGORY_COLORS_3D["shower_zone"],
        "x": shower_zone["x0"], "y": 0, "z": 0,
        "w": shower_width, "h": SHOWER_ENCLOSURE_HEIGHT_IN, "d": shower_width,
        "transparent": True,
    })

    shower_fixture_product = final_bundle["shower_fixture"]
    objects.append({
        "name": shower_fixture_product["name"], "category": "shower_fixture",
        "color": CATEGORY_COLORS_3D["shower_fixture"],
        "shape_family": classify_shape_family("shower_fixture", shower_fixture_product["name"]),
        "x": shower_zone["x0"] + shower_width / 2 - 4, "y": SHOWERHEAD_MOUNT_HEIGHT_IN, "z": 4,
        "w": 8, "h": 2, "d": 8,
    })

    return {
        "room": {"width_in": room_width_in, "depth_in": room_depth_in, "height_in": ASSUMED_CEILING_HEIGHT_IN},
        "objects": objects,
    }


# Approximate real-world heights (inches) used only for the 3D preview —
# not sourced per-product, since the catalog doesn't track fixture height
# for every category. These are reasonable industry-typical values
# (standard toilet bowl height, vanity counter height, shower enclosure
# height) used purely to make the 3D preview readable, not as precise
# product specs.
ZONE_HEIGHTS_IN = {"toilet": 16, "vanity": 32, "shower": 84}


def get_layout_data(catalog_path, room_width_ft, room_depth_ft, final_bundle):
    """
    Returns a plain-JSON-serializable description of the room and zone
    geometry, for the browser's 3D preview to build boxes from directly
    without re-deriving any spatial math client-side.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle)

    zones = []
    for name, z in layout["zones"].items():
        zones.append({
            "name": name,
            "x0": z["x0"], "x1": z["x1"],
            "depth": z["depth"],
            "height": ZONE_HEIGHTS_IN[name],
            "label": z["label"],
        })

    return {
        "room_width_in": layout["room_width_in"],
        "room_depth_in": layout["room_depth_in"],
        "zones": zones,
    }


if __name__ == "__main__":
    # Chains Stage A -> Stage B -> Stage C for a full end-to-end smoke test.
    from stage_a import run_stage_a
    from stage_b import run_stage_b

    ROOM_WIDTH_FT, ROOM_DEPTH_FT, BUDGET_INR, STYLE = 10, 7, 80000, "Modern"
    CATALOG_PATH = "../data/kohler_catalog.json"

    stage_a_result = run_stage_a(CATALOG_PATH, ROOM_WIDTH_FT, ROOM_DEPTH_FT, BUDGET_INR, STYLE)
    if stage_a_result["status"] != "ok":
        print("Stage A failed:", stage_a_result)
    else:
        top_bundles = stage_a_result["optimization_result"]["top_bundles"]
        stage_b_result = run_stage_b(STYLE, top_bundles)

        if stage_b_result["status"] != "ok":
            print("Stage B failed:", stage_b_result)
        else:
            output_path = run_stage_c(
                CATALOG_PATH, ROOM_WIDTH_FT, ROOM_DEPTH_FT, STYLE,
                stage_b_result["final_bundle"], stage_b_result["total_price"],
            )
            print(f"Floorplan saved to: {output_path}")
            print(f"Rationale: {stage_b_result['rationale']}")
