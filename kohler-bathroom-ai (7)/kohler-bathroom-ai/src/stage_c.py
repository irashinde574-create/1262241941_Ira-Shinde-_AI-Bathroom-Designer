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

The arrangement of the three zones (toilet, vanity — the washbasin sits on
top of it — and shower enclosure) comes from the layout template chosen in
Stage A (see layouts.py): single wall, L-shaped with a corner shower, or
opposite walls. Every zone is placed against a wall, and both this floorplan
and the 3D scene derive their coordinates from the same placement, so the
two views always agree with each other and with Stage A's fit checks.
"""

import json
from stage_a import load_catalog, ft_to_in, compute_zone_requirements
from layouts import DEFAULT_LAYOUT_ID, WALL_ROT_Y, plan_zones, wall_point, wall_rect, camera_for_layout

PX_PER_IN = 8       # scale factor: pixels per inch
MARGIN = 60          # margin around the room for labels


def compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle,
                        layout_id=DEFAULT_LAYOUT_ID):
    """
    Computes the placement of each zone (toilet, vanity, shower) for the given
    layout template, plus the actual fixture footprint inside each zone, using
    the same effective-width/depth formulas Stage A used to validate fit.
    Returns everything in inches; conversion to pixels happens at render time.

    Each zone carries its wall, its span along that wall (u0..u1) and depth
    out from it, and `rect` — the same area in plan coordinates.
    """
    rules = catalog["category_spatial_rules"]
    zone_reqs = compute_zone_requirements(catalog, room_width_ft, room_depth_ft, layout_id)

    toilet = final_bundle["toilet"]
    toilet_fp = toilet["footprint_in"]
    toilet_eff_width = toilet_fp["width"] + rules["toilet"]["centerline_to_sidewall_min_in"]
    toilet_eff_depth = toilet_fp["depth"] + toilet["clearance_required_in"]["front_min_in"]

    vanity_zone = zone_reqs["vanity_zone"]   # proxy footprint, no real SKU
    shower_zone = zone_reqs["shower_zone"]   # proxy footprint, no real SKU

    basin = final_bundle["washbasin"]
    basin_fp = basin["footprint_in"]

    room_w, room_d = zone_reqs["room_width_in"], zone_reqs["room_depth_in"]
    placed = plan_zones(layout_id, room_w, room_d, vanity_zone, shower_zone,
                        {"width": toilet_eff_width, "depth": toilet_eff_depth})

    placed["toilet"].update({
        "footprint": toilet_fp, "label": toilet["name"], "price": toilet["price_inr"],
    })
    placed["vanity"].update({
        "footprint": basin_fp, "label": basin["name"], "price": basin["price_inr"],
        "zone_note": "Vanity + basin zone (vanity is a planning allowance; basin shown to scale)",
    })
    placed["shower"].update({
        "footprint": None, "label": "Shower area (space reserved, fixtures TBD)", "price": None,
    })

    return {
        "layout_id": layout_id,
        "room_width_in": room_w,
        "room_depth_in": room_d,
        "zones": placed,
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


def _zone_label(zone, zx, zy, zw, zh, inside_rect=None):
    """
    Product name (wrapped at a word boundary) and price.

    Default placement is just outside the zone on the side facing into the
    room: below a back-wall zone, above a front-wall zone, beside a side-wall
    zone. That is fine when zones sit in a row (single-wall layout), but in
    the L-shaped layout the area beside a zone can belong to another zone, so
    layouts pass `inside_rect` (px x, y, w, h) to centre the label inside the
    zone's own clearance area instead — zones never overlap, so those labels
    can't collide.
    """
    line1, line2 = _wrap_label(zone["label"])
    lines = [(line1, 11, "bold", "#222", 0)]              # (text, size, weight, color, dy)
    if line2:
        lines.append((line2, 11, "bold", "#222", 14))
    if zone["price"]:
        lines.append((f"INR {zone['price']:,}", 10, "normal", "#555", 15))
    block_height = sum(dy for *_, dy in lines)

    wall = zone["wall"]
    if inside_rect is not None:
        rx, ry, rw, rh = inside_rect
        x, anchor, y = rx + rw / 2, "middle", ry + rh / 2 - block_height / 2 + 4
    elif wall == "back":
        x, anchor, y = zx + zw / 2, "middle", zy + zh + 18
    elif wall == "front":
        x, anchor, y = zx + zw / 2, "middle", zy - 8 - block_height
    elif wall == "right":
        x, anchor, y = zx - 8, "end", zy + zh / 2 - block_height / 2 + 4
    else:  # left
        x, anchor, y = zx + zw + 8, "start", zy + zh / 2 - block_height / 2 + 4

    out = []
    for text, size, weight, color, dy in lines:
        y += dy
        out.append(_text(x, y, text, size=size, anchor=anchor, weight=weight, color=color))
    return out


def _clearance_area_px(zone, room_w_in, room_d_in, origin_x, origin_y):
    """
    Pixel rect of the part of a zone in front of its fixture (the clearance
    area), where its label can sit without covering the fixture. For a zone
    with no drawn fixture (the shower) this is the whole zone.
    """
    v0 = zone["footprint"]["depth"] if zone["footprint"] else 0
    a = wall_rect(zone["wall"], room_w_in, room_d_in, zone["u0"], zone["u1"], v0, zone["depth"])
    return (origin_x + a["x0"] * PX_PER_IN, origin_y + a["y0"] * PX_PER_IN,
            (a["x1"] - a["x0"]) * PX_PER_IN, (a["y1"] - a["y0"]) * PX_PER_IN)


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

    room_w_in_ = layout["room_width_in"]
    room_d_in_ = layout["room_depth_in"]

    for zone_name, zone in layout["zones"].items():
        r = zone["rect"]
        zx = origin_x + r["x0"] * PX_PER_IN
        zy = origin_y + r["y0"] * PX_PER_IN
        zw = (r["x1"] - r["x0"]) * PX_PER_IN
        zh = (r["y1"] - r["y0"]) * PX_PER_IN

        # Zone allowance (includes clearance) — light fill, dashed border
        parts.append(_rect(zx, zy, zw, zh, fill=zone_colors[zone_name],
                            stroke=fixture_colors[zone_name], dash="4,3", opacity=0.6))

        # Actual fixture footprint, drawn to scale flush against its wall and
        # centered along it, if known
        if zone["footprint"]:
            fw, fd = zone["footprint"]["width"], zone["footprint"]["depth"]
            u_start = zone["u0"] + (zone["u1"] - zone["u0"] - fw) / 2
            b = wall_rect(zone["wall"], room_w_in_, room_d_in_, u_start, u_start + fw, 0, fd)
            parts.append(_rect(origin_x + b["x0"] * PX_PER_IN, origin_y + b["y0"] * PX_PER_IN,
                                (b["x1"] - b["x0"]) * PX_PER_IN, (b["y1"] - b["y0"]) * PX_PER_IN,
                                fill=fixture_colors[zone_name], stroke="#222", stroke_width=1))

        inside_rect = None
        if layout.get("layout_id", DEFAULT_LAYOUT_ID) != "single_wall":
            inside_rect = _clearance_area_px(zone, room_w_in_, room_d_in_, origin_x, origin_y)
        parts.extend(_zone_label(zone, zx, zy, zw, zh, inside_rect))

    # Leftover open floor space to the right of the last zone (single-wall
    # layout only: the other layouts leave an L-shaped or central open area
    # that is simply the white floor)
    if layout.get("layout_id", DEFAULT_LAYOUT_ID) == "single_wall":
        last_zone = layout["zones"]["shower"]
        used_width_in = last_zone["u1"]
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
                 output_path="bathroom_layout.svg", layout_id=DEFAULT_LAYOUT_ID):
    svg_content = get_floorplan_svg(catalog_path, room_width_ft, room_depth_ft, style, final_bundle,
                                    total_price, layout_id)

    with open(output_path, "w") as f:
        f.write(svg_content)

    return output_path


def get_floorplan_svg(catalog_path, room_width_ft, room_depth_ft, style, final_bundle, total_price,
                      layout_id=DEFAULT_LAYOUT_ID):
    """
    Returns the SVG markup as a string without writing to disk — used by
    the web interface (app.py) to embed the floorplan directly in a page
    response instead of serving a separate file.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle, layout_id)
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


