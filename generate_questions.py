"""Add a chosen number of trivia questions, split automatically across tiers.

Usage:
    python generate_questions.py --total 200
    python generate_questions.py --total 200 --dry-run
    python generate_questions.py --total 50 --reserve my_pool.json
    python generate_questions.py --total 200 --data-dir /path/to/data

You enter one number — the total to add — and the tool splits it across
easy / medium / hard using the same ratio the banks were built with (4:3:3)
and pulls that many fresh questions from the reserve pool
(`data/reserve_questions.json` by default).

A question is only ever added once: anything already present in the banks is
skipped automatically, so running this repeatedly never creates duplicates.
If the reserve can't cover the request, the tool says exactly how many are
left and writes nothing.
"""
import argparse
import json
import os
import sys

from add_questions import FILES, TIERS, append_batch, load_banks, load_input, validate_batch

# Relative weights per tier — 4:3:3 matches the original 80/60/60 split.
WEIGHTS = {'easy': 4, 'medium': 3, 'hard': 3}


def load_reserve(path):
    """Load a reserve pool from a single .json/.py file, or every such file in a directory."""
    if os.path.isdir(path):
        merged = {tier: [] for tier in TIERS}
        files = sorted(
            os.path.join(path, f) for f in os.listdir(path)
            if f.endswith('.json') or f.endswith('.py')
        )
        if not files:
            raise ValueError(f"no .json or .py files in {path}")
        for f in files:
            part = load_input(f)
            for tier in TIERS:
                merged[tier].extend(part.get(tier, []))
        return merged
    return load_input(path)


def split_total(total):
    """Split a total into per-tier counts by weight, largest-remainder style."""
    weight_sum = sum(WEIGHTS.values())
    exact = {t: total * WEIGHTS[t] / weight_sum for t in TIERS}
    counts = {t: int(exact[t]) for t in TIERS}
    leftover = total - sum(counts.values())
    # Hand out the rounding leftovers to whichever tiers are furthest below
    # their exact share (ties go to the earlier tier, i.e. easy first).
    order = sorted(TIERS, key=lambda t: (-(exact[t] - counts[t]), TIERS.index(t)))
    for tier in order[:leftover]:
        counts[tier] += 1
    return counts


def fresh_pool(banks, reserve):
    """Reserve questions that are not already in the banks, per tier."""
    present = {q['question'].strip().lower() for tier in TIERS for q in banks[tier]}
    pool = {}
    for tier in TIERS:
        pool[tier] = []
        for item in reserve.get(tier, []):
            if item.get('question', '').strip().lower() not in present:
                pool[tier].append(item)
    return pool


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--total', type=int, required=True, help='how many questions to add in total')
    parser.add_argument('--reserve', default=os.path.join(here, 'data', 'reserve_questions.json'),
                        help='pool file or directory to draw from (default: data/reserve_questions.json)')
    parser.add_argument('--data-dir', default=os.path.join(here, 'data'),
                        help='question bank directory (default: ./data)')
    parser.add_argument('--dry-run', action='store_true', help='show what would be added; write nothing')
    args = parser.parse_args()

    if args.total < 1:
        print("--total must be at least 1")
        return 1

    banks = load_banks(args.data_dir)
    try:
        reserve = load_reserve(args.reserve)
    except Exception as e:
        print(f"Could not read reserve pool {args.reserve}: {e}")
        return 1

    pool = fresh_pool(banks, reserve)
    wanted = split_total(args.total)

    print(f"Asked for {args.total}: " + ", ".join(f"{tier} {wanted[tier]}" for tier in TIERS))

    shortages = {t: wanted[t] - len(pool[t]) for t in TIERS if wanted[t] > len(pool[t])}
    if shortages:
        print("\nNot enough fresh questions in the reserve:")
        for tier in TIERS:
            print(f"  {tier}: want {wanted[tier]}, {len(pool[tier])} left in reserve")
        print("\nNothing written. Top up the reserve pool and try again.")
        return 1

    selected = {tier: pool[tier][:wanted[tier]] for tier in TIERS}

    problems = validate_batch(banks, selected)
    if problems:
        print("\nREFUSING TO WRITE — problems found:")
        for p in problems:
            print("  -", p)
        return 1

    if args.dry_run:
        print("\nDry run — nothing written. Would add:")
        for tier in TIERS:
            for item in selected[tier]:
                print(f"  [{tier}] {item['question']}")
        _report_leftover(pool, selected)
        return 0

    changed = append_batch(banks, selected, args.data_dir)
    print()
    for tier, (before, after) in changed.items():
        print(f"{FILES[tier]}: {before} -> {after} questions")
    print(f"Total: {sum(after for _, after in changed.values())} questions.")
    _report_leftover(pool, selected)
    return 0


def _report_leftover(pool, selected):
    left = {tier: len(pool[tier]) - len(selected[tier]) for tier in TIERS}
    print("Reserve remaining: " + ", ".join(f"{tier} {left[tier]}" for tier in TIERS))


if __name__ == '__main__':
    sys.exit(main())
