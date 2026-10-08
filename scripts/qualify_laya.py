"""Small regression corpus; report abstentions separately from correct routes."""
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from laya_worker import Classifier, RECIPES

cases = [
    ('Show the contents of the application error log file.', 'file_read', ['file_read', 'symbols', 'clarify']),
    ('Find the definition of the function calculate_total and show its source.', 'symbols', ['file_read', 'symbols', 'clarify']),
    ('Search JavaScript for syntax matching the AST pattern console.log($A).', 'ast_search', ['file_read', 'symbols', 'ast_search', 'clarify']),
    ('Display the git commit history for this repository.', 'git_report', ['git_report', 'clarify']),
    ('Take a snapshot of the current browser page in the existing session.', 'browser_snapshot', ['browser_snapshot', 'clarify']),
    ('Read this local JSON configuration file exactly.', 'file_read', ['file_read', 'symbols', 'clarify']),
    ('Find matching syntax nodes for the Python pattern print($A).', 'ast_search', ['file_read', 'symbols', 'ast_search', 'clarify']),
]
started = time.monotonic()
classifier = Classifier(Path(sys.argv[1]).resolve())
cold = time.monotonic() - started
rows = []
for intent, expected, eligible in cases:
    result = classifier.predict(intent)
    accepted = result['route'] in eligible and result['route'] != 'clarify' and result['confidence'] >= .80 and not result['truncated']
    rows.append({'expected': expected, 'eligible': eligible, **result, 'accepted': accepted,
                 'correct': result['route'] == expected})
report = {'cases': rows, 'accepted_correct': sum(row['accepted'] and row['correct'] for row in rows),
          'blocked': sum(not row['accepted'] for row in rows),
          'wrong_accepted': sum(row['accepted'] and not row['correct'] for row in rows), 'total': len(rows),
          'model_load_seconds': round(cold, 2), 'median_route_ms': statistics.median(row['elapsed_ms'] for row in rows)}
print(json.dumps(report, indent=2))
if report['wrong_accepted'] or report['accepted_correct'] < 6:
    raise SystemExit(1)
