from pathlib import Path
import shutil
import csv
import json
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'study_guide.docx'
TEMP_OUT = ROOT / 'work' / 'study_guide_generated.docx'
FIG = ROOT / 'reports' / 'figures'
BASELINE = ROOT / 'experiments' / 'baseline'
RESULTS = json.loads((BASELINE / 'results.json').read_text(encoding='utf-8'))

def field(paragraph, instr):
    r=paragraph.add_run(); b=OxmlElement('w:fldChar'); b.set(qn('w:fldCharType'),'begin'); r._r.append(b)
    r=paragraph.add_run(); it=OxmlElement('w:instrText'); it.set(qn('xml:space'),'preserve'); it.text=instr; r._r.append(it)
    r=paragraph.add_run(); e=OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'),'end'); r._r.append(e)

def set_cell_shading(cell, color):
    tcPr=cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd'); shd.set(qn('w:fill'), color); tcPr.append(shd)

def add_table(doc, headers, rows):
    table=doc.add_table(rows=1, cols=len(headers)); table.style='Light Shading Accent 1'
    for cell, value in zip(table.rows[0].cells, headers):
        cell.text=value; set_cell_shading(cell, 'DCEEF1')
        for run in cell.paragraphs[0].runs: run.bold=True
    for row in rows:
        cells=table.add_row().cells
        for cell, value in zip(cells,row): cell.text=str(value)
    doc.add_paragraph()
    return table

def add_figure(doc, path, caption, width=5.6):
    p=doc.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(path), width=Inches(width))
    p=doc.add_paragraph(caption); p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    for r in p.runs: r.italic=True; r.font.size=Pt(9); r.font.color.rgb=RGBColor(83,100,116)

def add_code_block(doc, code):
    for line in code.strip('\n').splitlines():
        paragraph=doc.add_paragraph()
        paragraph.paragraph_format.left_indent=Inches(.16)
        paragraph.paragraph_format.space_after=Pt(0)
        paragraph.paragraph_format.keep_together=True
        pPr=paragraph._p.get_or_add_pPr(); shading=OxmlElement('w:shd'); shading.set(qn('w:fill'),'F1F5F8'); pPr.append(shading)
        run=paragraph.add_run(line or ' '); run.font.name='Consolas'; run.font.size=Pt(8)


doc=Document(); sec=doc.sections[0]
sec.top_margin=Inches(.72); sec.bottom_margin=Inches(.72); sec.left_margin=Inches(.82); sec.right_margin=Inches(.82)
update_fields=OxmlElement('w:updateFields'); update_fields.set(qn('w:val'),'true'); doc.settings._element.append(update_fields)
styles=doc.styles; styles['Normal'].font.name='Aptos'; styles['Normal'].font.size=Pt(10); styles['Normal'].font.color.rgb=RGBColor(45,55,68)
for name,size,color in [('Title',25,'153B5B'),('Heading 1',17,'153B5B'),('Heading 2',12,'167D8D')]:
    st=styles[name]; st.font.name='Aptos Display'; st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor.from_string(color)

p=doc.add_paragraph(style='Title'); p.add_run('Исследование и разработка интеллектуальной системы обработки пользовательских обращений с применением ML, NLP и Generative AI')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(10); r=p.add_run('Учебное пособие и журнал экспериментов'); r.bold=True; r.font.size=Pt(13); r.font.color.rgb=RGBColor.from_string('167D8D')
doc.add_paragraph('Проект развивается по этапам: сначала проверяем данные и формулируем задачу, затем обучаем и сравниваем модели, после этого проектируем поиск, генерацию и API. Документ объясняет решения и пополняется реальными результатами по мере работы.')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(14); p.add_run('Классификатор обучен и получил финальные test-метрики; для retrieval готовы код, API и протокол эксперимента, но сквозная оценка ждёт одобренный корпус и экспертную разметку.').bold=True
doc.add_paragraph('Дата обновления: 14 ноября 2026')
doc.add_page_break()

doc.add_heading('Оглавление', level=1); p=doc.add_paragraph(); field(p,'TOC \\o "1-2" \\h \\z \\u')
doc.add_paragraph('В Word выберите оглавление и обновите поле, если номера страниц не обновились автоматически.')
doc.add_heading('Как читать это пособие', level=1)
doc.add_paragraph('Каждый этап объясняет задачу и варианты решения, фиксирует выбранный подход и его причины, затем показывает реализацию, фактические результаты и следующие эксперименты. Для intent classification приведены validation и однократные финальные метрики official test. Для retrieval метрик пока нет: одобренный корпус и размеченные запросы ещё не добавлены.')

doc.add_heading('Карта этапов и текущий статус',level=1)
doc.add_paragraph('Журнал содержит 29 завершённых кодовых и документальных этапов. «Завершён» здесь означает, что реализация и инструкция внесены в репозиторий; это не означает, что все ветви были запущены на пользовательской машине или подтверждены реальными статьями. Для retrieval выполнены статические проверки синтаксиса и структуры, но end-to-end измерений пока нет.')
add_table(doc,['Направление','Статус','Что подтверждает завершение / что осталось'],[
    ('Intent classification','Результаты получены','EDA, split, tuning; Linear SVM word + char_wb: official test Accuracy=0.9010, Macro F1=0.9011. Test не используется для последующей настройки.'),
    ('API классификации','Код реализован','Endpoint и readiness описаны; локальный запуск/HTTP вызов требует проверки в среде PyCharm пользователя.'),
    ('Knowledge retrieval','Workflow реализован, данные отсутствуют','TF-IDF/BM25, оценка, языковые срезы, пороги, holdout, audit утечки, error cases, provenance, run review и замеры добавлены. Реальных retrieval-метрик ещё нет.'),
    ('Сквозная проверка поиска','Ожидает входные данные','Нужны одобренные статьи, экспертные calibration/holdout запросы и ручная проверка источников. После этого выполняются ноутбуки 02 и 03.'),
    ('Внешнее production-развёртывание','Не начато','Отдельно спроектировать auth, rate limit, TLS, мониторинг, резервирование и контролируемое обновление корпуса.')])
doc.add_paragraph('Следующий рабочий шаг зависит от владельца предметных данных: предоставить статьи, разрешённые для поиска, и экспертную разметку вопросов. Библиотека не должна генерировать фиктивные ответы или метрики вместо этих материалов.')

