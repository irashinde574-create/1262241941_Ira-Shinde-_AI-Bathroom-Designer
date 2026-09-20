"""
layouts.py — Layout templates for the Kohler AI Bathroom Designer

Single source of truth for *where* the three floor zones (toilet, vanity,
shower) sit in the room. Stage A (feasibility + which toilets fit), Stage C
(2D SVG) and the 3D scene builder all read from here, so they can never
disagree about the arrangement.

A layout template is just two small functions plus a label:

  1. evaluate_layout()  -> can this arrangement fit the room at all, and how
                           much space is left over for the toilet zone?
  2. plan_zones()       -> the concrete placement of each zone.

WALL-LOCAL COORDINATES
----------------------
Every zone is placed against a wall using two numbers instead of x/y:

    u = distance ALONG the wall, from that wall's start corner
    v = distance OUT from the wall, into the room

so "a zone against a wall" is described the same way whichever wall it is on.
wall_point() converts (u, v) to plan coordinates (x across the room's width,
y down its depth, origin at the back-left corner, back wall at y = 0).

For each wall, u runs left-to-right as seen from INSIDE the room facing that
wall, so a fixture placed at (u, v) always faces into the room:

    back  wall: u starts at the back-left corner,   runs +x
    right wall: u starts at the back-right corner,  runs +y (toward the front)
    front wall: u starts at the front-right corner, runs -x
    left  wall: u starts at the front-left corner,  runs -y

To add a new layout: add an entry to LAYOUTS, an evaluate_ function and a
plan_ function, and register them in _EVALUATORS / _PLANNERS. Nothing in the
renderers needs to change.

All lengths are in inches.
"""

import math

AUTO = "auto"
DEFAULT_LAYOUT_ID = "single_wall"

LAYOUTS = {
    "single_wall": {
        "label": "Single wall",
        "summary": "Toilet, vanity and shower in one row along a single wall.",
    },
    "l_shaped_corner_shower": {
        "label": "L-shaped, corner shower",
        "summary": "Shower in a corner, vanity beside it, toilet on the adjoining wall.",
    },
    "opposite_walls": {
        "label": "Opposite walls",
        "summary": "Toilet and vanity on one wall, shower on the wall across from them.",
    },
}

# Rotation (radians, about the vertical axis) that turns a fixture built
# against the back wall so that it sits against the given wall, facing in.
WALL_ROT_Y = {
    "back": 0.0,
    "front": math.pi,
    "right": -math.pi / 2,
    "left": math.pi / 2,
}


# ---------------------------------------------------------------------------
# Geometry helpers (wall-local <-> plan)
# ---------------------------------------------------------------------------

def wall_point(wall, room_w, room_d, u, v):
    """Wall-local (u along wall, v out from wall) -> plan (x, y)."""
    if wall == "back":
        return (u, v)
    if wall == "front":
        return (room_w - u, room_d - v)
    if wall == "right":
        return (room_w - v, u)
    if wall == "left":
        return (v, room_d - u)
    raise ValueError(f"Unknown wall: {wall}")


def wall_rect(wall, room_w, room_d, u0, u1, v0, v1):
    """Wall-local rectangle -> plan rectangle {x0, y0, x1, y1} (x0<x1, y0<y1)."""
    xa, ya = wall_point(wall, room_w, room_d, u0, v0)
    xb, yb = wall_point(wall, room_w, room_d, u1, v1)
    return {"x0": min(xa, xb), "y0": min(ya, yb), "x1": max(xa, xb), "y1": max(ya, yb)}


# ---------------------------------------------------------------------------
# Template 1: single wall  (toilet | vanity | shower along the back wall)
# ---------------------------------------------------------------------------

def _evaluate_single_wall(room_w, room_d, vanity, shower):
    max_along = room_w - vanity["width"] - shower["width"]
    budget = {"max_width_in": max_along, "max_depth_in": room_d}

    if max_along <= 0:
        reason = (
            "Room is too narrow to fit toilet + vanity + shower zones side by side. "
            f"Vanity needs {vanity['width']}in, shower needs {shower['width']}in width minimum; "
            f"only {room_w}in of wall width available."
        )
        return False, reason, budget
    if vanity["depth"] > room_d or shower["depth"] > room_d:
        need = max(vanity["depth"], shower["depth"])
        reason = (f"Room is too shallow for a single-wall layout: the vanity and shower zones "
                  f"need {need}in of depth (including clearance), but the room is only {room_d}in deep.")
        return False, reason, budget
    return True, None, budget


