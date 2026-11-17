import ast
import hashlib
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check():
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    output_dir = ROOT / 'work' / 'validation'
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'unittest.log').write_text(stream.getvalue(), encoding='utf-8')
    compiled_cells = 0
    for path in (ROOT / 'notebooks').glob('*.ipynb'):
        notebook = json.loads(path.read_text(encoding='utf-8'))
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                ast.parse(''.join(cell['source']), filename=path.name)
                compiled_cells += 1
    summary = dict(created_at=datetime.now(timezone.utc).isoformat(), tests_run=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                   passed=result.wasSuccessful(), notebook_cells_parsed=compiled_cells,
                   source_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                  for folder in ['src', 'tests', 'scripts'] for path in (ROOT / folder).rglob('*.py')})
    (output_dir / 'checks.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(stream.getvalue())
    print(json.dumps({key: value for key, value in summary.items() if key != 'source_sha256'}, indent=2))
    return result.wasSuccessful()


if __name__ == '__main__':
    sys.exit(0 if check() else 1)
