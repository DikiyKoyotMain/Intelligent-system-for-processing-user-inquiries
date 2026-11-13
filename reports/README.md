# Повторный запуск анализа и baseline

1. Установите зависимости: `python -m pip install -r requirements.txt`.
2. Скачайте исходные BANKING77 CSV с официального репозитория PolyAI:

```powershell
Invoke-WebRequest 'https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/train.csv' -OutFile 'data/raw/train.csv'
Invoke-WebRequest 'https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/master/banking_data/test.csv' -OutFile 'data/raw/test.csv'
```

3. Выполните команды по порядку:

```powershell
python src/data/eda.py
python src/data/prepare_splits.py
python src/models/baseline.py
```

`eda.py` сверяет SHA-256 с `data/raw/source_manifest.json`, проверяет схему и создаёт EDA сводку/графики. `prepare_splits.py` использует test тексты только для аудита и удаления дубликатов на стороне train; test labels не используются, исходный test-файл не меняется. `baseline.py` читает только подготовленные train и validation части, fit-ит все преобразования внутри Pipeline и оценивает 4 модели на validation.

Конфигурации находятся в `configs/`; сводные метрики, per-class отчёты, confusion matrices и ошибки — в `experiments/baseline/`. MLflow Tracking логирует параметры, метрики и артефакты в локальную SQLite `mlflow.db` и каталог `mlartifacts/`. Эти данные и производные CSV намеренно исключены из Git, чтобы хранить в истории исходный код, конфигурации, manifest и человекочитаемые результаты.
