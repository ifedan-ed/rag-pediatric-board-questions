"""Passage-relevance audit for JMIR AI ms#113094 (revision 2).

Combines the rater files (one primary rating per question, a second independent
rating for 60 questions) with the August answers, and writes:
  - how relevant and sufficient the retrieved passages were, per question;
  - agreement between the two raters on the 60 double-rated questions;
  - a classification of every answer that retrieval changed:
      broken (correct -> wrong):
        misleading retrieval  the passages point to the option the model chose
        retrieval failure     the passages are insufficient to find the key
        reader failure        the passages are sufficient and support the key
      corrected (wrong -> correct):
        supplied by passages  the passages are sufficient and support the key
        not from passages     the passages are insufficient
The passages rated are those of the repeated retrieval; the classification is
reported both for all pairs and for pairs whose August source documents match
the repeated retrieval exactly, since only there are the rated passages
certainly the ones that model saw.
"""
import json
from collections import Counter
from pathlib import Path

import pandas as pd


def cohen_kappa_score(x, y, weights=None):
    """Cohen's kappa for two raters; weights="linear" gives linearly weighted kappa."""
    cats = sorted(set(x) | set(y))
    idx = {c: i for i, c in enumerate(cats)}
    k, n = len(cats), len(x)
    obs = [[0] * k for _ in range(k)]
    for a, b in zip(x, y):
        obs[idx[a]][idx[b]] += 1
    row = [sum(obs[i]) for i in range(k)]
    col = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i, j):
        if weights == "linear":
            return abs(i - j) / (k - 1) if k > 1 else 0
        return 0 if i == j else 1

    po = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    pe = sum(w(i, j) * row[i] * col[j] for i in range(k) for j in range(k)) / (n * n)
    return 1 - po / pe if pe else 1.0

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "data" / "private"
RATINGS = PRIVATE / "audit" / "ratings"
OUT = ROOT / "analysis" / "results"


def load(prefix):
    rows = {}
    for path in sorted(RATINGS.glob(prefix + "_*.json")):
        for r in json.loads(path.read_text()):
            rows[r["qid"]] = r
    return rows


def main():
    primary, second = load("primary"), load("second")
    questions = {q["qid"]: q for q in json.load(open(PRIVATE / "questions.json"))}
    rerun = {}
    for line in (PRIVATE / "out" / "retrieval.jsonl").read_text().splitlines():
        r = json.loads(line)
        rerun[r["qid"]] = r["ids"]
    report = {}

    # Passage and question level summary.
    levels = Counter(v for r in primary.values() for v in r["passages"])
    n_pass = sum(levels.values())
    q_any_relevant = sum(1 for r in primary.values() if 2 in r["passages"])
    q_all_irrelevant = sum(1 for r in primary.values() if max(r["passages"]) == 0)
    report["passages"] = {"total": n_pass, "relevant": levels[2], "partial": levels[1], "irrelevant": levels[0]}
    report["questions"] = {
        "total": len(primary),
        "any_relevant_passage": q_any_relevant,
        "no_relevant_or_partial": q_all_irrelevant,
        "sufficient": sum(r["sufficient"] for r in primary.values()),
        "supports_key": sum(r["supports_key"] for r in primary.values()),
        "supports_other_option": sum(r["supports_other"] is not None for r in primary.values()),
    }

    # Agreement on the double-rated questions.
    both = sorted(set(primary) & set(second))
    pa = [v for q in both for v in primary[q]["passages"]]
    sa = [v for q in both for v in second[q]["passages"]]
    agree = {"questions": len(both), "passages": len(pa)}
    agree["passage_weighted_kappa"] = cohen_kappa_score(pa, sa, weights="linear")
    agree["passage_exact_agreement"] = sum(a == b for a, b in zip(pa, sa)) / len(pa)
    for field in ("sufficient", "supports_key"):
        x = [primary[q][field] for q in both]
        y = [second[q][field] for q in both]
        agree[field + "_agreement"] = sum(a == b for a, b in zip(x, y)) / len(both)
        agree[field + "_kappa"] = cohen_kappa_score(x, y)
    report["agreement"] = agree

    # Classify the answers retrieval changed.
    gens = json.load(open(PRIVATE / "august_generations.json"))
    by = {(g["model"], g["qid"], g["arm"]): g for g in gens}
    rows = []
    for (model, qid, arm), g in by.items():
        if arm != "direct":
            continue
        rag = by[(model, qid, "rag")]
        key = questions[qid]["answer_key"].upper()
        d_ok = (g["selected"] or "").upper() == key
        r_sel = (rag["selected"] or "").upper()
        r_ok = r_sel == key
        if d_ok == r_ok:
            kind, cls = ("both correct" if d_ok else "both wrong"), None
        else:
            rt = primary[qid]
            if d_ok:
                kind = "broken"
                if rt["supports_other"] and rt["supports_other"].upper() == r_sel:
                    cls = "misleading retrieval"
                elif not rt["sufficient"]:
                    cls = "retrieval failure"
                else:
                    cls = "reader failure"
            else:
                kind = "corrected"
                cls = "supplied by passages" if (rt["sufficient"] and rt["supports_key"]) else "not from passages"
        rows.append({"model": model, "qid": qid, "kind": kind, "class": cls,
                     "same_documents": rag["retrieval_ids"] == rerun[qid],
                     "sufficient": primary[qid]["sufficient"]})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "audit_pairs.csv", index=False)
    for label, sub in (("all_pairs", df), ("matched_documents", df[df.same_documents])):
        changed = sub[sub.kind.isin(["broken", "corrected"])]
        report["classification_" + label] = {
            "pairs": len(sub),
            "by_kind": sub.kind.value_counts().to_dict(),
            "classes": changed.groupby(["kind", "class"]).size().reset_index(name="n").to_dict("records"),
            "sufficient_rate_by_kind": sub.groupby("kind").sufficient.mean().to_dict(),
        }
    report["matched_document_pairs"] = int(df.same_documents.sum())

    (OUT / "audit_report.json").write_text(json.dumps(report, indent=2, default=float))
    print(json.dumps(report, indent=2, default=float))


if __name__ == "__main__":
    main()
