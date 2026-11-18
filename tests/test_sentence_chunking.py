import re
import unittest

from src.rag.chunking import CHARACTER_STRATEGY, DEFAULT_CHUNKING, SENTENCE_STRATEGY, normalize_chunking, split_into_chunks, split_sentences


class SentenceChunkingTests(unittest.TestCase):
    def test_russian_and_english_sentence_boundaries(self):
        examples = [('Ставка 12.5%. Документы приняты. Всё готово!', 'ru', 3),
                    ('Dr. Smith works here. Visit https://bank.example/help. Next step.', 'en', 3),
                    ('Первый вопрос? Второй ответ! Последняя строка без точки', 'ru', 3)]
        for text, language, count in examples:
            sentences = split_sentences(text, language)
            self.assertEqual(len(sentences), count)
            self.assertEqual(' '.join(sentences), text)

    def test_whole_sentence_overlap(self):
        text = 'First sentence here. Second sentence here. Third sentence here.'
        chunks = split_into_chunks(text, max_chars=43, overlap_sentences=1, language='en')
        self.assertEqual(chunks, ['First sentence here. Second sentence here.', 'Second sentence here. Third sentence here.'])

    def test_no_overlap_covers_every_sentence_once(self):
        text = 'Первая фраза. Вторая фраза! Третья фраза? Четвёртая фраза.'
        chunks = split_into_chunks(text, max_chars=30, overlap_sentences=0)
        self.assertEqual(' '.join(chunks), text)
        self.assertTrue(all(len(chunk) <= 30 for chunk in chunks))

    def test_oversized_sentence_and_long_word_are_bounded(self):
        for text in [' '.join(['слово']*70)+'. Следующий шаг.', 'x'*180+'. Done.']:
            chunks = split_into_chunks(text, max_chars=50, overlap_sentences=0)
            self.assertTrue(all(0 < len(chunk) <= 50 for chunk in chunks))
            self.assertEqual(re.sub(r'\s', '', ''.join(chunks)), re.sub(r'\s', '', text))

    def test_overlap_never_prevents_progress(self):
        text = ' '.join(f'Предложение номер {i} завершено.' for i in range(100))
        chunks = split_into_chunks(text, max_chars=65, overlap_sentences=5)
        self.assertLessEqual(len(chunks), 100)
        self.assertTrue(chunks[-1].endswith('99 завершено.'))

    def test_legacy_config_is_explicit_and_stable(self):
        config = normalize_chunking(dict(max_chars=90, overlap_chars=20))
        self.assertEqual(config['strategy'], CHARACTER_STRATEGY)
        text = ' '.join(['token']*100)
        self.assertEqual(split_into_chunks(text, 90, 20), split_into_chunks(text, **config))
        self.assertEqual(normalize_chunking(DEFAULT_CHUNKING), DEFAULT_CHUNKING)

    def test_invalid_options_are_rejected(self):
        for options in [dict(max_chars=True), dict(max_chars=0), dict(overlap_sentences=-1),
                        dict(strategy='unknown'), dict(strategy=SENTENCE_STRATEGY, overlap_chars=10)]:
            with self.assertRaises(ValueError):
                split_into_chunks('Some text.', **options)
        with self.assertRaises(ValueError):
            normalize_chunking(dict(strategy=SENTENCE_STRATEGY, max_chars=900, overlap_chars=120))

    def test_empty_input_and_multiline_text(self):
        self.assertEqual(split_into_chunks('  \n '), [])
        self.assertEqual(split_into_chunks('Первая строка.\n\nВторая строка.'), ['Первая строка. Вторая строка.'])