def _plan_single_wall(room_w, room_d, vanity, shower, toilet):
    u = 0
    zones = {}
    for name, dims in (("toilet", toilet), ("vanity", vanity), ("shower", shower)):
        zones[name] = {"wall": "back", "u0": u, "u1": u + dims["width"], "depth": dims["depth"]}
        u += dims["width"]
    return zones


# ---------------------------------------------------------------------------
# Template 2: L-shaped with corner shower
#   back wall : shower in the back-left corner, vanity next to it
#   right wall: toilet, starting just beyond the vanity's clearance zone
# ---------------------------------------------------------------------------

def _evaluate_l_shaped(room_w, room_d, vanity, shower):
    # The toilet zone runs along the right wall starting at u = vanity depth.
    # It only competes with the shower for x-space if the two overlap in y.
    along = room_d - vanity["depth"]
    depth = (room_w - shower["width"]) if vanity["depth"] < shower["depth"] else room_w
    budget = {"max_width_in": along, "max_depth_in": depth}

    if shower["width"] + vanity["width"] > room_w:
        reason = (
            "Room is too narrow for an L-shaped layout: the shower and vanity sit side by side "
            f"on the back wall and need {shower['width'] + vanity['width']}in, "
            f"but only {room_w}in of wall width is available."
        )
        return False, reason, budget
    if vanity["depth"] > room_d or shower["depth"] > room_d:
        need = max(vanity["depth"], shower["depth"])
        reason = (f"Room is too shallow for an L-shaped layout: the vanity and shower zones "
                  f"need {need}in of depth (including clearance), but the room is only {room_d}in deep.")
        return False, reason, budget
    if along <= 0 or depth <= 0:
        reason = ("Room is too small for an L-shaped layout: there is no wall space left "
                  "for the toilet beyond the vanity and shower zones.")
        return False, reason, budget
    return True, None, budget


def _plan_l_shaped(room_w, room_d, vanity, shower, toilet):
    return {
        "shower": {"wall": "back", "u0": 0, "u1": shower["width"], "depth": shower["depth"]},
        "vanity": {"wall": "back", "u0": shower["width"], "u1": shower["width"] + vanity["width"],
                   "depth": vanity["depth"]},
        "toilet": {"wall": "right", "u0": vanity["depth"], "u1": vanity["depth"] + toilet["width"],
                   "depth": toilet["depth"]},
    }


# ---------------------------------------------------------------------------
# Template 3: opposite walls
#   back wall : toilet | vanity
#   front wall: shower in the front-right corner
# Zones are reserved exclusively (clearance areas are not allowed to overlap),
# which is conservative: it needs the room to be deep enough for both rows.
# ---------------------------------------------------------------------------

def _evaluate_opposite(room_w, room_d, vanity, shower):
    along = room_w - vanity["width"]
    depth = room_d - shower["depth"]
    budget = {"max_width_in": along, "max_depth_in": depth}

    if shower["width"] > room_w or along <= 0:
        reason = (
            "Room is too narrow for an opposite-walls layout: the back wall needs room for "
            f"the toilet plus a {vanity['width']}in vanity, and the front wall needs "
            f"{shower['width']}in for the shower; the room is only {room_w}in wide."
        )
        return False, reason, budget
    if vanity["depth"] > depth or depth <= 0:
        reason = (
            "Room is too shallow for an opposite-walls layout: the two rows of fixtures need "
            f"{vanity['depth'] + shower['depth']}in of depth including clearance, "
            f"but the room is only {room_d}in deep."
        )
        return False, reason, budget
    return True, None, budget


def _plan_opposite(room_w, room_d, vanity, shower, toilet):
    return {
        "toilet": {"wall": "back", "u0": 0, "u1": toilet["width"], "depth": toilet["depth"]},
        "vanity": {"wall": "back", "u0": toilet["width"], "u1": toilet["width"] + vanity["width"],
                   "depth": vanity["depth"]},
        "shower": {"wall": "front", "u0": 0, "u1": shower["width"], "depth": shower["depth"]},
    }


