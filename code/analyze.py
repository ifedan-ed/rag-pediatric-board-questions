"""Statistics for the 2nd revision of JMIR AI ms#113094.

Reads the frozen August generations and any revision runs, and writes the numbers
the revised manuscript reports: accuracy with 95% CIs, paired differences with
95% CIs, exact McNemar tests, the GEE model, extraction failures, token counts,
cost per 1,000 correct answers, sensitivity analyses, and the repeated-run and
no-"prefer" comparisons when those runs exist.

Usage: python3 analyze.py  (paths are fixed below; output goes to results/)
"""
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "data" / "private"
OUT = ROOT / "analysis" / "results"
OUT.mkdir(parents=True, exist_ok=True)

# Stems that refer to a figure, photograph or image that the models never saw.
FIGURE = re.compile(r"(figure|photograph|image|shown (below|above|here|in))", re.I)


def wilson(k, n, z=1.959964):
    """Wilson score interval for k successes out of n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def newcombe_paired(a, b, c, d):
    """Newcombe (1998) method 10 CI for the paired difference p1 - p2.

    a: both correct, b: first correct only, c: second correct only, d: neither.
    Here p1 is the retrieval arm and p2 the direct arm, so b counts corrected
    answers and c counts broken ones.
    """
    n = a + b + c + d
    p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n)
    l2, u2 = wilson(a + c, n)
    diff = p1 - p2
    denom = (a + b) * (c + d) * (a + c) * (b + d)
    if denom == 0:
        phi = 0.0
    else:
        num = a * d - b * c
        # Continuity-free version of the phi correction used by Newcombe.
        phi = num / math.sqrt(denom)
    dl = math.sqrt((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2)
    du = math.sqrt((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2)
    return diff, diff - dl, diff + du


def mcnemar_exact(b, c):
    """Two-sided exact McNemar test on the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * stats.binom.cdf(min(b, c), n, 0.5))


def load_august():
    questions = {q["qid"]: q for q in json.load(open(PRIVATE / "questions.json"))}
    rows = []
    for g in json.load(open(PRIVATE / "august_generations.json")):
        q = questions[g["qid"]]
        tokens = g["tokens"] or {}
        rows.append({
            "qid": g["qid"], "model": g["model"], "arm": g["arm"], "run": "august",
            "selected": g["selected"], "source": g["selected_source"],
            "correct": int((g["selected"] or "").upper() == q["answer_key"].upper()),
            "cost": float(g["cost"]) if g["cost"] is not None else np.nan,
            "prompt_tokens": tokens.get("prompt_tokens"), "completion_tokens": tokens.get("completion_tokens"),
            "retrieval_ids": g["retrieval_ids"], "edition": q["edition"],
            "figure": bool(FIGURE.search(q["stem"])),
        })
    return questions, pd.DataFrame(rows)


def load_run(pattern, questions, manual):
    """Revision runs. `manual` maps (file stem, model, qid) to a hand-read letter."""
    rows = []
    for path in sorted((PRIVATE / "out").glob(pattern)):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            q = questions[r["qid"]]
            selected, source = r["selected"], "auto"
            key = f'{path.stem}|{r["model"]}|{r["qid"]}'
            if selected is None and key in manual:
                selected, source = manual[key], "manual"
            tokens = r["tokens"] or {}
            rows.append({
                "qid": r["qid"], "model": r["model"], "arm": r["arm"], "run": r["rep"],
                "selected": selected, "source": source if selected else "unread",
                "correct": int((selected or "").upper() == q["answer_key"].upper()),
                "cost": r["cost"], "prompt_tokens": tokens.get("prompt_tokens"),
                "completion_tokens": tokens.get("completion_tokens"),
                "edition": q["edition"], "figure": bool(FIGURE.search(q["stem"])),
            })
    return pd.DataFrame(rows)


