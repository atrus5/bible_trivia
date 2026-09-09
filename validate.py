"""Quick validation of the question banks and app imports."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
total = 0
problems = []
for fname in ['questions_easy.json', 'questions_medium.json', 'questions_hard.json']:
    with open(os.path.join(DATA, fname), encoding='utf-8') as f:
        qs = json.load(f)
    total += len(qs)
    print(f"{fname}: {len(qs)} questions")
    for i, q in enumerate(qs):
        qid = f"{q.get('difficulty')}#{i}"
        if not q.get('question'):
            problems.append(f"{fname}[{i}]: missing question text")
        if not q.get('answer'):
            problems.append(f"{fname}[{i}]: missing answer")
        opts = q.get('options', [])
        if len(opts) != 4:
            problems.append(f"{fname}[{i}]: expected 4 options, got {len(opts)}")
        if q.get('answer') not in opts:
            problems.append(f"{fname}[{i}]: answer not among options -> {q.get('answer')!r}")
        if len(set(opts)) != len(opts):
            problems.append(f"{fname}[{i}]: duplicate options")
        if len(q['question']) > 140:
            problems.append(f"{fname}[{i}]: question text too long ({len(q['question'])} chars)")
        for o in opts:
            if len(o) > 60:
                problems.append(f"{fname}[{i}]: option too long ({len(o)} chars): {o!r}")

# Cross-file duplicate questions
seen = {}
for fname in ['questions_easy.json', 'questions_medium.json', 'questions_hard.json']:
    with open(os.path.join(DATA, fname), encoding='utf-8') as f:
        for i, q in enumerate(json.load(f)):
            key = q['question'].strip().lower()
            if key in seen:
                problems.append(f"duplicate question: {fname}[{i}] == {seen[key]}")
            seen[key] = f"{fname}[{i}]"

print(f"\nTOTAL: {total} questions (target: 200)")
print("PROBLEMS:" if problems else "No problems found. ✅")
for p in problems:
    print("  -", p)

# Import check for the app
try:
    import app  # noqa: F401
    print("app.py imports OK ✅  (loaded", len(app.QUESTIONS), "questions)")
except Exception as e:
    print("app.py import FAILED:", e)
    sys.exit(1)

sys.exit(1 if problems else 0)
