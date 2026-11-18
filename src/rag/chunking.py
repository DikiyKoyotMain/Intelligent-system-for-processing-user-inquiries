import re

import pysbd

SENTENCE_STRATEGY = 'sentences_pysbd034_v1'
CHARACTER_STRATEGY = 'characters_v1'
DEFAULT_CHUNKING = dict(strategy=SENTENCE_STRATEGY, max_chars=900, overlap_sentences=1)


def integer(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}.')
    return value


def normalize_chunking(config):
    if not isinstance(config, dict):
        raise ValueError('chunking must be an object.')
    strategy = config.get('strategy', CHARACTER_STRATEGY)
    max_chars = integer(config.get('max_chars'), 'max_chars', 1)
    if strategy == SENTENCE_STRATEGY:
        if set(config) - {'strategy', 'max_chars', 'overlap_sentences'}:
            raise ValueError('Sentence chunking accepts overlap_sentences, not overlap_chars.')
        return dict(strategy=strategy, max_chars=max_chars,
                    overlap_sentences=integer(config.get('overlap_sentences', 1), 'overlap_sentences'))
    if strategy == CHARACTER_STRATEGY:
        if set(config) - {'strategy', 'max_chars', 'overlap_chars'}:
            raise ValueError('Unknown character chunking option.')
        overlap = integer(config.get('overlap_chars', 120), 'overlap_chars')
        if overlap >= max_chars:
            raise ValueError('overlap_chars must be smaller than max_chars.')
        return dict(strategy=strategy, max_chars=max_chars, overlap_chars=overlap)
    raise ValueError('Unknown chunking strategy.')


def split_sentences(text, language=None):
    normalized = re.sub(r'\s+', ' ', text).strip()
    if not normalized:
        return []
    language = language.casefold().split('-')[0] if language else None
    if language not in pysbd.languages.LANGUAGE_CODES:
        language = 'ru' if re.search(r'[А-Яа-яЁё]', normalized) else 'en'
    return [sentence.strip() for sentence in pysbd.Segmenter(language=language, clean=False).segment(normalized) if sentence.strip()]


def character_chunks(text, max_chars, overlap_chars):
    chunks = []
    start = 0
    while start < len(text):
        end = min(start+max_chars, len(text))
        if end < len(text):
            boundary = text.rfind(' ', start, end)
            if boundary > start+max_chars//2:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end-overlap_chars, start+1)
    return chunks


def split_into_chunks(text, max_chars=900, overlap_chars=None, *, strategy=None, overlap_sentences=1, language=None):
    integer(max_chars, 'max_chars', 1)
    if not isinstance(text, str):
        raise ValueError('text must be a string.')
    if overlap_chars is not None:
        integer(overlap_chars, 'overlap_chars')
        if overlap_chars >= max_chars:
            raise ValueError('overlap_chars must be smaller than max_chars.')
    strategy = strategy or (CHARACTER_STRATEGY if overlap_chars is not None else SENTENCE_STRATEGY)
    normalized = re.sub(r'\s+', ' ', text).strip()
    if strategy == CHARACTER_STRATEGY:
        config = normalize_chunking(dict(strategy=strategy, max_chars=max_chars,
                                         overlap_chars=120 if overlap_chars is None else overlap_chars))
        return character_chunks(normalized, max_chars, config['overlap_chars'])
    normalize_chunking(dict(strategy=strategy, max_chars=max_chars, overlap_sentences=overlap_sentences))
    if overlap_chars is not None:
        raise ValueError('Use overlap_sentences with sentence chunking.')
    units = []
    for sentence in split_sentences(normalized, language):
        if len(sentence) > max_chars:
            units.extend((part, False) for part in character_chunks(sentence, max_chars, 0))
        else:
            units.append((sentence, True))
    chunks, current = [], []
    for unit in units:
        if current and len(' '.join(part[0] for part in current+[unit])) > max_chars:
            chunks.append(' '.join(part[0] for part in current))
            retained = []
            for part in reversed(current):
                if not part[1] or len(retained) >= overlap_sentences:
                    break
                retained.insert(0, part)
            while retained and len(' '.join(part[0] for part in retained+[unit])) > max_chars:
                retained.pop(0)
            current = retained
        current.append(unit)
    if current:
        chunks.append(' '.join(part[0] for part in current))
    return chunks