def get_3d_scene_data(catalog_path, room_width_ft, room_depth_ft, final_bundle,
                      layout_id=DEFAULT_LAYOUT_ID):
    """
    Returns a JSON-serializable description of the room and every fixture
    as simple 3D boxes (position + dimensions, in inches), for the
    frontend to render with Three.js. This is a stylized visualization,
    not a CAD-precision model — the floor footprints (toilet, vanity,
    shower zone) are exactly to scale, matching Stage A's real constraint
    math, but fixture heights and small accessories (faucet, showerhead,
    mirror) use reasonable standard placement assumptions documented
    above, since exact mounting heights aren't in the product catalog.

    Every fixture is positioned in wall-local terms (u along its wall, v out
    from it) and then mapped into the room with the same helper the 2D
    floorplan uses. `rot_y` turns a fixture built against the back wall so it
    sits against whichever wall its zone is on, facing into the room. The
    frontend applies it as a rotation about the fixture's own origin corner.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle, layout_id)

    room_width_in = layout["room_width_in"]
    room_depth_in = layout["room_depth_in"]

    def place(zone, u, v, w, d, y, h, **fields):
        x, z = wall_point(zone["wall"], room_width_in, room_depth_in, u, v)
        return {**fields, "x": x, "y": y, "z": z, "w": w, "h": h, "d": d,
                "rot_y": WALL_ROT_Y[zone["wall"]]}

    objects = []

    toilet_zone = layout["zones"]["toilet"]
    toilet_product = final_bundle["toilet"]
    toilet_fp = toilet_product["footprint_in"]
    toilet_height = toilet_product["dimensions_in"].get("height") or 15
    toilet_u = toilet_zone["u0"] + (toilet_zone["u1"] - toilet_zone["u0"] - toilet_fp["width"]) / 2
    objects.append(place(
        toilet_zone, toilet_u, 0, toilet_fp["width"], toilet_fp["depth"], 0, toilet_height,
        name=toilet_product["name"], category="toilet",
        color=CATEGORY_COLORS_3D["toilet"],
        shape_family=classify_shape_family("toilet", toilet_product["name"]),
    ))

    vanity_zone = layout["zones"]["vanity"]
    vanity_width = vanity_zone["u1"] - vanity_zone["u0"]
    # The vanity counter itself (a planning allowance, no real SKU in the catalog)
    objects.append(place(
        vanity_zone, vanity_zone["u0"], 0, vanity_width, 21, 0, VANITY_COUNTER_HEIGHT_IN,
        name="Vanity counter (planning allowance)", category="vanity_counter",
        color=CATEGORY_COLORS_3D["vanity_counter"],
    ))

    basin_product = final_bundle["washbasin"]
    basin_fp = basin_product["footprint_in"]
    basin_height = basin_product["dimensions_in"].get("height") or 6
    basin_u = vanity_zone["u0"] + (vanity_width - basin_fp["width"]) / 2
    objects.append(place(
        vanity_zone, basin_u, 0, basin_fp["width"], basin_fp["depth"],
        VANITY_COUNTER_HEIGHT_IN, basin_height,
        name=basin_product["name"], category="washbasin",
        color=CATEGORY_COLORS_3D["washbasin"],
        shape_family=classify_shape_family("washbasin", basin_product["name"]),
    ))

    faucet_product = final_bundle["bathroom_faucet"]
    objects.append(place(
        vanity_zone, basin_u + basin_fp["width"] / 2 - 1, basin_fp["depth"] - 2, 3, 3,
        FAUCET_MOUNT_HEIGHT_IN, 12,
        name=faucet_product["name"], category="bathroom_faucet",
        color=CATEGORY_COLORS_3D["bathroom_faucet"],
        shape_family=classify_shape_family("bathroom_faucet", faucet_product["name"]),
    ))

    mirror_product = final_bundle["mirror"]
    mirror_width = mirror_product["dimensions_in"]["width"]
    mirror_height = mirror_product["dimensions_in"].get("depth") or 32  # catalog quirk: mirror's vertical extent is stored in "depth"
    mirror_u = vanity_zone["u0"] + (vanity_width - mirror_width) / 2
    objects.append(place(
        vanity_zone, mirror_u, 20.5, mirror_width, 1.5,
        MIRROR_MOUNT_HEIGHT_IN, min(mirror_height, 40),
        name=mirror_product["name"], category="mirror",
        color=CATEGORY_COLORS_3D["mirror"],
        shape_family=classify_shape_family("mirror", mirror_product["name"]),
    ))

    shower_zone = layout["zones"]["shower"]
    shower_width = shower_zone["u1"] - shower_zone["u0"]
    objects.append(place(
        shower_zone, shower_zone["u0"], 0, shower_width, shower_width, 0, SHOWER_ENCLOSURE_HEIGHT_IN,
        name="Shower area (space reserved)", category="shower_zone",
        color=CATEGORY_COLORS_3D["shower_zone"], transparent=True,
    ))

    shower_fixture_product = final_bundle["shower_fixture"]
    objects.append(place(
        shower_zone, shower_zone["u0"] + shower_width / 2 - 4, 4, 8, 8, SHOWERHEAD_MOUNT_HEIGHT_IN, 2,
        name=shower_fixture_product["name"], category="shower_fixture",
        color=CATEGORY_COLORS_3D["shower_fixture"],
        shape_family=classify_shape_family("shower_fixture", shower_fixture_product["name"]),
    ))

    return {
        "layout_id": layout_id,
        "room": {"width_in": room_width_in, "depth_in": room_depth_in, "height_in": ASSUMED_CEILING_HEIGHT_IN},
        "camera": camera_for_layout(layout_id, room_width_in, room_depth_in, ASSUMED_CEILING_HEIGHT_IN),
        "objects": objects,
    }


# Approximate real-world heights (inches) used only for the 3D preview —
# not sourced per-product, since the catalog doesn't track fixture height
# for every category. These are reasonable industry-typical values
# (standard toilet bowl height, vanity counter height, shower enclosure
# height) used purely to make the 3D preview readable, not as precise
# product specs.
ZONE_HEIGHTS_IN = {"toilet": 16, "vanity": 32, "shower": 84}


def get_layout_data(catalog_path, room_width_ft, room_depth_ft, final_bundle,
                    layout_id=DEFAULT_LAYOUT_ID):
    """
    Returns a plain-JSON-serializable description of the room and zone
    geometry, for the browser's 3D preview to build boxes from directly
    without re-deriving any spatial math client-side.
    """
    catalog = load_catalog(catalog_path)
    layout = compute_zone_layout(catalog, room_width_ft, room_depth_ft, final_bundle, layout_id)

    zones = []
    for name, z in layout["zones"].items():
        zones.append({
            "name": name,
            "wall": z["wall"],
            "x0": z["rect"]["x0"], "x1": z["rect"]["x1"],
            "y0": z["rect"]["y0"], "y1": z["rect"]["y1"],
            "depth": z["depth"],
            "height": ZONE_HEIGHTS_IN[name],
            "label": z["label"],
        })

    return {
        "layout_id": layout_id,
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
