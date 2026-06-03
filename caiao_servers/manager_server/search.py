"""CAIAO semantic search — TF-IDF + keyword hybrid search over server capabilities.

Improvement over the hub's keyword-only Jaccard search.
TF-IDF provides better ranking when tool descriptions are longer and more varied.
"""

import math
import re
import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase keyword tokens."""
    normalized = text.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"([a-z])([A-Z])", r"\1 \2", normalized)
    tokens = re.findall(r"[a-zA-Z0-9]+", normalized.lower())
    return [t for t in tokens if len(t) > 1]


def _ngram_similarity(a: str, b: str, n: int = 3) -> float:
    """Character n-gram similarity between two strings."""
    if not a or not b:
        return 0.0
    a_ngrams = {a[i:i + n] for i in range(len(a) - n + 1)}
    b_ngrams = {b[i:i + n] for i in range(len(b) - n + 1)}
    if not a_ngrams or not b_ngrams:
        return 0.0
    return len(a_ngrams & b_ngrams) / len(a_ngrams | b_ngrams)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


class SearchIndex:
    """TF-IDF + keyword hybrid search index for CAIAO servers and tools.

    Builds an inverted index from server manifests. Supports:
    - TF-IDF ranking for longer queries
    - Keyword Jaccard for short queries
    - N-gram similarity as tiebreaker
    """

    def __init__(self):
        self._documents: list[dict[str, Any]] = []
        self._idf: dict[str, float] = {}
        self._tfidf_vectors: list[dict[str, float]] = []
        self._keyword_sets: list[set[str]] = []
        self._built = False

    def build(self, manifests: list[dict[str, Any]]) -> int:
        """Build the search index from a list of caiao.yaml manifest dicts.

        Each document = one tool entry from a server manifest.
        Returns the number of documents indexed.
        """
        self._documents = []
        doc_texts = []

        for m in manifests:
            server_name = m.get("name", "unknown")
            server_desc = m.get("description", "")
            server_caps = " ".join(m.get("capabilities", []))
            server_kind = m.get("kind", "")

            for tool in m.get("tools", []):
                tname = tool.get("name", "")
                tdesc = tool.get("description", "")
                ttags = " ".join(tool.get("tags", []))

                full_text = f"{tname} {tdesc} {ttags} {server_name} {server_desc} {server_caps} {server_kind}"
                doc_texts.append(full_text)

                self._documents.append({
                    "tool_name": tname,
                    "tool_description": tdesc,
                    "server_name": server_name,
                    "server_description": server_desc,
                    "server_kind": server_kind,
                    "capabilities": m.get("capabilities", []),
                    "tags": tool.get("tags", []),
                })

        self._build_tfidf(doc_texts)
        self._built = True
        logger.info(f"Search index built: {len(self._documents)} documents")
        return len(self._documents)

    def _build_tfidf(self, doc_texts: list[str]) -> None:
        """Compute TF-IDF vectors for all documents."""
        doc_count = len(doc_texts)
        if doc_count == 0:
            self._idf = {}
            self._tfidf_vectors = []
            self._keyword_sets = []
            return

        tokenized = [_tokenize(t) for t in doc_texts]
        term_freqs = [Counter(tokens) for tokens in tokenized]
        all_terms = set()
        for tf in term_freqs:
            all_terms.update(tf.keys())

        self._idf = {}
        for term in all_terms:
            doc_freq = sum(1 for tf in term_freqs if term in tf)
            self._idf[term] = math.log((doc_count + 1) / (doc_freq + 1)) + 1

        self._tfidf_vectors = []
        for tf in term_freqs:
            vec = {}
            norm = 0
            for term, freq in tf.items():
                weight = freq * self._idf.get(term, 0)
                vec[term] = weight
                norm += weight * weight
            norm = math.sqrt(norm) if norm > 0 else 1
            vec = {t: w / norm for t, w in vec.items()}
            self._tfidf_vectors.append(vec)

        self._keyword_sets = [set(tokens) for tokens in tokenized]

    def search(self, query: str, threshold: float = 0.15, top_k: int = 10) -> list[dict[str, Any]]:
        """Search for servers/tools matching a query.

        Uses keyword Jaccard for queries with <= 2 content tokens,
        TF-IDF cosine similarity for longer queries.
        N-gram similarity is used as a tiebreaker.

        Returns a list of matches sorted by relevance.
        """
        if not self._built or not self._documents:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        if len(query_tokens) <= 2:
            scores = self._keyword_search(query_tokens)
        else:
            scores = self._tfidf_search(query_tokens)

        results = []
        for idx, score in scores:
            if score >= threshold:
                doc = dict(self._documents[idx])
                doc["score"] = round(score, 3)
                ngram = _ngram_similarity(query.lower(), doc["tool_name"].lower())
                doc["name_match"] = round(ngram, 3)
                doc["combined_score"] = round(score * 0.7 + ngram * 0.3, 3)
                results.append(doc)

        results.sort(key=lambda r: r["combined_score"], reverse=True)
        return results[:top_k]

    def _keyword_search(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        query_set = set(query_tokens)
        scores = []
        for idx, kw_set in enumerate(self._keyword_sets):
            score = _jaccard(query_set, kw_set)
            name = self._documents[idx]["tool_name"]
            if query_set & _tokenize(name):
                score = max(score, 0.5)
            if any(qt in name for qt in query_tokens):
                score = max(score, 0.3)
            scores.append((idx, score))
        scores.sort(key=lambda s: s[1], reverse=True)
        return scores

    def _tfidf_search(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        query_tf = Counter(query_tokens)
        query_vec = {}
        norm = 0
        for term, freq in query_tf.items():
            weight = freq * self._idf.get(term, 0)
            query_vec[term] = weight
            norm += weight * weight
        norm = math.sqrt(norm) if norm > 0 else 1
        query_vec = {t: w / norm for t, w in query_vec.items()}

        scores = []
        for idx, doc_vec in enumerate(self._tfidf_vectors):
            dot = sum(query_vec.get(t, 0) * w for t, w in doc_vec.items())
            keyword_score = _jaccard(set(query_tokens), self._keyword_sets[idx])
            combined = dot * 0.6 + keyword_score * 0.4
            scores.append((idx, combined))

        scores.sort(key=lambda s: s[1], reverse=True)
        return scores

    def find_tool_owner(self, tool_name: str) -> dict | None:
        """Find which server owns a given tool name."""
        for doc in self._documents:
            if doc["tool_name"] == tool_name:
                return dict(doc)
        return None

    def get_servers_summary(self) -> list[dict]:
        """Return a summary of all indexed servers."""
        servers: dict[str, dict] = {}
        for doc in self._documents:
            sname = doc["server_name"]
            if sname not in servers:
                servers[sname] = {
                    "name": sname,
                    "description": doc["server_description"],
                    "kind": doc["server_kind"],
                    "capabilities": doc["capabilities"],
                    "tool_count": 0,
                    "tools": [],
                }
            servers[sname]["tool_count"] += 1
            servers[sname]["tools"].append(doc["tool_name"])
        return list(servers.values())
