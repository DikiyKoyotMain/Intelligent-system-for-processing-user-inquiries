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


## Артефакты поиска по базе знаний

Ноутбук `notebooks/02_retrieval_exploration.ipynb` после успешных calibration и holdout сохраняет результаты в `work/retrieval_runs/<run_id>/`. `run_manifest.json` фиксирует время UTC, Git revision, версии Python/пакетов, параметры retrieval-конфига, состояние рабочего дерева и SHA-256 его diff, SHA-256 корпуса и файлов разметки, выбранные параметры и итоговые holdout-метрики. Отдельные CSV содержат сравнение методов и языков, calibration-ошибки, сетку BM25, кривые порогов, срезы holdout и операционные замеры index build/search latency/sparse matrix size. В частности `calibration_error_cases.csv` содержит тексты запросов. Поэтому каталог остаётся локальным и игнорируется Git; не пересылайте его без проверки на персональные или внутренние данные. Числа создаются только после запуска ноутбука на настоящем корпусе и разметке.

Для просмотра сохранённых запусков без перестроения индекса откройте `notebooks/05_retrieval_run_review.ipynb`. Он сравнивает calibration-метрики только в группах с одинаковыми SHA-256 корпуса и calibration-файла, показывает holdout для аудита и позволяет открыть локальный CSV ошибок выбранного run_id. Не используйте holdout-числа для выбора победителя. Старые манифесты без списка calibration-метрик отображаются в общей истории, но не попадут в таблицу сравнения методов; операционные метрики также отсутствуют для старых запусков.
