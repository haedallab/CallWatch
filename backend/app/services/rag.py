"""Lightweight retrieval (TF-IDF, runs in 512MB RAM) + grounded LLM answers with citations."""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import llm


def chunk_text(text: str, size: int = 900, overlap: int = 150) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 60]
    chunks, buf = [], ""
    for p in paras:
        if len(buf) + len(p) < size:
            buf = (buf + "\n" + p).strip()
            continue
        if buf:
            chunks.append(buf)
        while len(p) > size:
            chunks.append(p[:size])
            p = p[size - overlap:]
        buf = p
    if buf:
        chunks.append(buf)
    return chunks


def rank(query: str, docs: list[dict], k: int = 4) -> list[dict]:
    """docs: [{text, ...meta}] -> top-k with 'score' (cosine on TF-IDF, 1-2 grams)."""
    if not docs:
        return []
    texts = [d["text"] for d in docs]
    try:
        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True, max_features=60000)
        m = vec.fit_transform(texts + [query])
    except ValueError:
        return []
    sims = cosine_similarity(m[-1], m[:-1]).ravel()
    order = sims.argsort()[::-1][:k]
    return [{**docs[i], "score": round(float(sims[i]), 3)} for i in order if sims[i] > 0]


QA_SYSTEM = """당신은 미국 상장사의 어닝콜·SEC 공시를 분석하는 금융 리서치 어시스턴트입니다.
규칙:
1. 제공된 [근거] 안의 정보만 사용합니다. 근거에 없으면 "제공된 자료에서 확인되지 않습니다"라고 답합니다.
2. 문장마다 근거 번호를 [1], [2] 형식으로 붙입니다.
3. 수치는 원문 단위를 유지하고, 가이던스(전망)와 실제 실적을 명확히 구분합니다.
4. 투자 권유·매수/매도 의견은 제시하지 않습니다.
5. 한국어로 3~6문장 이내로 답합니다."""


def answer(question: str, contexts: list[dict]) -> dict:
    if not contexts:
        return {"answer": "관련 근거를 찾지 못했습니다. 먼저 해당 종목을 분석하거나 트랜스크립트를 추가해 주세요.",
                "citations": [], "mode": "empty"}
    blocks = "\n\n".join(f"[{i + 1}] ({c['source']}, {c.get('date', '')})\n{c['text'][:1500]}"
                         for i, c in enumerate(contexts))
    out = llm.complete_text(QA_SYSTEM, f"[근거]\n{blocks}\n\n[질문]\n{question}")
    if out:
        return {"answer": out.strip(), "citations": contexts, "mode": "llm"}
    # extractive fallback: show the best passages verbatim
    lines = []
    for i, c in enumerate(contexts[:4]):
        if c["source"].startswith("CallWatch"):
            lines += [f"- {ln} [{i + 1}]" for ln in c["text"].splitlines()[:6]]
        else:
            lines.append(f"- {c['text'][:260].strip()}… [{i + 1}]")
    return {"answer": "LLM 키가 없어 정렬 결과표와 관련 원문을 그대로 보여드립니다. "
                      "(불리한 이탈이 큰 순 → 결과 대기 → 최근 이행 순)\n\n" + "\n".join(lines),
            "citations": contexts, "mode": "extractive"}
