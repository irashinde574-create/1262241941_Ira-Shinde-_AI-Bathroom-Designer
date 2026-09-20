"""
Tests for the layout templates (src/layouts.py) and how Stage A / Stage C use them.

Run from the project root with either:
    python tests/test_layouts.py
    pytest tests/test_layouts.py
"""

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from layouts import LAYOUTS, WALL_ROT_Y, wall_rect  # noqa: E402
from stage_a import (  # noqa: E402
    load_catalog, compute_zone_requirements, filter_by_space, resolve_layout, run_stage_a,
)
from stage_c import compute_zone_layout, get_3d_scene_data, get_floorplan_svg  # noqa: E402

CATALOG_PATH = os.path.join(HERE, "..", "data", "kohler_catalog.json")
CATALOG = load_catalog(CATALOG_PATH)
EPS = 1e-6

ROOM_SIZES_FT = [(w / 2, d / 2) for w in range(10, 33) for d in range(10, 33)]   # 5ft .. 16ft


def _overlap(a, b):
    """True if two plan rects overlap by more than a shared edge."""
    return (min(a["x1"], b["x1"]) - max(a["x0"], b["x0"]) > EPS and
            min(a["y1"], b["y1"]) - max(a["y0"], b["y0"]) > EPS)


def _inside(inner, room_w, room_d):
    return (inner["x0"] >= -EPS and inner["y0"] >= -EPS and
            inner["x1"] <= room_w + EPS and inner["y1"] <= room_d + EPS)


def _contains(outer, inner):
    return (inner["x0"] >= outer["x0"] - EPS and inner["y0"] >= outer["y0"] - EPS and
            inner["x1"] <= outer["x1"] + EPS and inner["y1"] <= outer["y1"] + EPS)


def _base_bundle(w_ft, d_ft, layout_id):
    result = run_stage_a(CATALOG_PATH, w_ft, d_ft, 10_000_000, "Modern", layout=layout_id)
    assert result["status"] == "ok", (w_ft, d_ft, layout_id, result["status"])
    return result["optimization_result"]["top_bundles"][0]["bundle"]


def _valid_toilets(w_ft, d_ft, layout_id):
    zr = compute_zone_requirements(CATALOG, w_ft, d_ft, layout_id)
    if not zr["feasible"]:
        return zr, []
    return zr, filter_by_space(CATALOG, zr)["toilet"]["valid"]


# ---------------------------------------------------------------------------

def test_every_toilet_stage_a_accepts_is_placed_cleanly():
    """
    If Stage A says a toilet fits a layout, Stage C must be able to place all
    three zones inside the room with no two zones overlapping.
    """
    checked = 0
    for layout_id in LAYOUTS:
        for w_ft, d_ft in ROOM_SIZES_FT:
            zr, toilets = _valid_toilets(w_ft, d_ft, layout_id)
            if not toilets:
                continue
            base = _base_bundle(w_ft, d_ft, layout_id)
            for toilet in toilets:
                bundle = dict(base, toilet=toilet)
                layout = compute_zone_layout(CATALOG, w_ft, d_ft, bundle, layout_id)
                rw, rd = layout["room_width_in"], layout["room_depth_in"]
                rects = {name: z["rect"] for name, z in layout["zones"].items()}
                for name, rect in rects.items():
                    assert _inside(rect, rw, rd), (layout_id, w_ft, d_ft, toilet["id"], name, rect)
                names = list(rects)
                for i in range(len(names)):
                    for j in range(i + 1, len(names)):
                        assert not _overlap(rects[names[i]], rects[names[j]]), \
                            (layout_id, w_ft, d_ft, toilet["id"], names[i], names[j])
                checked += 1
    assert checked > 1000, checked


def test_stage_a_toilet_budget_is_tight_for_single_wall_and_l_shaped():
    """
    For these two layouts a toilet Stage A rejects genuinely can't be placed
    (outside the room, or overlapping another zone) — i.e. the budget isn't
    needlessly conservative. (Opposite walls is deliberately conservative:
    it never lets the two rows' clearance areas overlap.)
    """
    rejected_checked = 0
    for layout_id in ("single_wall", "l_shaped_corner_shower"):
        for w_ft, d_ft in ROOM_SIZES_FT[::7]:
            zr = compute_zone_requirements(CATALOG, w_ft, d_ft, layout_id)
            if not zr["feasible"]:
                continue
            valid_ids = {t["id"] for t in filter_by_space(CATALOG, zr)["toilet"]["valid"]}
            base = None
            for toilet in (p for p in CATALOG["products"] if p["category"] == "toilet"):
                if toilet["id"] in valid_ids:
                    continue
                if base is None:
                    # any complete bundle will do, we only vary the toilet
                    base = {c: next(p for p in CATALOG["products"] if p["category"] == c)
                            for c in ("toilet", "washbasin", "bathroom_faucet", "shower_fixture", "mirror")}
                layout = compute_zone_layout(CATALOG, w_ft, d_ft, dict(base, toilet=toilet), layout_id)
                rw, rd = layout["room_width_in"], layout["room_depth_in"]
                rects = {n: z["rect"] for n, z in layout["zones"].items()}
                bad = any(not _inside(r, rw, rd) for r in rects.values()) or \
                    any(_overlap(rects[a], rects[b]) for a, b in
                        (("toilet", "vanity"), ("toilet", "shower"), ("vanity", "shower")))
                assert bad, (layout_id, w_ft, d_ft, toilet["id"])
                rejected_checked += 1
    assert rejected_checked > 20, rejected_checked


