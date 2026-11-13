# Повторный запуск EDA

1. Установите зависимости: `python -m pip install -r requirements.txt`.
2. Скачайте неизменяемые CSV с официального репозитория PolyAI:

```powershell
Invoke-WebRequest 'https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/train.csv' -OutFile 'data/raw/train.csv'
Invoke-WebRequest 'https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv' -OutFile 'data/raw/test.csv'
```

3. Запустите `python src/data/eda.py`.

Скрипт сначала сверяет SHA-256 с `data/raw/source_manifest.json`, затем проверяет схему и рассчитывает пропуски, распределения классов, длины текстов, повторы и межсплитовые пересечения. Он создаёт `reports/eda_summary.json` и два PNG в `reports/figures/`. Исходные CSV игнорируются Git; в репозитории хранится manifest с происхождением и контрольными суммами.
