# Support Intelligence Lab

Учебный проект по построению системы обработки обращений службы поддержки: от анализа открытых данных и простых моделей классификации намерений до поиска по базе знаний, RAG и API.

## Текущий этап

**Этапы 1–3 — исследование, EDA, подготовка split и baseline завершены.** См. `reports/research.md` и `experiments/baseline/`.

## Воспроизведение

Установите зависимости командой `python -m pip install -r requirements.txt`, скачайте исходные BANKING77 CSV согласно `reports/README.md`, затем выполните:

```powershell
python src/data/eda.py
python src/data/prepare_splits.py
python src/models/baseline.py
```

Подготовка split читает тексты official test только для дедупликации train, не использует test метки и оставляет test-файл без изменений. Baseline скрипт работает только с train/validation. Результаты, per-class отчёты и confusion matrices сохраняются в `experiments/baseline/`.

MLflow Tracking сохраняет метаданные запусков в локальную SQLite `mlflow.db`, а артефакты — в `mlruns/` (оба пути исключены из Git). Для UI выполните `mlflow server --backend-store-uri sqlite:///mlflow.db`.

## Интерактивное обучение в PyCharm

Установите зависимости из корня проекта командой `python -m pip install -r requirements.txt`. Откройте `notebooks/01_model_training_and_metrics.ipynb` как Jupyter Notebook и выберите тот же Python-интерпретатор. Запускайте ячейки сверху вниз: ноутбук проверит данные и покажет EDA-графики, подготовит split из `data/raw/`, обучит модели, покажет таблицу метрик и ошибки, сохранит результаты в `experiments/baseline/` и залогирует прогоны в MLflow. Чтобы использовать готовый split без исходных CSV, оставьте существующие файлы в `data/processed/`.

## Структура

- `data/raw/` — исходные CSV (игнорируются Git) и `source_manifest.json`.
- `data/processed/` — воспроизводимые train/validation CSV (игнорируются Git).
- `src/data/` — загрузка, аудит и подготовка split.
- `src/models/` — baseline и дальнейшие модели.
- `experiments/baseline/` — конфигурация, метрики и диагностика ошибок.
- `reports/` — исследование и объяснение результатов.
- `docs/study_guide.docx` — обновляемое учебное пособие.

## Git

Результаты фиксируются логическими этапами и отправляются в `origin/main`. Сырые и производные CSV, модели, среда MLflow и временные файлы исключены из Git; в истории остаются код, конфигурации, сводки и отчёты.
