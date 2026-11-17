from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def verify():
    output = ROOT / 'work/validation'
    output.mkdir(parents=True, exist_ok=True)
    for name in ['09_public_banking_review.ipynb', '10_banking_calibration.ipynb', '11_local_operations.ipynb']:
        notebook = nbformat.read(ROOT / 'notebooks' / name, as_version=4)
        NotebookClient(notebook, timeout=120, kernel_name='python3', resources={'metadata': {'path': str(ROOT)}}).execute()
        nbformat.write(notebook, output / name)
        print(f'Выполнен {name}')


if __name__ == '__main__':
    verify()