def per_model_table(df, arm_a="direct", arm_b="rag"):
    """Accuracy per arm with Wilson CIs, paired difference with Newcombe CI, exact McNemar."""
    out = []
    for model, g in df.groupby("model"):
        wide = g.pivot_table(index="qid", columns="arm", values="correct")
        wide = wide.dropna()
        x, y = wide[arm_a].astype(int), wide[arm_b].astype(int)
        n = len(wide)
        a = int(((x == 1) & (y == 1)).sum())
        broken = int(((x == 1) & (y == 0)).sum())
        corrected = int(((x == 0) & (y == 1)).sum())
        d = n - a - broken - corrected
        ka, kb = int(x.sum()), int(y.sum())
        diff, lo, hi = newcombe_paired(a, corrected, broken, d)
        p = mcnemar_exact(broken, corrected)
        out.append({
            "model": model, "n": n,
            f"{arm_a}_correct": ka, f"{arm_a}_pct": 100 * ka / n,
            f"{arm_a}_lo": 100 * wilson(ka, n)[0], f"{arm_a}_hi": 100 * wilson(ka, n)[1],
            f"{arm_b}_correct": kb, f"{arm_b}_pct": 100 * kb / n,
            f"{arm_b}_lo": 100 * wilson(kb, n)[0], f"{arm_b}_hi": 100 * wilson(kb, n)[1],
            "diff_pp": 100 * diff, "diff_lo": 100 * lo, "diff_hi": 100 * hi,
            "broken": broken, "corrected": corrected,
            "p": p, "p_bonferroni": min(1.0, p * 10),
        })
    return pd.DataFrame(out).sort_values(f"{arm_a}_pct", ascending=False)


def gee(df, arm_b="rag", interaction=False):
    """Logit GEE, exchangeable correlation, clustered on question, model as fixed effect."""
    d = df.copy()
    d["treat"] = (d["arm"] == arm_b).astype(int)
    formula = "correct ~ treat * C(model)" if interaction else "correct ~ treat + C(model)"
    model = smf.gee(formula, groups="qid", data=d, family=sm.families.Binomial(),
                    cov_struct=sm.cov_struct.Exchangeable())
    fit = model.fit()
    if interaction:
        names = [n for n in fit.params.index if n.startswith("treat:")]
        r = np.zeros((len(names), len(fit.params)))
        for i, name in enumerate(names):
            r[i, list(fit.params.index).index(name)] = 1
        wald = fit.wald_test(r, scalar=True)
        return {"interaction_chi2": float(wald.statistic), "df": len(names), "p": float(wald.pvalue)}
    b, se = fit.params["treat"], fit.bse["treat"]
    return {"or": math.exp(b), "lo": math.exp(b - 1.959964 * se), "hi": math.exp(b + 1.959964 * se),
            "p": float(fit.pvalues["treat"]), "exchangeable_rho": float(model.cov_struct.dep_params)}