sections=[
('1. Постановка задачи',['Бизнес-проблема и цель','Формализация intent classification','Входы, выходы и критерии успеха']),
('2. Поиск и выбор данных',['Сравнение BANKING77, CLINC150, MASSIVE и Bitext','Источник, лицензия и ограничения','Что этот датасет позволяет и чего не позволяет исследовать']),
('3. Исследовательский анализ данных EDA',['Распределение классов и дисбаланс','Длина запросов','Пропуски, дубликаты и split overlap','Графики и выводы']),
('4. Подготовка данных',['Очистка и нормализация текста','Стратифицированное train / validation / test разбиение','Предотвращение Data Leakage']),
('5. Выбор моделей',['Majority и классические baseline','TF-IDF с Logistic Regression, Linear SVM и Naive Bayes','DistilBERT и BERT','Zero-shot и few-shot']),
('6. Обучение',['Конфигурации и воспроизводимость','Функция потерь и оптимизатор','Переобучение и остановка обучения']),
('7. Оценка качества',['Accuracy, Precision, Recall и F1','Macro F1 и Weighted F1','Confusion Matrix и анализ ошибок','Скорость, память и размер модели']),
('8. Улучшение модели',['Гипотезы и журнал экспериментов','Гиперпараметры и TF-IDF','Class weights, предобработка и длина текста','Fine-tuning и сравнение до/после']),
('9. Итоговый выбор модели',['Сравнительная таблица','Компромисс качества, задержки и ресурсов','Ограничения и применимость']),
('10. Практическое применение',['Архитектура FastAPI','Retrieval, RAG и reranking','Разрешённые инструменты агента','Docker, MLflow и мониторинг']),
('11. Подготовка к собеседованию',['Вопросы и ответы по ML/NLP','Метрики, утечки и валидация','Transformers, fine-tuning и эксплуатация']),
('12. Глоссарий',['Термины ML, NLP и Generative AI'])]

