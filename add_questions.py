"""Add new trivia questions to the question banks — reusable merge tool.

Usage:
    python add_questions.py new_batch.json
    python add_questions.py new_batch.py
    python add_questions.py new_batch.json --dry-run
    python add_questions.py new_batch.json --data-dir /path/to/data

Input formats accepted:
  1. A dict keyed by tier:  {"easy": [...], "medium": [...], "hard": [...]}
  2. A flat list; each item must carry a "difficulty" of easy/medium/hard.
  3. A .py file exposing a module-level ``QUESTIONS`` in either of those shapes.

Each question is an object with exactly these keys:
    question, options (4 unique strings), answer (one of the options), reference

The tool refuses to write anything if it finds a duplicate question (against the
existing banks or within the batch), a bad answer, duplicate options, the wrong
number of options, or text over the length limits. Existing files keep their
one-object-per-line format.
"""
import argparse
import importlib.util
import json
import os
import sys

TIERS = ('easy', 'medium', 'hard')
FILES = {t: f'questions_{t}.json' for t in TIERS}
MAX_QUESTION = 140
MAX_OPTION = 60


def load_input(path):
    """Return {tier: [question, ...]} from a .json or .py file."""
    if path.endswith('.py'):
        spec = importlib.util.spec_from_file_location('_new_questions', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = getattr(module, 'QUESTIONS', module)
    else:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

    if isinstance(data, dict):
        normalized = {t: list(data.get(t, [])) for t in TIERS}
        unknown = set(data) - set(TIERS)
        if unknown:
            raise ValueError(f"unknown tier key(s) in input: {sorted(unknown)}")
    elif isinstance(data, list):
        normalized = {t: [] for t in TIERS}
        for item in data:
            tier = str(item.get('difficulty', '')).lower()
            if tier not in TIERS:
                raise ValueError(f"item missing a valid 'difficulty': {item.get('question', item)!r}")
            normalized[tier].append(item)
    else:
        raise ValueError("input must be a dict of tiers or a list of questions")
    return normalized


def load_banks(data_dir):
    banks = {}
    for tier, fname in FILES.items():
        path = os.path.join(data_dir, fname)
        with open(path, encoding='utf-8') as f:
            banks[tier] = json.load(f)
    return banks


def validate_batch(banks, incoming):
    """Return a list of human-readable problems (empty means safe to write)."""
    problems = []
    seen = {}
    for tier in TIERS:
        for i, item in enumerate(banks[tier]):
            seen[item['question'].strip().lower()] = f"{FILES[tier]}[{i}]"

    for tier in TIERS:
        for item in incoming[tier]:
            label = (item.get('question') or '<no question text>')[:48]
            if not item.get('question'):
                problems.append(f"{tier}: missing question text")
                continue
            if not item.get('answer'):
                problems.append(f"{tier}: missing answer -> {label!r}")
            options = item.get('options') or []
            if len(options) != 4:
                problems.append(f"{tier}: expected 4 options, got {len(options)} -> {label!r}")
            if item.get('answer') not in options:
                problems.append(f"{tier}: answer not among options -> {label!r} ({item.get('answer')!r})")
            if len(set(options)) != len(options):
                problems.append(f"{tier}: duplicate options -> {label!r}")
            if len(item['question']) > MAX_QUESTION:
                problems.append(f"{tier}: question too long ({len(item['question'])} chars) -> {label!r}")
            for opt in options:
                if len(opt) > MAX_OPTION:
                    problems.append(f"{tier}: option too long ({len(opt)} chars): {opt!r}")
            key = item['question'].strip().lower()
            if key in seen:
                problems.append(f"{tier}: duplicate question -> {label!r} (also at {seen[key]})")
            seen[key] = f"new {tier}: {label!r}"
    return problems


def append_batch(banks, incoming, data_dir):
    changed = {}
    for tier, fname in FILES.items():
        items = banks[tier] + [dict(difficulty=tier, **item) for item in incoming[tier]]
        lines = ['[']
        for i, item in enumerate(items):
            comma = ',' if i < len(items) - 1 else ''
            lines.append('  ' + json.dumps(item, ensure_ascii=False) + comma)
        lines.append(']')
        with open(os.path.join(data_dir, fname), 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
        changed[tier] = (len(banks[tier]), len(items))
    return changed


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('input', help='.json or .py file with the new questions')
    parser.add_argument('--data-dir', default=os.path.join(here, 'data'),
                        help='question bank directory (default: ./data)')
    parser.add_argument('--dry-run', action='store_true', help='validate only; do not write')
    args = parser.parse_args()

    try:
        incoming = load_input(args.input)
    except Exception as e:
        print(f"Could not read {args.input}: {e}")
        return 1

    banks = load_banks(args.data_dir)
    counts = ', '.join(f"{tier} {len(incoming[tier])}" for tier in TIERS)
    print(f"New questions: {counts}")

    problems = validate_batch(banks, incoming)
    if problems:
        print("\nREFUSING TO WRITE — problems found:")
        for p in problems:
            print("  -", p)
        return 1

    if args.dry_run:
        print("\nNo problems found. ✅  (dry run — nothing written)")
        return 0

    changed = append_batch(banks, incoming, args.data_dir)
    for tier, (before, after) in changed.items():
        print(f"{FILES[tier]}: {before} -> {after} questions")
    total = sum(after for _, after in changed.values())
    print(f"Total: {total} questions. Merged OK.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
