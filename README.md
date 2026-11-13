# Support Intelligence Lab

Учебный проект по построению системы обработки обращений службы поддержки: от анализа открытых данных и простых моделей классификации намерений до поиска по базе знаний, RAG и API.

## Текущий этап

**Завершены исследование данных, EDA, подготовка split, classical baseline, подбор настроек Linear SVM, сравнение словесных с символьными n-граммами и эксплуатационные замеры кандидата.** Зафиксирован Linear SVM с word + char_wb TF-IDF; official test сохранён для следующей финальной оценки. Подробности — в `reports/research.md`, `configs/final_model.json` и `experiments/`.

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

Установите зависимости из корня проекта командой `python -m pip install -r requirements.txt`. Откройте `notebooks/01_model_training_and_metrics.ipynb` как Jupyter Notebook и выберите тот же Python-интерпретатор. Запускайте ячейки сверху вниз: ноутбук проверит данные и покажет EDA-графики, подготовит split из `data/raw/`, обучит baseline-модели, сравнит настройки Linear SVM и word/char представления, покажет метрики и ошибки, замерит latency и размер зафиксированного кандидата. Сводки сохраняются в `experiments/`, параметры — в `configs/final_model.json`, прогоны — в MLflow. Official test этим этапом не используется; его оценим отдельно после фиксации кандидата.

## Структура

- `data/raw/` — исходные CSV (игнорируются Git) и `source_manifest.json`.
- `data/processed/` — воспроизводимые train/validation CSV (игнорируются Git).
- `src/data/` — загрузка, аудит и подготовка split.
- `src/models/` — baseline и дальнейшие модели.
- `configs/` — параметры split, baseline и зафиксированного кандидата.
- `experiments/baseline/` — конфигурация, метрики и диагностика ошибок.
- `reports/` — исследование и объяснение результатов.
- `docs/study_guide.docx` — обновляемое учебное пособие.

## Git

Результаты отправляются в `origin/main` по завершении экспериментов. Сырые и производные CSV, модели, среда MLflow и временные файлы исключены из Git; в истории остаются код, конфигурации, сводки и отчёты.
