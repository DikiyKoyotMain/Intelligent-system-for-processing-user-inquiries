import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.public_banking import build_bundle


if __name__ == '__main__':
    report = build_bundle(ROOT / 'data/public_banking')
    output = ROOT / 'reports/public_banking_corpus.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ['candidates', 'research_eligible', 'review_due', 'business_approval']}, indent=2))
