# Support Intelligence Lab

Учебный проект по построению системы обработки обращений службы поддержки: от анализа открытых данных и простых моделей классификации намерений до поиска по базе знаний, RAG и API.

## Текущий этап

**Завершены исследование данных, EDA, подготовка split, сравнение и финальная оценка модели; добавлен локальный HTTP API классификации и первый lexical retrieval по статьям.** Зафиксирован Linear SVM с word + char_wb TF-IDF; official test оценён один раз и больше не используется для настройки. Качество поиска пока не измерено: в проекте отсутствуют одобренные статьи поддержки. Подробности — в `reports/research.md`, `configs/final_model.json` и `experiments/`.

## Воспроизведение

Установите зависимости командой `python -m pip install -r requirements.txt`, скачайте исходные BANKING77 CSV согласно `reports/README.md`, затем выполните:

```powershell
python src/data/eda.py
python src/data/prepare_splits.py
python src/models/baseline.py
```

Подготовка split читает тексты official test только для дедупликации train, не использует test метки и оставляет test-файл без изменений. Baseline скрипт работает только с train/validation. Результаты, per-class отчёты и confusion matrices сохраняются в `experiments/baseline/`.

MLflow Tracking сохраняет метаданные запусков в локальную SQLite `mlflow.db`, а артефакты — в `mlruns/` (оба пути исключены из Git). Для UI выполните `mlflow server --backend-store-uri sqlite:///mlflow.db`.

## HTTP API классификации

Сначала выполните `notebooks/01_model_training_and_metrics.ipynb` сверху вниз, чтобы обучить и сохранить модель. Финальная ячейка покажет сохранённую оценку official test и не запустит предсказания повторно. Затем установите зависимости командой `python -m pip install -r requirements.txt` и запустите из корня проекта:

```powershell
python -m uvicorn src.api.main:app --reload
```

Интерактивная схема запросов доступна на `http://127.0.0.1:8000/docs`. Для классификации отправьте `POST /v1/classify` с JSON `{"text":"I lost my card"}`. Ответ содержит `intent`, `request_id` и `model_version`. `GET /health/live` проверяет процесс, `GET /health/ready` — доступность модели. Невалидный текст отклоняется с кодом 422; если model artifact не создан или не читается, readiness и классификация возвращают 503.

API не возвращает confidence: используемый Linear SVM не откалиброван в вероятности. Текст запроса не включается в сообщения журнала приложения.

После добавления корпуса статей API загружает индекс один раз при запуске и открывает `POST /v1/knowledge/search`. Тело запроса: `{"text":"card payment reversed","top_k":5,"language":"en"}`. Ответ содержит top-k фрагменты, источник, дату актуальности, язык, `score`/`score_type`, `retrieval_status` и применённый порог. Конфигурация метода, chunking, параметров BM25 и `thresholds_by_language` хранится в `configs/retrieval.json`. После calibration и holdout ноутбук создаёт `work/retrieval_config_candidate.json` с SHA-256 корпуса и разметки; проверьте кандидат и перенесите конфигурацию в `configs/retrieval.json`. API сверяет manifest с текущим корпусом, методом и параметрами. При несовпадении порог отключается и возвращается `calibration_mismatch`. Если порог для языка не настроен, API возвращает `threshold_not_configured`; кандидаты остаются доступны для ручного просмотра. `threshold_passed` означает только, что верхний score выше порога, не гарантию корректности статьи или ответа. Переменная `KNOWLEDGE_RETRIEVER` позволяет временно переопределить ранжировщик; при смене метода калиброванные пороги отключаются. Другой путь к JSONL можно указать через `KNOWLEDGE_ARTICLES_PATH`. `/health/knowledge/ready` отдельно сообщает о готовности индекса и состоянии порога. Если корпуса нет, классификация продолжает работать, а поиск вернёт 503.

Для ручной проверки откройте `notebooks/03_api_search.ipynb` в PyCharm, запустите API в отдельном терминале и выполняйте ячейки сверху вниз. Ноутбук проверит доступность сервиса и базы знаний, затем отправит поисковый запрос и покажет выдержки с источниками. Для просмотра схемы API откройте `http://127.0.0.1:8000/docs`.

## База знаний и поиск статей

Подготовьте одобренный корпус в `data/knowledge/articles.jsonl`: одна статья JSON на строку, с полями `id`, `title`, `content`, `source`, `updated_at`, `language`, `owner`, `license`, `status`. `updated_at` задаётся в формате `YYYY-MM-DD`, `status` должен быть `approved`. Полный контракт и пример описаны в `data/knowledge/README.md`. В проекте пока нет статей: BANKING77 содержит обращения и метки намерений, а не проверенные ответы.