_EVALUATORS = {
    "single_wall": _evaluate_single_wall,
    "l_shaped_corner_shower": _evaluate_l_shaped,
    "opposite_walls": _evaluate_opposite,
}

_PLANNERS = {
    "single_wall": _plan_single_wall,
    "l_shaped_corner_shower": _plan_l_shaped,
    "opposite_walls": _plan_opposite,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_valid_layout_id(layout_id):
    return layout_id in LAYOUTS


def evaluate_layout(layout_id, room_w, room_d, vanity, shower):
    """
    Can this arrangement fit the room, and how much space does the toilet
    zone get?  `vanity` / `shower` are {"width", "depth"} zone sizes including
    clearance. Returns:

        {"feasible": bool, "reason": str | None,
         "toilet_budget": {"max_width_in": <along its wall>,
                           "max_depth_in": <out from its wall>}}
    """
    feasible, reason, budget = _EVALUATORS[layout_id](room_w, room_d, vanity, shower)
    return {"feasible": feasible, "reason": reason, "toilet_budget": budget}


def plan_zones(layout_id, room_w, room_d, vanity, shower, toilet):
    """
    Concrete placement of each zone. `toilet` is {"width", "depth"} of the
    toilet zone incl. clearance. Each returned zone has:
        wall, u0, u1 (along the wall), depth (out from the wall),
        rect (plan-space x0/y0/x1/y1).
    """
    zones = _PLANNERS[layout_id](room_w, room_d, vanity, shower, toilet)
    for z in zones.values():
        z["rect"] = wall_rect(z["wall"], room_w, room_d, z["u0"], z["u1"], 0, z["depth"])
    return zones


def preference_order(room_w, room_d):
    """
    Order in which layouts are tried when the user leaves the choice on
    "auto", based on the room's proportions (width : depth).
    """
    ratio = room_w / room_d
    if ratio >= 1.3:       # long along the fixture wall
        return ["single_wall", "l_shaped_corner_shower", "opposite_walls"]
    if ratio <= 0.85:      # deeper than it is wide
        return ["opposite_walls", "l_shaped_corner_shower", "single_wall"]
    return ["l_shaped_corner_shower", "single_wall", "opposite_walls"]   # roughly square


_AUTO_BLURBS = {
    "single_wall": ("Your room is long compared with its depth, so one row of fixtures "
                    "along a single wall uses the space best."),
    "l_shaped_corner_shower": ("Your room is close to square, so a corner shower with the toilet on "
                               "the adjoining wall uses the depth better than one long row."),
    "opposite_walls": ("Your room is deeper than it is wide, so toilet and vanity on one wall "
                       "with the shower across from them makes use of the depth."),
}


def auto_reason(chosen, order):
    """Customer-facing sentence explaining an automatic layout choice."""
    if chosen == order[0]:
        return _AUTO_BLURBS[chosen]
    return (f"{LAYOUTS[chosen]['label']} is the arrangement that fits this room — the layout "
            f"we'd normally prefer for these proportions doesn't leave enough space.")


def camera_for_layout(layout_id, room_w, room_d, room_h):
    """
    Default 3D camera position/target and which walls to draw translucent,
    chosen so the walls carrying fixtures are seen from the inside.
    Walls listed in `walls` are the ones drawn (the far walls, from the camera).
    """
    dist = max(room_w, room_d) * 1.05
    target = [room_w / 2, room_h / 4, room_d / 2]

    if layout_id == "l_shaped_corner_shower":      # fixtures on back + right walls
        position = [room_w / 2 - dist * 0.65, dist * 0.6, room_d + dist * 0.55]
        walls = ["back", "right"]
    elif layout_id == "opposite_walls":            # fixtures on back + front walls
        position = [room_w / 2 + dist * 0.85, dist * 0.6, room_d / 2 + dist * 0.2]
        walls = ["back", "left"]
    else:                                          # single wall: fixtures on the back wall
        position = [room_w / 2 + dist * 0.65, dist * 0.6, room_d + dist * 0.55]
        walls = ["back", "left"]

    return {"position": position, "target": target, "walls": walls}
