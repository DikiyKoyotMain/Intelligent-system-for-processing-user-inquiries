import json


def append_hybrid_guide(doc, root, add_table, add_code_block):
    path = root / 'reports/hybrid_comparison.json'
    if not path.exists():
        return
    report = json.loads(path.read_text(encoding='utf-8'))
    doc.add_page_break()
    doc.add_heading('Гибридный поиск RRF и нейросетевой реранкер', level=1)
    doc.add_paragraph('17 ноября 2026 выполнен отдельный эксперимент с реальными pretrained-моделями на CPU. Вопрос исследования: улучшит ли сочетание lexical и dense retrieval порядок документов, и даст ли дополнительный выигрыш cross-encoder. Использована только демонстрационная calibration-выборка: 24 запроса, из них 16 с ответом и 8 без ответа. Прежний holdout не открывался: он уже использовался раньше и не подходит для нового выбора архитектуры.')
    doc.add_heading('Какую гипотезу проверяем', level=2)
    doc.add_paragraph('BM25 хорошо находит точные совпадения и технические команды. Dense encoder может находить смысловую близость при других формулировках. Объединение должно расширять или улучшать список кандидатов. Cross-encoder совместно читает запрос и документ, поэтому потенциально может точнее их сопоставить. Это три отдельные гипотезы, и ни одна не гарантирует прироста на конкретном корпусе.')
    doc.add_paragraph('Для dense выбран intfloat/multilingual-e5-small, для reranking — cross-encoder/mmarco-mMiniLMv2-L12-H384-v1. Обе модели мультиязычные, что важно для русских и английских статей. Веса не дообучались. Репозитории загружены с зафиксированными revision, trust_remote_code=False; версии torch, sentence-transformers и transformers записаны в артефакте. Модели и кэш находятся в work/hf_cache и не публикуются в Git.')
    add_table(doc, ['Компонент', 'Модель', 'Revision'], [
        (key, report['model_names'][key], report['revisions'][key]) for key in ['dense', 'reranker']])
    doc.add_heading('Dense encoder и подготовка текста', level=2)
    doc.add_paragraph('Документы и запросы преобразуются отдельно в векторы. У E5 используются префиксы passage: для фрагмента и query: для вопроса, включая русский язык. Векторы нормализуются до единичной длины; их скалярное произведение равно cosine similarity. Индекс хранит float32-матрицу фрагментов. Фильтр языка применяется к кандидатам до ранжирования выдачи.')
    doc.add_paragraph('На 16 фрагментах достаточно точного матричного поиска. Векторная база или ANN сейчас добавили бы инфраструктуру без измеримой необходимости. Для большого корпуса можно сравнить FAISS/HNSW или pgvector с точным baseline по Recall и latency. Размер матрицы не включает память весов модели: для нейросетевого поиска именно веса и inference часто оказываются основной статьёй ресурсов.')
    doc.add_heading('Почему складываем ранги через RRF', level=2)
    doc.add_paragraph('Складывать BM25 score и cosine напрямую нельзя без обоснованной нормализации: их шкалы и распределения различаются. RRF использует позиции, поэтому не требует сопоставимости исходных score. Для кандидата d вклад каждой выдачи равен 1/(c + rank(d)); ранги начинаются с единицы. Если кандидата в выдаче нет, вклад этой ветки равен нулю. Здесь c=60, одинаковый вес обеих веток.')
    add_code_block(doc, '''RRF(d) = sum(1 / (60 + rank_i(d)))
rank starts at 1
missing candidate contributes 0''')
    doc.add_paragraph('Пример: кандидат первый в BM25 и второй в dense получает 1/61 + 1/62. Наличие в двух выдачах увеличивает общий вес. Внутри одной ветки дубликат chunk_id учитывается только один раз. При одинаковом итоговом score порядок определяется chunk_id, чтобы результаты были воспроизводимыми. Если один ID относится к разному содержимому, fusion останавливается с ошибкой вместо смешивания источников.')
    doc.add_paragraph('RRF является удобным baseline fusion, но не обязательным единственным способом. После отдельной нормализации и calibration можно сравнить weighted score fusion, weighted RRF или обучаемую модель объединения. Само значение RRF не является вероятностью и плохо характеризует отсутствие ответа: даже нерелевантный кандидат может занимать первое место в обеих ветках.')
    doc.add_heading('Кандидаты и cross encoder', level=2)
    doc.add_paragraph('Каждая ветка берёт 4 фрагмента. Их RRF-объединение содержит до 8 уникальных кандидатов. Для reranking используются первые 6, а пользователю показываются первые 5. Cross-encoder получает пары query/text, вычисляет score для каждой пары и меняет только их порядок. Он не способен добавить статью, отсутствовавшую в candidate pool.')
    doc.add_paragraph('Для модели явно задана Identity activation, поэтому сравниваются исходные logits. Sigmoid изменил бы численную шкалу, но сохранил порядок. Ни logit, ни sigmoid score без отдельной вероятностной калибровки не являются надёжной оценкой правильности ответа. Пороги прежнего BM25 на dense, RRF или reranker не переносятся. Этот эксперимент измеряет ranking; production-калибровка отказов и подключение нового метода к ответам API требуют следующей проверки.')
    doc.add_heading('Как измеряли сравнение', level=2)
    doc.add_paragraph('Параметры candidate_depth=4, candidate_pool=6, c=60 и CPU threads=2 зафиксированы до прогона. Сравниваются BM25, dense, hybrid_rrf и hybrid_reranker на одних и тех же запросах. Recall@5 и MRR@5 считаются по уникальным document_id только на answerable примерах. Top1 accuracy — доля answerable запросов с релевантным первым документом. Unanswerable входят в измерение latency, но не превращаются в ranking positives.')
    doc.add_paragraph('MRR@5 здесь ограничен первыми пятью документами для всех методов. Это отличается от прежней метрики MRR по полной доступной выдаче, поэтому нельзя смешивать столбцы разных отчётов без учёта определения. После одного прогрева выполнен один последовательный проход по 24 calibration-запросам. P50/P95 — ориентир данной машины, не SLO и не доказательство статистически устойчивого различия задержек.')
    add_table(doc, ['Метод', 'Recall@5', 'MRR@5', 'Top1', 'P50 мс', 'P95 мс'], [
        (name, f"{row['recall_at_5']:.4f}", f"{row['mrr_at_5']:.4f}", f"{row['top1_accuracy']:.4f}",
         f"{row['latency_p50_ms']:.2f}", f"{row['latency_p95_ms']:.2f}")
        for name, row in report['metrics'].items()])
    doc.add_paragraph('Результат: BM25 правильно ранжировал top-1 для 14 из 16 answerable запросов; dense и RRF — для 16 из 16; вариант с реранкером — для 15 из 16. У всех Recall@5=1.0, поэтому одна эта метрика скрыла бы регрессию top-1. На таком малом автоматически составленном наборе нельзя заключить, что dense всегда лучше BM25 или что hybrid не нужен на других данных.')
    add_table(doc, ['Метод', 'Язык', 'Top1', 'MRR@5'], [
        (method, language, f"{values['top1_accuracy']:.4f}", f"{values['mrr_at_5']:.4f}")
        for method, row in report['metrics'].items() for language, values in row['languages'].items()])
    doc.add_heading('Разбираем конкретную регрессию', level=2)
    for row in report['reranker_changes']:
        if row['top1_delta'] < 0:
            doc.add_paragraph(f"Запрос: {row['query']}. До reranking: {', '.join(row['before_ids'])}. После: {', '.join(row['after_ids'])}. Правильная tests_ru опустилась с первого на четвёртое место. Вклад этого запроса в MRR изменился с 1 до 1/4, то есть на −0.75; средняя потеря по 16 answerable составляет 0.046875.")
    doc.add_paragraph('Вероятная причина — предметная неоднозначность слова «запустить»: cross-encoder предпочёл инструкцию запуска API инструкции запуска тестов. Это интерпретация одной ошибки, а не доказанная причинная диагностика модели. Нужно смотреть больше независимых примеров, чтобы отделить недостаток модели от особенности обучающего домена, truncation или неполной разметки.')
    doc.add_heading('Вывод и следующий эксперимент', level=2)
    doc.add_paragraph('В этом прогоне реранкер не даёт оснований для автоматического включения: качество top-1 ухудшилось, а медианная задержка выросла примерно в восемь раз относительно RRF. Dense и hybrid равны по ranking-метрикам; правило выбора при равенстве предпочитает более простой вариант, поэтому в отчёте выбран dense. Это выбор исследовательского кандидата по calibration, а не переключение рабочего API.')
    doc.add_paragraph('Дальнейшие гипотезы: добавить реальные сложные запросы и hard negatives; проверить candidate depth при большем числе статей; сравнить другой мультиязычный reranker; исследовать необходимость title/context в документе; откалибровать отказы каждой архитектуры. Гиперпараметры выбираются на calibration. Для независимого вывода потребуется новый экспертный holdout; прежний demo holdout не используется для настройки.')
    doc.add_heading('Код и воспроизведение в PyCharm', level=2)
    doc.add_paragraph('Реализация находится в src/rag/hybrid.py, воспроизводимый эксперимент — scripts/compare_hybrid.py, просмотр таблиц и изменений выдачи — notebooks/07_hybrid_and_reranking.ipynb. Файлы requirements-hybrid.txt устанавливаются отдельно от лёгкого runtime API. Результат и model revisions публикуются в reports/hybrid_comparison.json, веса и локальные per-query артефакты остаются в work.')
    add_code_block(doc, '''python -m venv --system-site-packages work/hybrid_env
work/hybrid_env/Scripts/python.exe -m pip install -r requirements-hybrid.txt
work/hybrid_env/Scripts/python.exe scripts/compare_hybrid.py
python -m unittest discover -s tests -v''')
    doc.add_paragraph('Пройдены 44 автоматических теста: прежний набор и 9 новых проверок fusion/dense/reranking. Новые тесты не требуют torch: в них проверяются контракты с контролируемыми encoder fixtures. Реальный нейросетевой inference проверен отдельным экспериментом с настоящими весами. На Windows отсутствие прав для symlink может увеличить размер кэша, но не меняет формулу поиска.')
    doc.add_heading('Дополнительные вопросы для собеседования', level=2)
    for question, answer in [
        ('Зачем RRF если уже есть BM25 и cosine', 'Их score имеют разные шкалы. RRF объединяет ранги, не пытаясь считать исходные числа сопоставимыми. Цена этого удобства — потеря информации о величине разрыва между соседними score.'),
        ('Обязан ли reranker улучшать результат', 'Нет. Он обучался на другом распределении и может неверно переупорядочить хорошую выдачу. В нашем опыте один русский top-1 опустился на четвёртое место. Поэтому обязательны ablation и сравнение по одинаковым запросам.'),
        ('Почему reranker не исправит пропущенную статью', 'Он работает только с candidate pool. Если релевантного документа нет среди кандидатов, даже идеальная функция reranking не сможет вывести его наверх. Сначала оценивают recall первого этапа, затем качество порядка.'),
        ('Почему нельзя переносить старый порог', 'BM25, cosine, RRF и cross-encoder logits описывают разные функции оценки. Число 3.6 для BM25 не имеет того же смысла для cosine или RRF. Нужна новая calibration с answerable и unanswerable запросами.'),
        ('Что означает равенство dense и hybrid на маленькой выборке', 'Только то, что на данных вопросах выбранные ranking-метрики совпали. Это не доказательство эквивалентности архитектур. Нужно больше независимых и сложных примеров; до этого проще оставить кандидата с меньшей сложностью.')]:
        doc.add_heading(question, level=3)
        doc.add_paragraph(answer)
    doc.add_paragraph('Первичные источники: https://huggingface.co/intfloat/multilingual-e5-small; https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1; https://sbert.net/docs/cross_encoder/usage/usage.html; https://sbert.net/docs/package_reference/sparse_encoder/evaluation.html.')