Перед индексацией запустите аудит: `python -m src.rag.audit --input data/knowledge/articles.jsonl --output reports/knowledge_audit.json`. Для интерактивного просмотра откройте `notebooks/04_knowledge_audit.ipynb` в PyCharm. Отчёт показывает сводку по языкам, владельцам, лицензиям, дубликатам и документам, которым нужна ручная проверка актуальности.

`src/rag/retriever.py` проверяет документы, делит текст на фрагменты с перекрытием и ищет их по word TF-IDF. Поиск можно посмотреть из Python после добавления корпуса:

```python
from src.rag.retriever import KnowledgeRetriever

retriever = KnowledgeRetriever.from_jsonl("data/knowledge/articles.jsonl")
hits = retriever.search("card payment reversed", top_k=5)
for hit in hits:
    print(hit.title, hit.source, hit.score, hit.score_type)
```

У обоих ранжировщиков результат содержит `score` и `score_type`: TF-IDF возвращает cosine similarity, BM25 — свой ранжирующий балл. Ни одна оценка не является вероятностью правильного ответа. До построения ответов нужно подготовить отдельный набор запросов с релевантными статьями и измерить Recall@5 и MRR.

Для оценки заведите `data/knowledge/queries_calibration.jsonl` и `data/knowledge/queries_holdout.jsonl` по формату из `data/knowledge/README.md`. Для многоязычного корпуса указывайте в каждой строке `language`: поиск отфильтрует статьи того же языка, а ноутбук покажет метрики по языкам отдельно. Перед расчётом метрик ноутбук проверяет точные дубли между выборками и пересечение `query_group_id` для перефразировок. В ноутбуке `02_retrieval_exploration.ipynb` можно сравнить TF-IDF/BM25 и выбрать отдельные языковые пороги только на calibration; после фиксации решения — один раз вывести метрики по языкам на holdout. До появления экспертной разметки значения не рассчитываются.

Ноутбук также показывает сравнение TF-IDF и BM25, таблицу ошибок answerable calibration-запросов (top-1, первый ранг релевантной статьи и пропущенные ID) и исследование порога abstention. Для выбора порога нужна отдельная калибровочная выборка с answerable и unanswerable запросами; итоговое качество нужно проверять на новом holdout наборе. Численного победителя пока нет, поскольку корпус и разметка ещё не добавлены. После успешной оценки holdout ноутбук сохраняет локальные артефакты запуска в `work/retrieval_runs/`: манифест с версиями и SHA-256, таблицы метрик и calibration ошибок. Каталог `work/` исключён из Git.

## Интерактивное обучение в PyCharm

Установите зависимости из корня проекта командой `python -m pip install -r requirements.txt`. Откройте `notebooks/01_model_training_and_metrics.ipynb` как Jupyter Notebook и выберите тот же Python-интерпретатор. Запускайте ячейки сверху вниз: ноутбук проверит данные и покажет EDA-графики, подготовит split из `data/raw/`, обучит baseline-модели, сравнит настройки Linear SVM и word/char представления, покажет метрики и ошибки, замерит latency, а в последней ячейке покажет сохранённый результат official test без повторного вызова модели. Сводки сохраняются в `experiments/`, параметры — в `configs/final_model.json`, прогоны — в MLflow.

## Структура

- `data/raw/` — исходные CSV (игнорируются Git) и `source_manifest.json`.
- `data/processed/` — воспроизводимые train/validation CSV (игнорируются Git).
- `src/data/` — загрузка, аудит и подготовка split.
- `src/models/` — baseline и дальнейшие модели.
- `src/api/` — HTTP API для intent classification.
- `src/rag/` — подготовка фрагментов и базовый lexical retrieval для одобренных статей.
- `src/rag/audit.py` — валидация статей и отчёт по метаданным, дубликатам и срокам ручного пересмотра.
- `data/knowledge/` — формат и инструкции для корпуса поддержки; сами статьи пока не добавлены.
- `notebooks/03_api_search.ipynb` — ручной вызов поискового HTTP API.
- `notebooks/04_knowledge_audit.ipynb` — интерактивный аудит базы знаний.
- `notebooks/05_retrieval_run_review.ipynb` — просмотр сохранённых запусков и ошибок без повторного обучения или индексирования.
- `configs/` — параметры split, baseline и зафиксированного кандидата.
- `configs/retrieval.json` — выбор ранжировщика, параметры разбиения, BM25 и языковые пороги; исходно пороги не настроены.
- `experiments/baseline/` — конфигурация, метрики и диагностика ошибок.
- `reports/` — исследование и объяснение результатов.
- `docs/study_guide.docx` — обновляемое учебное пособие.

## Git

Результаты отправляются в `origin/main` по завершении экспериментов. Сырые и производные CSV, модели, среда MLflow и временные файлы исключены из Git; в истории остаются код, конфигурации, сводки и отчёты.
