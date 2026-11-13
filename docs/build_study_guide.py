from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from pathlib import Path

out = Path(r'C:\Users\maks5\Documents\Codex\2026-11-13\x20\outputs\study_guide.docx')
doc = Document()
sec = doc.sections[0]
sec.top_margin = Inches(.72); sec.bottom_margin = Inches(.72)
sec.left_margin = Inches(.82); sec.right_margin = Inches(.82)
styles = doc.styles
styles['Normal'].font.name = 'Aptos'; styles['Normal'].font.size = Pt(10)
styles['Normal'].font.color.rgb = RGBColor(45, 55, 68)
for name, size, color in [('Title', 25, '153B5B'), ('Heading 1', 17, '153B5B'), ('Heading 2', 12, '167D8D')]:
    st = styles[name]; st.font.name='Aptos Display'; st.font.size=Pt(size); st.font.bold=True; st.font.color.rgb=RGBColor.from_string(color)

def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd'); shd.set(qn('w:fill'),fill); tcPr.append(shd)

def field(paragraph, instr):
    r=paragraph.add_run(); b=OxmlElement('w:fldChar'); b.set(qn('w:fldCharType'),'begin'); r._r.append(b)
    r2=paragraph.add_run(); it=OxmlElement('w:instrText'); it.set(qn('xml:space'),'preserve'); it.text=instr; r2._r.append(it)
    r3=paragraph.add_run(); e=OxmlElement('w:fldChar'); e.set(qn('w:fldCharType'),'end'); r3._r.append(e)

p=doc.add_paragraph(style='Title'); p.alignment=WD_ALIGN_PARAGRAPH.LEFT
p.add_run('Исследование и разработка интеллектуальной системы обработки пользовательских обращений с применением ML, NLP и Generative AI')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(10)
r=p.add_run('Учебное пособие и журнал экспериментов'); r.bold=True; r.font.size=Pt(13); r.font.color.rgb=RGBColor.from_string('167D8D')
doc.add_paragraph('Проект развивается по этапам: сначала проверяем данные и формулируем задачу, затем обучаем и сравниваем модели, после этого проектируем поиск, генерацию и API. Документ обновляется вместе с кодом. На текущем этапе рассматривается BANKING77 для классификации намерений; результаты обучения и метрики появятся только после реальных экспериментов.')
p=doc.add_paragraph(); p.paragraph_format.space_before=Pt(14); p.add_run('Текущий этап: 1 — исследование').bold=True
p=doc.add_paragraph('Дата подготовки: 13 ноября 2026')
doc.add_page_break()
doc.add_heading('Оглавление', level=1)
p=doc.add_paragraph(); field(p, 'TOC \\o "1-2" \\h \\z \\u')
doc.add_paragraph('Если оглавление не обновилось автоматически, в Word выберите его и нажмите «Обновить поле».')

doc.add_heading('Как читать это пособие', level=1)
doc.add_paragraph('Каждый этап будет объяснять задачу и варианты решения, фиксировать выбор и его причины, показывать реализацию, реальные результаты и следующий эксперимент. Пока эксперимент не проведён, раздел содержит только постановку и план. Мы не будем выдавать плановые значения за результаты.')

sections = [
('1. Постановка задачи', ['Бизнес-проблема и цель', 'Формализация intent classification', 'Входы, выходы и критерии успеха']),
('2. Поиск и выбор данных', ['Сравнение BANKING77, CLINC150, MASSIVE и Bitext', 'Источник, лицензия и ограничения', 'Что этот датасет позволяет и чего не позволяет исследовать']),
('3. Exploratory Data Analysis', ['Распределение классов и дисбаланс', 'Длина запросов', 'Пропуски, дубликаты и split overlap', 'Графики и выводы']),
('4. Подготовка данных', ['Очистка и нормализация текста', 'Стратифицированное train/validation/test разбиение', 'Предотвращение Data Leakage']),
('5. Выбор моделей', ['Majority и классические baseline', 'TF-IDF с Logistic Regression, Linear SVM и Naive Bayes', 'DistilBERT и BERT', 'Zero-shot и few-shot: условия сравнения']),
('6. Обучение', ['Конфигурации и воспроизводимость', 'Функция потерь и оптимизатор', 'Переобучение и остановка обучения']),
('7. Оценка качества', ['Accuracy, Precision, Recall и F1', 'Macro F1 и Weighted F1', 'Confusion Matrix и анализ ошибок', 'Скорость, память и размер модели']),
('8. Улучшение модели', ['Гипотезы и журнал экспериментов', 'Гиперпараметры и TF-IDF', 'Class weights, предобработка и длина текста', 'Fine-tuning и сравнение до/после']),
('9. Итоговый выбор модели', ['Сравнительная таблица', 'Компромисс качества, задержки и ресурсов', 'Ограничения и границы применимости']),
('10. Практическое применение', ['Архитектура FastAPI', 'Retrieval, RAG и reranking', 'Разрешённые инструменты агента', 'Docker, MLflow и мониторинг']),
('11. Подготовка к собеседованию', ['Вопросы и ответы по ML/NLP', 'Метрики, утечки и валидация', 'Transformers, fine-tuning и эксплуатация']),
('12. Глоссарий', ['Термины ML, NLP и Generative AI'])]

for title, subs in sections:
    doc.add_heading(title, level=1)
    if title.startswith('2.'):
        doc.add_paragraph('Предварительное решение этапа: BANKING77 содержит 13 083 английских банковских запроса и 77 намерений; опубликованное разбиение включает 10 003 примера для обучения и 3 080 для тестирования. Это benchmark для single-label intent classification. В нём нет меток срочности, статей базы знаний и эталонных ответов, поэтому эти продуктовые функции требуют отдельных данных и оценки.')
    elif title.startswith('1.'):
        doc.add_paragraph('Первая задача проекта — по тексту запроса определить одну из 77 меток намерения. Это не равно определению приоритета или срочности. Основной критерий сравнения моделей планируется выбрать Macro F1 на validation; итоговый test используется после выбора модели.')
    else:
        doc.add_paragraph('Раздел будет заполнен на соответствующем этапе по фактическим данным и результатам экспериментов. Пока численные результаты отсутствуют.')
    for s in subs:
        doc.add_heading(s, level=2)
        doc.add_paragraph('Планируется раскрыть: понятия и варианты подхода, причины выбора, реализацию и результаты этапа.')

doc.add_heading('Источники данных и публикации', level=1)
for s in [
'BANKING77: https://huggingface.co/datasets/PolyAI/banking77',
'Casanueva et al. (2020): https://aclanthology.org/2020.nlp4convai-1.5/',
'CLINC OOS: https://aclanthology.org/D19-1131/',
'MASSIVE: https://huggingface.co/datasets/AmazonScience/massive',
'Bitext Customer Support: https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset',
'Исходные данные и CC BY 4.0: https://github.com/PolyAI-LDN/task-specific-datasets']:
    doc.add_paragraph(s, style='List Bullet')

footer=sec.footer.paragraphs[0]; footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('Учебный ML/NLP проект  •  '); field(footer, 'PAGE')
out.parent.mkdir(parents=True, exist_ok=True); doc.save(out)
print(out)