def test_single_wall_matches_original_left_to_right_formula():
    layout = compute_zone_layout(CATALOG, 10, 7, _base_bundle(10, 7, "single_wall"), "single_wall")
    z = layout["zones"]
    assert all(zone["wall"] == "back" for zone in z.values())
    assert z["toilet"]["rect"]["x0"] == 0
    assert z["vanity"]["rect"]["x0"] == z["toilet"]["rect"]["x1"]
    assert z["shower"]["rect"]["x0"] == z["vanity"]["rect"]["x1"]


def test_auto_layout_choice():
    expected = {
        (10, 7): "single_wall",                  # long, shallow
        (12, 8): "single_wall",
        (8, 8): "l_shaped_corner_shower",        # square
        (7, 7): "l_shaped_corner_shower",        # too small for a single row
        (8, 10): "opposite_walls",               # deeper than wide
    }
    for (w, d), layout_id in expected.items():
        assert resolve_layout(CATALOG, w, d)["layout_id"] == layout_id, (w, d)


def test_auto_falls_back_to_single_wall_when_nothing_fits():
    chosen = resolve_layout(CATALOG, 5, 5)
    assert chosen["layout_id"] == "single_wall" and chosen["reason"] is None
    result = run_stage_a(CATALOG_PATH, 5, 5, 80000, "Modern")
    assert result["status"] == "room_infeasible"


def test_explicit_layout_is_honoured_and_infeasible_reason_names_the_layout():
    result = run_stage_a(CATALOG_PATH, 8, 8, 80000, "Modern", layout="opposite_walls")
    assert result["layout_id"] == "opposite_walls"
    assert result["status"] == "room_infeasible"
    assert "opposite-walls" in result["reason"]


def test_3d_objects_match_the_2d_plan():
    """
    Each 3D object's floor footprint, after applying its rot_y about its own
    origin corner (how Three.js applies it), must land exactly on the same
    wall-local footprint the 2D floorplan draws.
    """
    def world_footprint(obj):
        c, s = math.cos(obj["rot_y"]), math.sin(obj["rot_y"])
        xs, zs = [], []
        for lx, lz in ((0, 0), (obj["w"], 0), (0, obj["d"]), (obj["w"], obj["d"])):
            xs.append(obj["x"] + lx * c + lz * s)
            zs.append(obj["z"] - lx * s + lz * c)
        return {"x0": min(xs), "x1": max(xs), "y0": min(zs), "y1": max(zs)}

    for w_ft, d_ft, layout_id in [(10, 7, "single_wall"), (8, 8, "l_shaped_corner_shower"),
                                  (7, 7, "l_shaped_corner_shower"), (8, 10, "opposite_walls"),
                                  (12, 12, "opposite_walls"), (12, 12, "l_shaped_corner_shower")]:
        bundle = _base_bundle(w_ft, d_ft, layout_id)
        layout = compute_zone_layout(CATALOG, w_ft, d_ft, bundle, layout_id)
        scene = get_3d_scene_data(CATALOG_PATH, w_ft, d_ft, bundle, layout_id)
        rw, rd = layout["room_width_in"], layout["room_depth_in"]
        objs = {o["category"]: o for o in scene["objects"]}

        for name, cat in (("toilet", "toilet"), ("vanity", "washbasin")):
            zone = layout["zones"][name]
            fw, fd = zone["footprint"]["width"], zone["footprint"]["depth"]
            u = zone["u0"] + (zone["u1"] - zone["u0"] - fw) / 2
            expected = wall_rect(zone["wall"], rw, rd, u, u + fw, 0, fd)
            got = world_footprint(objs[cat])
            assert all(abs(got[k] - expected[k]) < 1e-6 for k in expected), (layout_id, cat, got, expected)
            assert objs[cat]["rot_y"] == WALL_ROT_Y[zone["wall"]]

        for o in scene["objects"]:
            if o["category"] == "mirror":
                continue     # mirror is a wall plate; its d is a thin plate, checked by containment only
            assert _inside(world_footprint(o), rw, rd), (layout_id, o["category"], world_footprint(o))

        shower = layout["zones"]["shower"]["rect"]
        assert _contains(shower, world_footprint(objs["shower_zone"])), (layout_id, "shower_zone")
        assert _contains(layout["zones"]["vanity"]["rect"], world_footprint(objs["vanity_counter"]))


def test_svg_renders_for_every_layout():
    for w_ft, d_ft, layout_id in [(10, 7, "single_wall"), (8, 8, "l_shaped_corner_shower"),
                                  (8, 10, "opposite_walls")]:
        bundle = _base_bundle(w_ft, d_ft, layout_id)
        svg = get_floorplan_svg(CATALOG_PATH, w_ft, d_ft, "Modern", bundle, 1234, layout_id)
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
        assert bundle["toilet"]["name"].split()[0] in svg


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} tests passed")