for title,subs in sections:
    doc.add_heading(title,level=1)
    if title.startswith('1.'):
        doc.add_paragraph('Первая ML-задача — определить по тексту запроса одну из 77 меток намерения BANKING77. Это не то же самое, что оценка срочности. Основной критерий сравнения — Macro F1 на validation; официальный test останется для финальной оценки.')
    elif title.startswith('2.'):
        doc.add_paragraph('Для первого benchmark выбран BANKING77: 13 083 английских запроса по 77 банковским намерениям. Он подходит для сравнения классификаторов, но не содержит меток приоритета, статей базы знаний, истории диалогов или эталонных ответов.')
    elif title.startswith('3.'):
        doc.add_paragraph('EDA выполнен на загруженных CSV PolyAI. В train 10 003 строки, в test 3 080; оба split содержат 77 классов и не имеют пропусков. У train частота классов варьирует от 35 до 187 примеров. Test сбалансирован: ровно 40 примеров на класс.')
        doc.add_heading('Распределение классов',level=2)
        doc.add_paragraph('Частоты train заметно различаются: отношение максимума к минимуму — около 5,3. Macro F1 нужен, чтобы редкие классы не исчезли за усреднением по частым. На равномерном test Macro F1 и Weighted F1 совпадут, так как support классов равен; это свойство разбиения, а не метрик в целом.')
        add_figure(doc,FIG/'banking77_train_intent_counts.png','Рисунок 1. Число примеров каждого intent в обучающей выборке; классы отсортированы по частоте.',5.35)
        doc.add_heading('Длина запросов',level=2)
        doc.add_paragraph('В train медиана длины — 47 символов, 75-й процентиль — 64, 95-й — около 152, максимум — 433. Распределение имеет длинный правый хвост. До выбора длины последовательности для Transformer измерим длину в токенах конкретного токенизатора.')
        add_figure(doc,FIG/'banking77_train_length_histogram.png','Рисунок 2. Распределение длины запросов train в символах.',5.8)
        doc.add_heading('Пропуски, повторы и split overlap',level=2)
        add_table(doc,['Проверка','Train','Test'],[
            ('Пропуски в text/category','0','0'),
            ('Точные дубли внутри split','0 строк','0 строк'),
            ('Повторы после casefold и схлопывания пробелов','8 строк / 4 ключа','2 строки / 1 ключ'),
            ('Совпадения между split после нормализации','7 ключей (7 строк)','7 ключей (7 строк)'),
            ('Конфликты меток у совпадений','0','0')])
        doc.add_paragraph('Нормализация использовалась только для аудита, исходные тексты не менялись. При подготовке split из train удалили 4 внутренних повтора и 7 строк, совпавших с official test по ключу. Test оставлен без изменений. Проверка семантически близких, но не идентичных запросов — отдельная задача.')
    elif title.startswith('4.'):
        doc.add_paragraph('После дедупликации осталось 9 992 строки. Стратифицированное разбиение с random_state=42 и долей validation 20% дало 7 993 train и 1 999 validation. В каждом классе есть 28–149 train-примеров и 7–38 validation-примеров.')
        doc.add_paragraph('Стратификация сохраняет примеры всех намерений в обеих частях. Vectorizer обучается внутри sklearn Pipeline только на train; validation участвует лишь в сравнении моделей. Официальный test использовался только по тексту для аудита дубликатов, но его метки и оценки не использовались.')
        add_table(doc,['Данные','Строки','Роль'],[
            ('Train после дедупликации','9 992','Источник stratified split'),
            ('Train fit','7 993','Fit TF-IDF и классификатора'),
            ('Validation','1 999','Сравнение моделей и эксперименты'),
            ('Official test','3 080','Оставлен для финальной оценки')])
    elif title.startswith('5.'):
        doc.add_paragraph('Сначала сравнили Majority, TF-IDF + Logistic Regression, TF-IDF + Linear SVM и TF-IDF + Multinomial Naive Bayes. У TF-IDF одинаковые word n-граммы 1–2, lowercase=true, min_df=1, sublinear_tf=true, без stop-word фильтра; class_weight не включён. Векторизатор обучается только на train.')
        ordered=RESULTS['models']
        quality_rows=[(r['model'],f"{r['accuracy']*100:.2f}%",f"{r['macro_precision']:.4f}",f"{r['macro_recall']:.4f}",f"{r['macro_f1']:.4f}") for r in ordered]
        add_table(doc,['Модель','Accuracy','Macro P','Macro R','Macro F1'],quality_rows)
        weighted_rows=[(r['model'],f"{r['weighted_precision']:.4f}",f"{r['weighted_recall']:.4f}",f"{r['weighted_f1']:.4f}") for r in ordered]
        add_table(doc,['Модель','Weighted P','Weighted R','Weighted F1'],weighted_rows)
        performance_rows=[(r['model'],f"{r['fit_seconds']:.2f}",f"{r['single_query_latency_p50_ms']:.2f} / {r['single_query_latency_p95_ms']:.2f}",f"{r['serialized_model_kb']/1024:.2f} MB") for r in ordered]
        add_table(doc,['Модель','Fit, сек','Одиночный запрос P50 / P95, мс','Размер joblib'],performance_rows)
        doc.add_paragraph('Linear SVM лидирует на этой validation с Macro F1 0.8795. Подбор параметров и class weights описан в разделе улучшения модели; Transformer ещё не сравнивался.')
        doc.add_heading('Как работают baseline-модели',level=2)
        doc.add_paragraph('Majority задаёт нижнюю контрольную планку. Logistic Regression обучает линейный multiclass классификатор с log-loss. Linear SVM разделяет классы с большим зазором и использует squared hinge loss. Multinomial Naive Bayes оценивает классы через условные частоты слов с alpha-сглаживанием. TF-IDF уменьшает вес частых слов и повышает вес информативных для документа терминов.')
        doc.add_heading('Следующее сравнение',level=2)
        doc.add_paragraph('Следующий эксперимент сравнит новые представления текста и Transformer на том же split. Official test откроем после фиксации выбора модели.')
    elif title.startswith('6.'):
        doc.add_paragraph('Параметры зафиксированы в configs/baseline.json. Logistic Regression: C=1, max_iter=2000. Linear SVM: C=1 и squared hinge по умолчанию. MultinomialNB: alpha=1. Используется собственная функция потерь или правдоподобия каждого алгоритма; общей функции потерь у этих baseline нет.')
        doc.add_paragraph('Повторяемость обеспечивают фиксированный split seed=42, источник с SHA-256, конфигурация и версии библиотек. MLflow записывает параметры, validation-метрики, per-class отчёты, матрицы ошибок и сериализованные pipeline. Метаданные хранятся в локальной SQLite, артефакты — в mlruns/; оба пути исключены из Git.')
    elif title.startswith('7.'):
        best=RESULTS['models'][0]
        doc.add_paragraph(f"На validation из {RESULTS['validation_rows']} обращений Linear SVM получил Accuracy {best['accuracy']:.4f}, Macro F1 {best['macro_f1']:.4f} и Weighted F1 {best['weighted_f1']:.4f}. Macro F1 — простое среднее F1 по 77 классам; Weighted F1 взвешивает классы по support. Эти средние близки, но метрики не взаимозаменяемы.")
        doc.add_paragraph('Формулы: Accuracy = число верных предсказаний / N; Precision = TP / (TP + FP); Recall = TP / (TP + FN); F1 = 2 × Precision × Recall / (Precision + Recall). Для multiclass Macro F1 = среднее F1 по K классам; Weighted F1 = сумма (support класса × F1 класса) / N. Аналогично строятся macro и weighted Precision/Recall.')
        doc.add_paragraph('Accuracy — доля верных ответов. Precision отвечает, насколько точны предсказания класса; Recall — какую долю реальных примеров класса нашли. Macro усредняет классы поровну, Weighted учитывает support. Поэтому Macro важен при разном числе примеров, а Weighted отражает среднее по этому split. Общая Accuracy не показывает источник ошибок, поэтому дополнительно анализируем confusion matrix и метрики по классам.')
        doc.add_paragraph('ROC-AUC сейчас не считаем: выбранная задача — многоклассовое назначение одного intent, а текущий LinearSVC возвращает margin scores, не откалиброванные вероятности. При необходимости можно отдельно исследовать one-vs-rest ROC-AUC как ranking metric.')
        add_figure(doc,BASELINE/'tfidf_linear_svm_confusion_matrix.png','Рисунок 3. Confusion matrix Linear SVM на validation. Диагональ — верные предсказания; off-diagonal клетки — ошибки. Порядок классов и названия — в CSV матрице.',5.8)
        with (BASELINE/'top_confusions.csv').open(encoding='utf-8') as f:
            confusions=list(csv.DictReader(f))[:5]
        add_table(doc,['Истинный класс','Предсказан','Ошибок'],[(r['true_category'],r['predicted_category'],r['count']) for r in confusions])
        with (BASELINE/'tfidf_linear_svm_classification_report.csv').open(encoding='utf-8') as f:
            report=list(csv.DictReader(f))
        classes=[r for r in report if r.get('label') not in {'accuracy','macro avg','weighted avg'}]
        classes.sort(key=lambda r:float(r['f1-score']))
        add_table(doc,['Класс с наименьшим F1','Support','F1'],[(r['label'],r['support'],f"{float(r['f1-score']):.3f}") for r in classes[:5]])
        doc.add_paragraph('Самый трудный класс в этом прогоне — pending_transfer (F1=0.704, 30 validation-примеров). Частые путаницы: top_up_failed → pending_top_up и disposable_card_limits → get_disposable_virtual_card. Решение пока одно на запрос; вероятности не калибровались.')
        doc.add_paragraph('Время fit и одиночного predict измерено локально, без HTTP overhead. Размер joblib — размер сериализованного pipeline, а не RAM. Пиковую память в этом прогоне не измеряли.')
    elif title.startswith('8.'):
        tuning_path=BASELINE/'linear_svm_tuning_results.csv'
        with tuning_path.open(encoding='utf-8') as f:
            tuning=list(csv.DictReader(f))
        tuning.sort(key=lambda r:float(r['macro_f1']),reverse=True)
        doc.add_paragraph('На одном и том же stratified split сравнили 18 вариантов Linear SVM: word n-граммы 1–1, 1–2 или 1–3; C=0.5, 1 или 2; class_weight=None или balanced. Macro F1 на validation использовали как основной критерий. Official test не участвовал в подборе.')
        top_rows=[(r['tfidf_ngram_range'],r['C'],'Нет' if r['class_weight']=='none' else 'Balanced',f"{float(r['accuracy']):.4f}",f"{float(r['macro_f1']):.4f}") for r in tuning[:5]]
        add_table(doc,['Word n-граммы','C','Веса классов','Accuracy','Macro F1'],top_rows)
        best=tuning[0]
        doc.add_paragraph(f"Лучший вариант — n-граммы {best['tfidf_ngram_range']}, C={best['C']}, без весов классов: Macro F1 {float(best['macro_f1']):.4f}, Accuracy {float(best['accuracy']):.4f}. Он совпал с исходной конфигурацией. C=2 дал Macro F1 0.8793; word триграммы снизили максимум до 0.8653. Ни одна из 18 настроек не улучшила baseline.")
        comparison_path=BASELINE/'word_char_comparison.csv'
        with comparison_path.open(encoding='utf-8') as f:
            comparison=list(csv.DictReader(f))
        doc.add_heading('Сравнение словесных и символьных признаков',level=2)
        comparison_rows=[(r['feature_representation'],r['C'],f"{float(r['accuracy']):.4f}",f"{float(r['macro_f1']):.4f}",f"{float(r['fit_seconds']):.2f}") for r in comparison]
        add_table(doc,['Представление','C','Accuracy','Macro F1','Fit, сек'],comparison_rows)
        candidate=comparison[0]
        baseline=next(r for r in comparison if r['model']=='tfidf_linear_svm')
        delta=float(candidate['macro_f1'])-float(baseline['macro_f1'])
        doc.add_paragraph(f"Word TF-IDF (1–2) вместе с символьными char_wb n-граммами (3–5), C={candidate['C']}, дал Macro F1 {float(candidate['macro_f1']):.4f}. Прирост относительно word baseline составил {delta:.4f}. Fit занял {float(candidate['fit_seconds']):.2f} сек вместо {float(baseline['fit_seconds']):.2f} сек; inference latency и память ещё нужно измерить.")
        doc.add_paragraph('Кандидат — объединение word и char_wb признаков. После фиксации конфигурации измерили размер и задержку, затем один раз посчитали метрики на official test. Этот набор не использовался для настройки модели.')
    elif title.startswith('9.'):
        doc.add_paragraph('Кандидат и его параметры зафиксированы в configs/final_model.json после сравнения качества на validation. После фиксации конфигурации один раз оценили её на official test. Эти метрики являются финальным отчётом и не используются для перенастройки модели.')
        operational_path=ROOT/'experiments'/'final_model'/'operational_metrics.json'
        if operational_path.exists():
            operational=json.loads(operational_path.read_text(encoding='utf-8'))
            add_table(doc,['Замер','Результат','Условия'],[
                ('Validation Macro F1',f"{operational['validation_macro_f1']:.4f}",'1 999 validation-запросов'),
                ('Fit',f"{operational['fit_seconds_single_run']:.2f} сек",'Один прогон'),
                ('Одиночный predict P50 / P95',f"{operational['single_query_latency_p50_ms']:.2f} / {operational['single_query_latency_p95_ms']:.2f} мс",'200 запросов × 10 повторов, после 32 warmup'),
                ('Пакетный predict',f"{operational['batch_validation_seconds_median']:.3f} сек",'Медиана пяти прогонов по validation'),
                ('Размер pipeline',f"{operational['serialized_model_mb']:.2f} MiB",'Joblib сериализация; RAM отдельно не измерялась')])
            doc.add_paragraph('Одиночный predict измеряет estimator без HTTP/API overhead. Скорость и размер зависят от компьютера и версий библиотек; они являются локальными замерами, а не гарантией production SLA.')
        test_metrics_path=ROOT/'experiments'/'final_model'/'test_metrics.json'
        if test_metrics_path.exists():
            test_metrics=json.loads(test_metrics_path.read_text(encoding='utf-8'))
            validation_metrics=json.loads(operational_path.read_text(encoding='utf-8'))
            add_table(doc,['Выборка','Строки','Accuracy','Macro Precision','Macro Recall','Macro F1','Weighted F1'],[
                ('Validation',validation_metrics['validation_rows'],f"{validation_metrics['validation_accuracy']:.4f}",f"{validation_metrics['validation_macro_precision']:.4f}",f"{validation_metrics['validation_macro_recall']:.4f}",f"{validation_metrics['validation_macro_f1']:.4f}",f"{validation_metrics['validation_weighted_f1']:.4f}"),
                ('Official test',test_metrics['test_rows'],f"{test_metrics['accuracy']:.4f}",f"{test_metrics['macro_precision']:.4f}",f"{test_metrics['macro_recall']:.4f}",f"{test_metrics['macro_f1']:.4f}",f"{test_metrics['weighted_f1']:.4f}")])
            doc.add_paragraph('Official test содержит по 40 запросов на каждый из 77 классов, поэтому support одинаковый и macro/weighted агрегаты совпадают или почти совпадают. Accuracy составила 0.9010, Macro F1 — 0.9011. Разница с validation небольшая; модель и параметры после просмотра test не менялись.')
            add_figure(doc,ROOT/'experiments'/'final_model'/'confusion_matrix.png','Итоговая матрица ошибок кандидата на official test. Результаты используются для отчёта, а не для повторного подбора.',5.8)
            confusion_path=ROOT/'experiments'/'final_model'/'confusion_matrix.csv'
            errors=[]
            with confusion_path.open(encoding='utf-8',newline='') as f:
                reader=csv.DictReader(f)
                predicted_labels=[name for name in reader.fieldnames if name!='true_label']
                for row in reader:
                    true_label=row['true_label']
                    for predicted_label in predicted_labels:
                        count=int(row[predicted_label])
                        if true_label!=predicted_label and count>0:
                            errors.append((count,true_label,predicted_label))
            errors.sort(reverse=True)
            add_table(doc,['Истинный класс','Предсказанный класс','Ошибок'],[(a,b,c) for c,a,b in errors[:5]])
        add_table(doc,['Действие','Проверка','Результат'],[
            ('Зафиксировать кандидата','word + char_wb TF-IDF, Linear SVM, C=2','Конфигурация без дальнейшего подбора на test'),
            ('Оценить official test один раз','Accuracy, Macro/Weighted Precision, Recall и F1','Выполнено, без повторной настройки'),
            ('Сохранить решение','Модель, параметры, метрики, ограничения','Кандидат готов к реализации сервиса')])
    elif title.startswith('10.'):
        doc.add_paragraph('Классификационный HTTP API реализован в src/api/main.py на FastAPI. Приложение загружает joblib pipeline один раз в lifespan и повторно использует его между запросами. Путь задаётся configs/final_model.json; переменная INTENT_MODEL_PATH позволяет переопределить локальный путь к артефакту. /health/live проверяет процесс, /health/ready отдельно сообщает, доступна ли модель.')
        doc.add_paragraph('POST /v1/classify принимает JSON с текстом от 1 до 2 000 символов, удаляет крайние пробелы и запрещает неизвестные поля. FastAPI/Pydantic возвращает 422 для некорректного запроса. Успешный ответ содержит intent, request_id и model_version. Confidence не возвращаем: Linear SVM выдаёт неоткалиброванные decision scores, которые нельзя выдавать за вероятности. Сырой текст обращения не записывается в сообщения журнала приложения.')
        add_table(doc,['Маршрут','Назначение','Поведение при ошибке'],[
            ('GET /health/live','Проверить, что процесс API запущен','Не требует загруженной модели'),
            ('GET /health/ready','Проверить готовность модели','503, если артефакт отсутствует или не загрузился'),
            ('POST /v1/classify','Вернуть intent для одного текста','422 для некорректного тела; 503 без модели; 500 при ошибке предсказания'),
            ('GET /health/knowledge/ready','Проверить состояние поискового индекса','503, если корпус отсутствует или не загружается'),
            ('POST /v1/knowledge/search','Вернуть top-k статей и фрагментов с источниками','422 для некорректного тела; 503 без индекса; 500 при ошибке поиска')])
        doc.add_paragraph('Пример тела запроса: {"text":"I lost my card"}. Ответ содержит текстовую метку intent, случайный request_id для связи с журналами и версию модели. Swagger/OpenAPI доступен через /docs. Сейчас это локальный учебный API: аутентификация, rate limiting, TLS termination, метрики сервера и мониторинг качества не добавлены; перед внешним размещением эти компоненты нужно спроектировать отдельно.')
        doc.add_heading('Endpoint поиска по базе знаний',level=2)
        doc.add_paragraph('POST /v1/knowledge/search принимает text, top_k (от 1 до 10) и необязательный language. Ответ возвращает заголовок и текст каждого найденного фрагмента, document_id/chunk_id, source, updated_at, language, score, score_type, retrieval_status и порог, если он задан для языка. Такой контракт позволяет проверить результат и перейти к первоисточнику. Endpoint не пишет текст вопроса в application logs, не формирует ответ клиенту и не интерпретирует сырой score как confidence.')
        add_code_block(doc,'''{
  "text": "card payment reversed",
  "top_k": 5,
  "language": "en"
}''')
        doc.add_paragraph('Индекс создаётся один раз при старте приложения. configs/retrieval.json хранит method, chunking, параметры BM25, thresholds_by_language и calibration_manifest. По умолчанию method=tfidf, threshold map пустая, selection_status=baseline_uncalibrated, manifest равен null. API отвечает retrieval_status=threshold_not_configured и возвращает выдачу для ручного просмотра. После калибровки ноутбук notebooks/02_retrieval_exploration.ipynb создаёт локальный work/retrieval_config_candidate.json только после расчёта holdout. В manifest входят SHA-256 корпуса и файла calibration-разметки, выбранные method, chunking и параметры BM25; также сохраняется хеш holdout для аудита. Кандидат вручную проверяют и переносят в configs/retrieval.json, сам документ с запросами в Git не попадает.')
        doc.add_paragraph('При запуске API вычисляет SHA-256 текущего корпуса и сверяет его, выбранный ранжировщик, chunking и параметры BM25 с manifest. Если статьи или настройки изменились, порог отключается, поиск продолжает выдавать кандидатов, а retrieval_status становится calibration_mismatch. Такой же статус возникает при переопределении ранжировщика через KNOWLEDGE_RETRIEVER. GET /health/knowledge/ready показывает threshold_status отдельно от готовности индекса. Это предотвращает случайное применение старого порога, но не подтверждает качество самого порога: для новой версии корпуса и конфигурации нужна повторная calibration и независимый holdout. KNOWLEDGE_ARTICLES_PATH задаёт путь к JSONL корпусу. Отсутствие статей не выключает intent classification: readiness и поиск вернут 503, пока индекс недоступен. При обновлении статей требуется перезапуск, поскольку индекс хранится в памяти.')
        add_code_block(doc,'''"calibration_manifest": {
  "corpus_sha256": "<64 шестнадцатеричных символа>",
  "calibration_queries_sha256": "<64 шестнадцатеричных символа>",
  "holdout_queries_sha256": "<64 шестнадцатеричных символа>",
  "method": "tfidf",
  "chunking": {"max_chars": 900, "overlap_chars": 120},
  "bm25": {"k1": 1.5, "b": 0.75}
}''')
        doc.add_paragraph('Статус threshold_passed означает только, что top-1 score выше настроенного порога; threshold_not_met — ниже порога; threshold_not_configured — порога для выбранного метода и языка нет; no_candidates — поиск не нашёл кандидатов для языкового фильтра; calibration_mismatch — manifest не соответствует корпусу или настройкам, поэтому порог не применяется. Найденные фрагменты остаются в выдаче для проверки человеком. Ни один статус не гарантирует правильность инструкции или безопасную генерацию клиентского ответа.')
        doc.add_paragraph('HTTP smoke проверка поиска ещё не выполнена: одобренный корпус отсутствует. До подключения корпуса endpoint можно увидеть в /docs, но полезных результатов он не вернёт. Проверку HTTP контракта и корректности результатов нужно провести после добавления статей.')
        doc.add_paragraph('Для самостоятельной проверки подготовлен notebooks/03_api_search.ipynb. Запустите uvicorn в отдельном терминале PyCharm, откройте ноутбук в том же проекте и выполняйте ячейки сверху вниз. Сначала он проверяет /health/live и /health/knowledge/ready, затем отправляет JSON POST запрос стандартной библиотекой urllib и выводит поля ответа. Если сервис не запущен, будет показана подсказка; если корпус ещё отсутствует, endpoint ожидаемо вернёт 503. Запуск сервера/API не считается проверенным до фактического вызова на машине разработчика.')
        doc.add_paragraph('В том же ноутбуке добавлено измерение полного HTTP round-trip: readiness, до 100 calibration-запросов, три прогревочных обращения, два повтора каждого запроса, P50/P95/mean для HTTP 200 и распределение статусов. Таймер охватывает клиентскую отправку, серверный поиск и получение сериализованных JSON-байтов; разбор JSON клиентом не входит. Сохраняются только короткий query hash, статус и latency в work/api_runs; тексты запросов и тела ответов не сохраняются. Это последовательный локальный ориентир, не нагрузочный тест и не SLO; результат зависит от компьютера и фоновой нагрузки.')
        doc.add_heading('Первый слой поиска по статьям',level=2)
        doc.add_paragraph('BANKING77 содержит обращения и метки намерений, но не содержит проверенных ответов. Поэтому поиск отделён от генерации: сначала система должна уметь находить и показывать фрагменты одобренных статей, а уже затем можно обсуждать генератор. Сейчас в репозитории нет такого корпуса, поэтому точность поиска, Recall@5 и MRR не измерялись.')
        doc.add_paragraph('Формат JSONL требует стабильный уникальный id, заголовок, содержание, ссылку на первоисточник, дату updated_at в формате YYYY-MM-DD, язык, владельца статьи, лицензию/разрешение и status=approved. Это делает ответственность и право использования проверяемыми до индексации; черновики загрузчик отклоняет. Загрузчик также сообщает номер строки с некорректным JSON и не допускает повторяющиеся идентификаторы.')
        doc.add_paragraph('Текст очищается от лишних пробелов и режется на фрагменты до 900 символов с перекрытием 120 символов. Перекрытие сохраняет часть контекста у границы соседних фрагментов. Индекс — word TF-IDF для unigram и bigram. Этот прозрачный baseline выбран потому, что его легко запустить и разобрать, он использует уже установленный scikit-learn и даёт точные фрагменты для ручной проверки. Он лучше всего подходит как точка сравнения для последующего BM25 или эмбеддингов, но не гарантирует семантический поиск синонимов.')
        doc.add_paragraph('Добавлен второй lexical baseline — BM25 на unigram с параметрами k1=1.5 и b=0.75. Он учитывает частоту слова во фрагменте, его редкость по корпусу и длину фрагмента. Так можно сравнить TF-IDF с распространённым способом ранжирования документов, не добавляя новый пакет. Оба ранжировщика возвращают один формат документа, но у score разные шкалы: TF-IDF использует cosine similarity, BM25 — BM25 score. Сравнивать эти числа напрямую нельзя; методы сравниваются по Recall@5 и MRR на одной экспертной разметке. Порог отказа подбирается отдельно для каждого ранжировщика.')
        doc.add_paragraph('На calibration добавлен небольшой перебор BM25 параметров: k1 ∈ {1.0, 1.2, 1.5, 2.0} и b ∈ {0.3, 0.5, 0.75, 0.9}. Для 16 комбинаций notebook выводит Recall@5 и MRR. Матрица частот слов строится один раз; метод with_parameters создаёт кандидата с другими коэффициентами без повторной токенизации корпуса. Это ограниченная исследовательская сетка, а не гарантия глобального оптимума. Выбор k1 и b делается по calibration, holdout не используется для настройки.')
        doc.add_paragraph('Чтобы агрегированные Recall@5 и MRR можно было проверить на примерах, evaluate_retrieval возвращает для каждого answerable запроса первый ранг релевантной статьи, ID и score top-1, найденные ID top-5 и релевантные ID, пропущенные в top-5. Notebook собирает из этих полей таблицу ошибок отдельно для TF-IDF и BM25 на calibration. Это помогает отличить промах ранжировщика от неверного ID, языка или неполной статьи. Таблица не заменяет чтение источника. Holdout остаётся финальной оценкой; если по нему меняется система, необходим новый независимый набор.')
        doc.add_paragraph('После завершения holdout ноутбук записывает локальный каталог work/retrieval_runs/<run_id>/: run_manifest.json с UTC-временем, Git revision, состоянием рабочего дерева и хешем diff, конфигурацией retrieval, версиями Python и основных пакетов, SHA-256 корпуса и обеих выборок, выбранными настройками и итоговыми метриками; CSV-файлы разделяют общие и языковые метрики, ошибки calibration, grid BM25 и holdout-порог. Это упрощает сравнение запусков и открытие таблиц в PyCharm. Каталог work исключён из Git, поскольку таблица ошибок содержит тексты запросов. Артефакты не создаются, пока отсутствуют корпус или экспертная разметка.')
        doc.add_paragraph('Для чтения предыдущих запусков без переобучения добавлен notebooks/05_retrieval_run_review.ipynb. Он группирует сравнения по совпадающим хешам корпуса и calibration-файла, показывает выбранные параметры и позволяет открыть CSV ошибок. Holdout-метрики показаны только для аудита; при разных хешах holdout результаты не сравниваются как одна и та же финальная оценка. Изменения по holdout потребуют нового независимого набора.')
        doc.add_paragraph('Операционная ячейка измеряет build time индекса и P50/P95 latency на первых 200 calibration-запросах, после прогрева и трёх повторов каждого запроса. Измеряются TF-IDF и BM25 с зафиксированными параметрами BM25. Размер sparse_matrix_mib складывает массивы data/indices/indptr и не включает vocabulary Python, сериализацию, API overhead или полный RSS. Это сравнительный ориентир на данной машине, а не SLO. Результаты сохраняются в CSV и манифест запуска; holdout для замеров не используется.')
        doc.add_heading('Контроль качества и актуальности корпуса',level=2)
        doc.add_paragraph('До построения индекса полезно проверить не только техническую схему, но и происхождение и состояние знаний. src/rag/audit.py валидирует вход, считает статьи по языкам, владельцам и лицензиям, показывает повторяющиеся заголовки и нормализованные тексты, а также формирует очередь статей старше заданного срока. Отметка review_due означает необходимость ручного пересмотра владельцем; она не выключает статью автоматически и не доказывает, что содержание неверно.')
        doc.add_paragraph('Для воспроизводимого формата даты загрузчик принимает ISO дату YYYY-MM-DD. Индекс строится только для записей со status=approved и заполненными owner/license. Это не заменяет юридическую или содержательную проверку, но не позволяет случайно добавить черновик с непонятным владельцем.')
        add_code_block(doc,'''from src.rag.audit import audit_corpus

report = audit_corpus(
    "data/knowledge/articles.jsonl",
    review_after_days=365,
)
print(report["summary"])
print(report["review_due"])''')
        doc.add_paragraph('Аудит можно открыть в notebooks/04_knowledge_audit.ipynb или запустить командой python -m src.rag.audit. JSON отчёт сохраняется отдельно и не заменяет исходные статьи. Пока корпуса нет, аудит не выдаёт численную сводку, а возвращает понятную ошибку отсутствующего файла.')
        doc.add_paragraph('Файлы articles.jsonl, queries_calibration.jsonl, queries_holdout.jsonl и reports/knowledge_audit.json добавлены в .gitignore. Запросы могут содержать данные пользователей, а статьи — внутренние инструкции и сведения об ответственном подразделении. В Git отправляем код и схему; содержимое корпуса можно публиковать только после явного подтверждения владельца и разрешения на распространение.')
        doc.add_paragraph('В ноутбуке 02_retrieval_exploration.ipynb после добавления data/knowledge/articles.jsonl можно загрузить корпус и вывести пять совпадений обоих ранжировщиков. У каждой выдачи есть score_type: tfidf_cosine_similarity или bm25. Это сырые ранжирующие величины, а не вероятности правильного ответа.')
        add_code_block(doc,'''from src.rag.retriever import KnowledgeRetriever

retriever = KnowledgeRetriever.from_jsonl("data/knowledge/articles.jsonl")
hits = retriever.search("card payment reversed", top_k=5)
for hit in hits:
    print(hit.title, hit.source, hit.score, hit.score_type)
    print(hit.text)''')
        doc.add_paragraph('Проверка качества требует отдельной выборки запросов с экспертно отмеченными relevant_document_ids. Recall@5 усредняет долю релевантных статей, которые попали в первые пять; MRR учитывает позицию первой релевантной статьи. Сравнение lexical baseline, BM25 и эмбеддингов нужно проводить на одних запросах и одних метках. Запросы без ответа в корпусе нужны для определения поведения отказа и передачи оператору. Генерацию подключать после этой проверки; качество retrieval и качество ответа оценивать отдельно.')
        doc.add_paragraph('Оценщик находится в src/rag/evaluation.py. Он проверяет JSONL с запросами, убеждается, что размеченные ID есть в корпусе, ранжирует уникальные документы (несколько совпавших фрагментов одной статьи не занимают несколько мест) и возвращает метрики и результаты по каждому запросу. Recall@5 для одного запроса — число найденных в первых пяти релевантных статей, делённое на полное число релевантных статей; MRR — обратная позиция первой релевантной статьи. Усреднение проводится только по answerable запросам. Запросы с пустым списком статей учитываются отдельно и не включаются в Recall@5/MRR: эти метрики сами по себе не измеряют корректность отказа.')
        doc.add_paragraph('Поле language в строке разметки необязательное, но для корпуса на нескольких языках рекомендуемое. При наличии language поиск фильтрует выдачу по языку, а evaluator проверяет соответствие языка релевантной статьи и считает query_count, answerable/unanswerable, Recall@5 и MRR по каждому языку отдельно. Незаполненный language показывает срез unspecified. Это помогает обнаружить языки, качество которых теряется в общей метрике.')
        doc.add_paragraph('Для каждого языка calibration должны быть размечены answerable и unanswerable запросы. Функция sweep_abstention_thresholds возвращает независимую кривую и диапазон порогов по каждой языковой группе; это учитывает различия score и unsafe accept rate. Если в языке нет обеих групп, настроить отказ только по этим данным нельзя: оценщик попросит дополнить разметку. Порог также калибруется отдельно для TF-IDF и BM25.')
        add_code_block(doc,'''from src.rag.evaluation import load_queries, evaluate_retrieval

examples = load_queries("data/knowledge/queries_calibration.jsonl")
metrics = evaluate_retrieval(retriever, examples, k=5)
print(metrics["recall_at_5"], metrics["mrr"])''')
        doc.add_paragraph('Реализация метрик не означает, что эксперимент уже проведён. Без экспертной разметки нельзя назвать Recall@5 или MRR и сравнить lexical TF-IDF с BM25 или эмбеддингами. Для честного сравнения фиксируйте одну и ту же размеченную выборку; после настройки retrieval подготовьте новый независимый набор для финальной оценки.')
        doc.add_paragraph('Для этого в проекте выделены queries_calibration.jsonl и queries_holdout.jsonl. Calibration содержит разнообразные запросы с ответом и без него в каждой языковой группе; на нём выбираются ранжировщик, параметры BM25 и отдельный порог для каждого языка. Holdout размечается заранее, но его метрики скрыты до фиксации решения. В notebooks/02_retrieval_exploration.ipynb методы сравниваются только на calibration. Разработчик вручную переносит метод в SELECTED_METHOD, параметры BM25 в соответствующие переменные, а выбранный порог для каждого языка — в SELECTED_THRESHOLDS; следующая ячейка выводит финальные метрики на holdout один раз.')
        doc.add_paragraph('До сравнения методов функция audit_query_splits проверяет нормализованные дубли внутри выборок, точные повторы между ними, конфликты разметки и пересечение query_group_id. Для парафраз вручную укажите общий query_group_id в строках JSONL: все варианты группы должны оставаться в одной части. Preflight показывает только агрегированные счётчики и останавливает оценку при утечке. Нормализация Unicode, регистра, пробелов и пунктуации ловит буквальные варианты, но не заменяет ручную группировку семантически похожих обращений.')
        add_code_block(doc,'''from src.rag.evaluation import evaluate_retrieval

bm25_candidate = bm25_retriever.with_parameters(k1=1.2, b=0.75)
metrics = evaluate_retrieval(bm25_candidate, calibration_examples, k=5)
print(metrics["recall_at_5"], metrics["mrr"])''')
        doc.add_heading('Порог отказа и безопасная выдача',level=2)
        doc.add_paragraph('Поиск должен уметь воздержаться от выдачи статьи, когда совпадение слабое или top-1 статья не подтверждена разметкой. Функция sweep_abstention_thresholds перебирает пороги сырого lexical similarity. Для каждого порога она считает coverage (сколько запросов приняты), precision/recall/F1 поддержанных ответов, долю принятых запросов без релевантного top-1 и false accept rate на unanswerable запросах. Принятый ответ засчитывается как поддержанный только если запрос имеет релевантную статью и top-1 документ входит в экспертный список.')
        add_code_block(doc,'''from src.rag.evaluation import sweep_abstention_thresholds
import pandas as pd

threshold_results = sweep_abstention_thresholds(retriever, examples)
threshold_table = pd.DataFrame(threshold_results)
threshold_table.sort_values(
    ["language", "supported_answer_f1", "coverage"],
    ascending=[True, False, False],
).groupby("language").head(10)''')
        doc.add_paragraph('Набор queries_calibration.jsonl используется для сравнения ранжировщиков и выбора порога, а queries_holdout.jsonl — только для финальной оценки уже выбранного варианта. После просмотра holdout не меняйте метод и порог по его метрикам. Иначе оценка будет оптимистичной. Score любого ранжировщика не является вероятностью; выбранный порог нельзя переносить на другой корпус или модель без повторной калибровки. Сейчас реальных threshold метрик нет: нет корпуса и экспертных запросов.')
        add_code_block(doc,'''holdout_results = sweep_abstention_thresholds(
    selected_retriever,
    holdout_examples,
    thresholds=SELECTED_THRESHOLDS,
)''')
        add_table(doc,['Слой','Ответственность','Проверка'],[
            ('API','Валидация входа и единый формат ответа','Контракты и коды ошибок'),
            ('Intent model','Классификация запроса','Версия, метрики и fallback'),
            ('Retrieval','Поиск по одобренным статьям','Релевантность и актуальность'),
            ('Generation','Сборка ответа с источниками','Grounding и отказ при нехватке данных'),
            ('Operations','Логи, метрики, версия модели','Задержка, ошибки и дрейф')])
    elif title.startswith('11.'):
        doc.add_paragraph('Вопросы для самостоятельного разбора: почему Macro F1 лучше показывает качество редких intents; как TF-IDF строит признаки; зачем векторизатор находится внутри Pipeline; чем word и char n-граммы различаются; почему official test нельзя использовать для подбора; как измерять задержку и размер модели.')
        doc.add_paragraph('Ответы проверяем по ходу реализации: Macro F1 усредняет F1 классов поровну; Pipeline предотвращает утечку словаря из validation; test даёт только финальную независимую оценку; latency замеряем на тех же запросах и сохраняем вместе с версиями библиотек и конфигурацией.')
    elif title.startswith('12.'):
        add_table(doc,['Термин','Объяснение'],[
            ('Intent classification','Предсказание намерения по тексту запроса.'),
            ('Train / validation / test','Обучение / выбор модели / финальная независимая оценка.'),
            ('Data leakage','Попадание информации из оценки в обучение или выбор конфигурации.'),
            ('TF-IDF','Взвешивание слов или символьных фрагментов по частоте в документе и корпусе.'),
            ('N-грамма','Последовательность из N соседних слов или символов.'),
            ('Linear SVM','Линейный классификатор с максимальным разделяющим зазором.'),
            ('Macro F1','Среднее F1 по классам с одинаковым весом.'),
            ('MLflow','Локальный учёт параметров, метрик и артефактов эксперимента.'),
            ('RAG','Поиск источников и генерация ответа, опирающаяся на найденные документы.')])
    else:
        doc.add_paragraph('Раздел будет заполнен на соответствующем этапе по фактическим данным и результатам экспериментов. Численные результаты до запуска эксперимента не подставляются.')
    for sub in subs:
        if title.startswith(('3.','4.','5.','6.','7.','8.','9.','10.','11.','12.')):
            continue
        doc.add_heading(sub,level=2)
        doc.add_paragraph('Понятия, варианты подхода, обоснование выбора, реализация и результаты будут добавлены на соответствующем этапе.')

