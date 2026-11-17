from dataclasses import replace

import numpy as np

from src.rag.retriever import RetrievalHit


def reciprocal_rank_fusion(rankings, rank_constant=60):
    if isinstance(rank_constant, bool) or not isinstance(rank_constant, int) or rank_constant < 1:
        raise ValueError('rank_constant must be a positive integer.')
    scores, examples = {}, {}
    for ranking in rankings:
        seen = set()
        for hit in ranking:
            if hit.chunk_id in seen:
                continue
            seen.add(hit.chunk_id)
            if hit.chunk_id in examples and replace(examples[hit.chunk_id], score=0, score_type='') != replace(hit, score=0, score_type=''):
                raise ValueError('Different evidence shares the same chunk_id.')
            examples[hit.chunk_id] = hit
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rank_constant + len(seen))
    return [replace(examples[key], score=scores[key], score_type='rrf')
            for key in sorted(scores, key=lambda key: (-scores[key], key))]


class DenseRetriever:
    def __init__(self, chunks, encoder):
        self.chunks = tuple(chunks)
        if not self.chunks or len({chunk.chunk_id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError('Dense index requires nonempty unique chunks.')
        self.encoder = encoder
        self.matrix = self._encode(['passage: ' + chunk.text for chunk in self.chunks])

    def _encode(self, texts):
        vectors = np.asarray(self.encoder.encode(texts, normalize_embeddings=True, convert_to_numpy=True,
                                                 show_progress_bar=False), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != len(texts) or not np.isfinite(vectors).all():
            raise ValueError('Invalid embeddings.')
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ValueError('Zero-norm embedding.')
        return vectors / norms

    def search(self, query, top_k=5, language=None):
        if not isinstance(query, str) or not query.strip() or top_k < 1:
            raise ValueError('A nonempty query and positive top_k are required.')
        scores = self.matrix @ self._encode(['query: ' + query.strip()])[0]
        indices = [i for i, chunk in enumerate(self.chunks) if language is None or chunk.language.casefold() == language.casefold()]
        indices.sort(key=lambda i: (-float(scores[i]), self.chunks[i].chunk_id))
        return [RetrievalHit(**self.chunks[i].__dict__, score=float(scores[i]), score_type='dense_cosine') for i in indices[:top_k]]


class HybridRetriever:
    def __init__(self, lexical, dense, candidate_depth=4, rank_constant=60):
        if lexical.chunks != dense.chunks:
            raise ValueError('Both branches must use identical chunks in the same order.')
        if isinstance(candidate_depth, bool) or not isinstance(candidate_depth, int) or candidate_depth < 1:
            raise ValueError('candidate_depth must be positive.')
        reciprocal_rank_fusion([], rank_constant)
        self.chunks = lexical.chunks
        self.lexical, self.dense = lexical, dense
        self.candidate_depth, self.rank_constant = candidate_depth, rank_constant

    def search(self, query, top_k=5, language=None):
        if top_k < 1:
            raise ValueError('top_k must be positive.')
        rankings = [branch.search(query, top_k=self.candidate_depth, language=language) for branch in [self.lexical, self.dense]]
        return reciprocal_rank_fusion(rankings, self.rank_constant)[:top_k]