def main():
    questions, aug = load_august()
    manual_path = PRIVATE / "out" / "manual_letters.json"
    manual = json.loads(manual_path.read_text()) if manual_path.exists() else {}
    report = {}

    # Primary comparison, August data.
    t1 = per_model_table(aug)
    t1.to_csv(OUT / "table1_accuracy.csv", index=False)
    n_d, n_r = int(aug[aug.arm == "direct"].correct.sum()), int(aug[aug.arm == "rag"].correct.sum())
    pooled = aug.pivot_table(index=["model", "qid"], columns="arm", values="correct")
    a = int(((pooled.direct == 1) & (pooled.rag == 1)).sum())
    br = int(((pooled.direct == 1) & (pooled.rag == 0)).sum())
    co = int(((pooled.direct == 0) & (pooled.rag == 1)).sum())
    diff, lo, hi = newcombe_paired(a, co, br, len(pooled) - a - br - co)
    report["pooled"] = {
        "direct": [n_d, 3000, 100 * n_d / 3000, *[100 * v for v in wilson(n_d, 3000)]],
        "rag": [n_r, 3000, 100 * n_r / 3000, *[100 * v for v in wilson(n_r, 3000)]],
        "broken": br, "corrected": co,
        "diff_pp_unclustered_ci": [100 * diff, 100 * lo, 100 * hi],
        "gee": gee(aug), "gee_interaction": gee(aug, interaction=True),
    }
    corr = stats.pearsonr(t1["direct_pct"], t1["diff_pp"])
    report["baseline_vs_benefit"] = {"r": corr.statistic, "p": corr.pvalue}

    # Sensitivity: without the 33 figure items; by PREP edition.
    nofig = aug[~aug.figure]
    report["sensitivity_no_figure_items"] = {
        "questions": int(nofig.qid.nunique()),
        "direct_pct": 100 * nofig[nofig.arm == "direct"].correct.mean(),
        "rag_pct": 100 * nofig[nofig.arm == "rag"].correct.mean(),
        "gee": gee(nofig),
    }
    fig = aug[aug.figure]
    report["figure_items"] = {"questions": int(fig.qid.nunique()),
                              "direct_pct": 100 * fig[fig.arm == "direct"].correct.mean(),
                              "rag_pct": 100 * fig[fig.arm == "rag"].correct.mean()}
    report["by_edition"] = (aug.groupby(["edition", "arm"]).correct.agg(["sum", "count", "mean"])
                            .reset_index().to_dict("records"))

    # Extraction: hand-read answers by model and arm, and whether any sit in a discordant pair.
    manual_rows = aug[aug.source == "manual"]
    report["hand_read"] = {
        "total": len(manual_rows),
        "by_model_arm": manual_rows.groupby(["model", "arm"]).size().reset_index(name="n").to_dict("records"),
    }
    keyed = aug.set_index(["model", "qid", "arm"])
    in_pairs = {"broken": 0, "corrected": 0}
    for (model, qid), row in pooled.iterrows():
        if row.direct == row.rag:
            continue
        kind = "broken" if row.direct == 1 else "corrected"
        if "manual" in (keyed.loc[(model, qid, "direct"), "source"], keyed.loc[(model, qid, "rag"), "source"]):
            in_pairs[kind] += 1
    report["hand_read"]["in_discordant_pairs"] = in_pairs

    # Tokens and cost. Cost is reported as US dollars per 1,000 correct answers.
    cost = (aug.groupby(["model", "arm"])
            .agg(cost_usd=("cost", "sum"), correct=("correct", "sum"),
                 prompt_tokens_mean=("prompt_tokens", "mean"), completion_tokens_mean=("completion_tokens", "mean"),
                 cost_per_answer=("cost", "mean"))
            .reset_index())
    cost["usd_per_1000_correct"] = 1000 * cost.cost_usd / cost.correct
    cost["usd_per_million_questions"] = 1e6 * cost.cost_per_answer
    cost.to_csv(OUT / "table2_cost_tokens.csv", index=False)
    totals = aug.groupby("arm").agg(cost=("cost", "sum"), correct=("correct", "sum"),
                                    prompt=("prompt_tokens", "mean"), completion=("completion_tokens", "mean"))
    totals["usd_per_1000_correct"] = 1000 * totals.cost / totals.correct
    report["cost_totals"] = totals.reset_index().to_dict("records")

    # Repeated direct runs: how often does a model change its answer with no retrieval at all?
    reps = load_run("gen_direct_r*.jsonl", questions, manual)
    if len(reps):
        base = aug[aug.arm == "direct"][["model", "qid", "selected", "correct"]]
        out = []
        for run, g in reps.groupby("run"):
            m = base.merge(g[["model", "qid", "selected", "correct", "source"]], on=["model", "qid"], suffixes=("_aug", "_rep"))
            read = m[m.selected_rep.notna()]
            changed = read[read.selected_aug.str.upper() != read.selected_rep.str.upper()]
            for model, gm in read.groupby("model"):
                ch = changed[changed.model == model]
                out.append({"run": run, "model": model, "pairs": len(gm), "changed": len(ch),
                            "now_wrong": int(((ch.correct_aug == 1) & (ch.correct_rep == 0)).sum()),
                            "now_right": int(((ch.correct_aug == 0) & (ch.correct_rep == 1)).sum()),
                            "accuracy_pct": 100 * gm.correct_rep.mean(),
                            "unread": int((m[m.model == model].source == "unread").sum())})
        rep_table = pd.DataFrame(out)
        rep_table.to_csv(OUT / "repeat_direct_runs.csv", index=False)
        report["repeat_direct"] = (rep_table.groupby("run")[["pairs", "changed", "now_wrong", "now_right", "unread"]]
                                   .sum().reset_index().to_dict("records"))
        report["retrieval_changed_answers"] = int((pooled.direct != pooled.rag).sum())
        letters = aug.pivot_table(index=["model", "qid"], columns="arm", values="selected", aggfunc="first")
        report["retrieval_changed_letters"] = int((letters.direct.str.upper() != letters.rag.str.upper()).sum())

    # Retrieval without the "prefer the context" instruction, against the August direct arm.
    noprefer = load_run("gen_rag_noprefer_*.jsonl", questions, manual)
    if len(noprefer):
        both = pd.concat([aug[aug.arm == "direct"], noprefer[noprefer.source != "unread"]])
        t = per_model_table(both, "direct", "rag_noprefer")
        t.to_csv(OUT / "table_noprefer.csv", index=False)
        report["noprefer"] = {"unread": int((noprefer.source == "unread").sum()),
                              "gee_vs_direct": gee(both, arm_b="rag_noprefer"),
                              "broken": int(t.broken.sum()), "corrected": int(t.corrected.sum())}
        # Against the original retrieval arm: does dropping the instruction change accuracy?
        vs_rag = pd.concat([aug[aug.arm == "rag"], noprefer[noprefer.source != "unread"]])
        report["noprefer"]["correct"] = int(noprefer.correct.sum())
        report["noprefer"]["gee_vs_original_rag"] = gee(vs_rag, arm_b="rag_noprefer")

    # Reproducibility: each repeated direct run against the August direct arm.
    repeats = load_run("gen_direct_r*.jsonl", questions, manual)
    if len(repeats):
        report["repeat_vs_august"] = {}
        for rep, sub in repeats.groupby("run"):
            d = pd.concat([aug[aug.arm == "direct"], sub.assign(arm="direct_" + rep)])
            report["repeat_vs_august"][rep] = {"correct": int(sub.correct.sum()),
                                               "gee": gee(d, arm_b="direct_" + rep)}

    # The original retrieval prompt replayed on the stored passages (same passages as
    # the no-prefer arm): against direct, against the August retrieval arm (reproduction),
    # and against no-prefer (the instruction alone, passages held fixed).
    replay = load_run("gen_rag_replay_*.jsonl", questions, manual)
    if len(replay):
        rp = replay[replay.source != "unread"]
        both = pd.concat([aug[aug.arm == "direct"], rp])
        t = per_model_table(both, "direct", "rag_replay")
        t.to_csv(OUT / "table_rag_replay.csv", index=False)
        report["rag_replay"] = {
            "pairs": len(replay), "unread": int((replay.source == "unread").sum()),
            "correct": int(replay.correct.sum()),
            "broken": int(t.broken.sum()), "corrected": int(t.corrected.sum()),
            "gee_vs_direct": gee(both, arm_b="rag_replay"),
            "gee_vs_august_rag": gee(pd.concat([aug[aug.arm == "rag"], rp]), arm_b="rag_replay"),
        }
        if len(noprefer):
            np_ = noprefer[noprefer.source != "unread"]
            report["rag_replay"]["gee_noprefer_vs_replay"] = gee(pd.concat([rp, np_]), arm_b="rag_noprefer")
            t2 = per_model_table(pd.concat([rp, np_]), "rag_replay", "rag_noprefer")
            t2.to_csv(OUT / "table_prefer_vs_noprefer.csv", index=False)
        letters = pd.concat([aug[aug.arm == "rag"], rp]).pivot_table(
            index=["model", "qid"], columns="arm", values="selected", aggfunc="first").dropna()
        report["rag_replay"]["letters_changed_vs_august_rag"] = int(
            (letters.rag.str.upper() != letters.rag_replay.str.upper()).sum())

    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=float))
    print(json.dumps(report, indent=2, default=float)[:6000])


if __name__ == "__main__":
    main()