doc.add_heading('Журнал разработки',level=1)
doc.add_paragraph('Ниже зафиксирована последовательность выполненных работ и следующий шаг. Результаты intent classification включают validation и однократную финальную оценку official test; retrieval-метрики появятся после добавления корпуса и экспертной разметки.')
add_table(doc,['Порядок','Работа','Результат','Артефакты'],[
    ('1','Постановка задачи и поиск открытых данных','Выбрана 77-классовая intent classification задача BANKING77; зафиксированы лицензия и ограничения','reports/research.md'),
    ('2','EDA источника','10 003 train и 3 080 test; проверены схема, пропуски, классы, длина текста, повторы и пересечения','reports/eda_summary.json, reports/figures/'),
    ('3','Очистка и разбиение','Удалены 4 внутренних повтора и 7 совпадений с official test; получено 7 993 train и 1 999 validation','configs/split.json, split_manifest.json'),
    ('4','Классические baseline','Сравнены Majority, Logistic Regression, Linear SVM и Naive Bayes; лучший baseline Macro F1=0.8795','experiments/baseline/results.csv'),
    ('5','Подбор параметров Linear SVM','Проверено 18 комбинаций word n-грамм, C и class weights; прироста не найдено','linear_svm_tuning_results.csv'),
    ('6','Сравнение word и char признаков','Проверено 7 конфигураций; word + char_wb достиг Macro F1=0.8987','word_char_comparison.csv, character_tuning_reports/'),
    ('7','Фиксация кандидата и замеры','Word + char_wb Linear SVM: Macro F1=0.8987; P50/P95=1.21/2.20 мс; joblib=20.36 MiB','configs/final_model.json, experiments/final_model/operational_metrics.json'),
    ('8','Финальная оценка','Official test: 3 080 запросов; Accuracy=0.9010, Macro F1=0.9011; тест не использовался для настройки','experiments/final_model/test_metrics.json, classification_report.csv, confusion_matrix.csv'),
    ('9','HTTP API классификации','Добавлены predict endpoint, валидация, health/readiness и версия модели; HTTP запуск предстоит проверить','src/api/main.py, README.md'),
    ('10','Retrieval baseline','Реализованы проверка корпуса, чанки до 900 символов с перекрытием 120, word TF-IDF поиск и просмотр в Jupyter; метрик пока нет без базы статей','src/rag/retriever.py, notebooks/02_retrieval_exploration.ipynb'),
    ('11','Оценка retrieval','Добавлены проверка JSONL запросов, ранжирование уникальных статей, Recall@5, MRR и учёт запросов без ответа; метрики ждут экспертной разметки','src/rag/evaluation.py, data/knowledge/README.md'),
    ('12','Калибровка отказа','Добавлен перебор порога lexical similarity с coverage и метриками поддержанных ответов; порог калибруется отдельно от финальной проверки','sweep_abstention_thresholds, notebooks/02_retrieval_exploration.ipynb'),
    ('13','Сравнение TF-IDF и BM25','Добавлен BM25 с настраиваемыми k1 и b; ноутбук считает одинаковые Recall@5/MRR и строит отдельные кривые отказа; численного победителя без корпуса нет','src/rag/retriever.py, notebooks/02_retrieval_exploration.ipynb'),
    ('14','HTTP API поиска','Добавлены маршрут поиска, отдельная проверка готовности базы знаний и выбор индекса TF-IDF/BM25 через настройки среды; HTTP проверка ожидает корпус','src/api/main.py, README.md'),
    ('15','Ручная проверка API из PyCharm','Добавлен ноутбук проверки liveness/readiness и поискового запроса; реальные HTTP результаты появятся после запуска сервиса с корпусом','notebooks/03_api_search.ipynb'),
    ('16','Аудит базы знаний','Закреплены owner/license/status=approved и ISO дата; добавлены отчёт по языкам/дубликатам и очередь ручной проверки документов старше заданного срока','src/rag/audit.py, notebooks/04_knowledge_audit.ipynb'),
    ('17','Протокол калибровки и holdout','Файлы запросов разделены на calibration и финальный holdout; методы/порог выбираются только на первой выборке, финальные метрики считаются после фиксации решения','data/knowledge/queries_calibration.jsonl, queries_holdout.jsonl, notebooks/02_retrieval_exploration.ipynb'),
    ('18','Защита holdout от утечки','Ноутбук не сравнивает TF-IDF/BM25 на holdout и просит вручную зафиксировать метод/порог; финальная оценка запускается только после этого','notebooks/02_retrieval_exploration.ipynb, reports/research.md'),
    ('19','Настройка параметров BM25','Добавлен небольшой перебор k1/b на calibration; индекс переиспользуется, holdout остаётся только для оценки зафиксированного решения','BM25Retriever.with_parameters, notebooks/02_retrieval_exploration.ipynb'),
    ('20','Метрики по языкам','Добавлено поле language в разметку, фильтрация выдачи по языку и отдельный Recall@5/MRR breakdown; для unanswerable языковых групп ranking метрики отмечаются как недоступные','src/rag/evaluation.py, notebooks/02_retrieval_exploration.ipynb'),
    ('21','Языковые пороги отказа','Пороговые кривые строятся отдельно по языку, методам и параметрам; holdout проверяет фиксированный словарь порогов','sweep_abstention_thresholds, SELECTED_THRESHOLDS, notebooks/02_retrieval_exploration.ipynb'),
    ('22','Применение порога в API','Добавлен configs/retrieval.json и retrieval_status; API сообщает, прошёл ли top-1 настроенный порог, но оставляет кандидаты для человеческой проверки','configs/retrieval.json, src/api/main.py, notebooks/03_api_search.ipynb'),
    ('23','Защита калибровки от изменений','Кандидат конфигурации сохраняет SHA-256 корпуса и наборов разметки; API отключает порог, если корпус, ранжировщик или параметры разбиения изменились','notebooks/02_retrieval_exploration.ipynb, configs/retrieval.json, src/api/main.py'),
    ('24','Разбор поисковых ошибок','К результатам добавлены ранг релевантной статьи, top-1 и пропущенные ID; ноутбук показывает отдельную таблицу ошибок на calibration для ручного разбора','src/rag/evaluation.py, notebooks/02_retrieval_exploration.ipynb'),
    ('25','Сохранение запусков retrieval','После holdout локально сохраняются параметры, версии библиотек, хеши данных, метрики и CSV ошибок; каталог work исключён из Git','notebooks/02_retrieval_exploration.ipynb, reports/README.md, .gitignore'),
    ('26','Просмотр истории retrieval-экспериментов','Добавлен ноутбук для группировки запусков по хешам корпуса и calibration, просмотра настроек и CSV ошибок без повторного индексирования','notebooks/05_retrieval_run_review.ipynb, reports/README.md'),
    ('27','Аудит утечки retrieval-выборок','До оценки считаются дубли, нормализованные совпадения запросов и пересечение query_group_id; при утечке ноутбук останавливает сравнение','audit_query_splits, data/knowledge/README.md, notebooks/02_retrieval_exploration.ipynb'),
    ('28','Операционные метрики retrieval','На calibration измеряются build time, P50/P95 latency и размер sparse-матрицы TF-IDF/BM25; результаты сохраняются рядом с run manifest','notebooks/02_retrieval_exploration.ipynb, notebooks/05_retrieval_run_review.ipynb, reports/README.md'),
    ('29','HTTP latency поиска','Добавлен последовательный round-trip замер API на calibration с P50/P95 и статусами; запросы не записываются в локальный CSV открытым текстом','notebooks/03_api_search.ipynb, reports/README.md'),
    ('30','Карта завершённости и следующий gate','Разделены готовность кода, измеренные результаты и обязательные входные данные; описан путь к реальной сквозной проверке поиска','README.md, docs/study_guide.docx, reports/research.md')])

