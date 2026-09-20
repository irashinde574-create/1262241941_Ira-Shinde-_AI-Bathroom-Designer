"""
run_cli.py

Interactive command-line entry point for Stage A.
Run this file to try the constraint engine with your own inputs.

Usage:
    python src/run_cli.py
"""

import json
from stage_a import run_stage_a

CATALOG_PATH = "../data/kohler_catalog.json"


def main():
    print("=== Kohler AI Bathroom Designer — Stage A (Constraint Engine) ===\n")

    room_width_ft = float(input("Room width in feet (e.g. 10): "))
    room_depth_ft = float(input("Room depth in feet (e.g. 7): "))
    budget_inr = int(input("Budget in INR (e.g. 60000): "))
    style = input("Style preference (Modern / Classic Luxury / Japanese Zen): ").strip()

    print("\nRunning constraint checks and budget optimization...\n")

    result = run_stage_a(CATALOG_PATH, room_width_ft, room_depth_ft, budget_inr, style)

    status = result["status"]

    if status == "room_infeasible":
        print("❌ ROOM TOO SMALL")
        print(result["reason"])
        return

    if status == "no_valid_products":
        print("❌ NO VALID PRODUCTS FOUND")
        print("These categories had zero products that fit the space:")
        print(result["optimization_result"]["empty_categories"])
        return

    opt = result["optimization_result"]

    if status == "over_budget_fallback":
        print("⚠️  BUDGET TOO LOW — showing closest possible bundle instead\n")
        print(opt["message"], "\n")
    else:
        print("✅ BUNDLE FOUND WITHIN BUDGET\n")

    print(f"Total price: INR {opt['total_price']}")
    print("\nSelected products:")
    for category, p in opt["bundle"].items():
        print(f"  [{category}] {p['name']} — INR {p['price_inr']} (quality tier {p['quality_tier']})")

    excluded = {c: v for c, v in result["excluded_products"].items() if v}
    if excluded:
        print("\nExcluded products (failed spatial fit):")
        for cat, items in excluded.items():
            for item in items:
                print(f"  [{cat}] {item['name']}: {item['reason']}")

    print("\nFull shortlist that would be passed to Stage B (LLM reasoning):")
    print(json.dumps(result["shortlist_for_stage_b"], indent=2))


if __name__ == "__main__":
    main()
