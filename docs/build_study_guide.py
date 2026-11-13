from pathlib import Path
import shutil
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'study_guide.docx'
TEMP_OUT = ROOT / 'work' / 'study_guide_generated.docx'
FIG = ROOT / 'reports' / 'figures'

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


doc=Document(); sec=doc.sections[0]
sec.top_margin=Inches(.72); sec.bottom_margin=Inches(.72); sec.left_margin=Inches(.82); sec.right_margin=Inches(.82)
update_fields=OxmlElement('w:updateFields'); update_fields.set(qn('w:val'),'true'); doc.settings._element.append(update_fields)
styles=doc.styles; styles['Normal'].font.name='Aptos'; styles['Normal'].font.size=Pt(10); styles['Normal'].font.color.rgb=RGBColor(45,55,68)
for name,size,color in [('Title',25,'153B5B'),('Heading 1',17,'153B5B'),('Heading 2',12,'167D8D')]:
    st=styles[name]; st.font.name='Aptos Display'; st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor.from_string(color)

p=doc.add_paragraph(style='Title'); p.add_run('Исследование и разработка интеллектуальной системы обработки пользовательских обращений с применением ML, NLP и Generative AI')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(10); r=p.add_run('Учебное пособие и журнал экспериментов'); r.bold=True; r.font.size=Pt(13); r.font.color.rgb=RGBColor.from_string('167D8D')
doc.add_paragraph('Проект развивается по этапам: сначала проверяем данные и формулируем задачу, затем обучаем и сравниваем модели, после этого проектируем поиск, генерацию и API. Документ объясняет решения и пополняется реальными результатами по мере работы.')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(14); p.add_run('Завершены этапы 1–2: исследование и первичный EDA').bold=True
doc.add_paragraph('Дата обновления: 13 ноября 2026')
doc.add_page_break()

doc.add_heading('Оглавление', level=1); p=doc.add_paragraph(); field(p,'TOC \\o "1-2" \\h \\z \\u')
doc.add_paragraph('В Word выберите оглавление и обновите поле, если номера страниц не обновились автоматически.')
doc.add_heading('Как читать это пособие', level=1)
doc.add_paragraph('Каждый этап объясняет задачу и варианты решения, фиксирует выбранный подход и его причины, затем показывает реализацию, фактические результаты и следующие эксперименты. Результаты моделей пока не получены; в документе их нет.')

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
        doc.add_paragraph('Первая ML-задача — определить по тексту запроса одну из 77 меток намерения BANKING77. Это не то же самое, что оценка срочности. Основной критерий сравнения планируется выбрать Macro F1 на validation; официальный test останется для финальной оценки.')
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
        doc.add_paragraph('Нормализация использовалась только для аудита, исходные тексты не менялись. Перед разбиением на validation оставим официальный test неизменным, удалим train-дубликаты по этому ключу и зафиксируем этот шаг до обучения. Проверка семантически близких, но не идентичных запросов — отдельная задача.')
    else:
        doc.add_paragraph('Раздел будет заполнен на соответствующем этапе по фактическим данным и результатам экспериментов. Численные результаты до запуска эксперимента не подставляются.')
    for sub in subs:
        if title.startswith('3.'):
            continue
        doc.add_heading(sub,level=2)
        doc.add_paragraph('Понятия, варианты подхода, обоснование выбора, реализация и результаты будут добавлены на соответствующем этапе.')

doc.add_heading('Источники данных и публикации',level=1)
for source in [
'BANKING77 dataset card: https://huggingface.co/datasets/PolyAI/banking77',
'Casanueva et al. (2020): https://aclanthology.org/2020.nlp4convai-1.5/',
'Исходные CSV и лицензия CC BY 4.0: https://github.com/PolyAI-LDN/task-specific-datasets',
'CLINC OOS: https://aclanthology.org/D19-1131/',
'MASSIVE: https://huggingface.co/datasets/AmazonScience/massive',
'Bitext Customer Support: https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset']:
    doc.add_paragraph(source,style='List Bullet')
footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT; footer.add_run('Учебный ML/NLP проект  •  '); field(footer,'PAGE')
OUT.parent.mkdir(parents=True,exist_ok=True); TEMP_OUT.parent.mkdir(parents=True,exist_ok=True); doc.save(TEMP_OUT)
shutil.copy2(TEMP_OUT, OUT)
repo_copy=ROOT/'docs'/'study_guide.docx'; repo_copy.write_bytes(OUT.read_bytes())
print(OUT)