doc.add_heading('Источники данных и публикации',level=1)
for source in [
'BANKING77 dataset card: https://huggingface.co/datasets/PolyAI/banking77',
'Casanueva et al. (2020): https://aclanthology.org/2020.nlp4convai-1.5/',
'Исходные CSV и лицензия CC BY 4.0: https://github.com/PolyAI-LDN/task-specific-datasets',
'CLINC OOS: https://aclanthology.org/D19-1131/',
'MASSIVE: https://huggingface.co/datasets/AmazonScience/massive',
'Bitext Customer Support: https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset',
'MLflow Tracking API: https://mlflow.org/docs/latest/tracking/tracking-api/',
'MLflow SQLite backend: https://mlflow.org/docs/latest/tracking/backend-stores/',
'FastAPI request body: https://fastapi.tiangolo.com/tutorial/body/',
'FastAPI response model: https://fastapi.tiangolo.com/tutorial/response-model/',
'FastAPI lifespan: https://fastapi.tiangolo.com/advanced/events/']:
    doc.add_paragraph(source,style='List Bullet')
footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT; footer.add_run('Учебный ML/NLP проект  •  '); field(footer,'PAGE')
OUT.parent.mkdir(parents=True,exist_ok=True); TEMP_OUT.parent.mkdir(parents=True,exist_ok=True); doc.save(TEMP_OUT)
shutil.copy2(TEMP_OUT, OUT)
print(OUT)
