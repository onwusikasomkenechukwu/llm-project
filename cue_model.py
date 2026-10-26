#!/usr/bin/env python3
"""Mixed-effects models of the identity-cue run.

    python cue_model.py cues-responses.jsonl cues-judgments.jsonl --out-dir analysis/cue-model

One row per grade. Every model has a random intercept per answer, since the
four or five grades of one answer share that answer; fixed effects for the
answering model, the judge and the question absorb their levels. Three models:

  vs baseline   each cue group (and the irrelevant-detail controls) against the
                no-identity baseline
  race-gender   race, gender and their interaction, and whether the race effect
                depends on the cue form (label, name, profile), on the channel
                (user turn or saved memory), or on the answering model
  education     did not finish high school against a doctorate, and whether
                that depends on cue form, channel or answering model

Two-level factors are coded +1/2 and -1/2, so a coefficient is the difference
between the two levels averaged over everything else: `race` is Black minus
White, `gender` woman minus man, `edu` did not finish high school minus
doctorate, `channel` memory minus user turn. Many-level factors use sum coding,
so an interaction term is that level's deviation from the average effect.

Each model is fitted twice: strict, where a grade that gives premise_handling
on a non-Loaded question is unusable, and lenient, where only that score is
dropped (as analyze.py --ignore-stray-premise). As a check on the mixed model's
intervals, which assume cue effects are the same on every question, each term
also gets an OLS interval clustered by question (by answer when there is only
one question).
"""

import argparse
import json
import re
import warnings
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf
from scipy.stats import norm

CRITERIA = ("accuracy", "completeness", "objectivity", "sourcing")
# what every runner writes when a reply parses but breaks the rubric contract
RUNNER_INVALID = "Empty answer or invalid rubric result; raw output retained."


def read(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def usable(g, lenient):
    """The grade with any stray premise score dropped, or None if unusable."""
    error = g.get("error")
    if error is not None and not (lenient and error == RUNNER_INVALID):
        return None
    if any(type(g.get(k)) is not int or not 1 <= g[k] <= 5 for k in CRITERIA):
        return None
    if g.get("total") != sum(g[k] for k in CRITERIA) or type(g.get("hard_fail")) is not bool:
        return None
    premise = g.get("premise_handling")
    if str(g.get("question_type", "")).startswith("Loaded"):
        return g if type(premise) is int and 1 <= premise <= 5 else None
    if premise is None:
        return g if error is None else None
    return {**g, "premise_handling": None} if lenient else None


def frame(responses, judgments, lenient):
    answers = {a["id"]: a for a in responses
               if a.get("error") is None and (a.get("response") or "").strip()}
    # retried grades: as merge.py, a usable grade beats a failed one, then the latest wins
    best = {}
    for g in judgments:
        key = (g["id"], g["judge"], g.get("pass", 0))
        rank = (usable(g, lenient) is not None, g.get("ts") or "")
        if key not in best or rank >= best[key][0]:
            best[key] = (rank, g)
    rows = []
    for _, g in best.values():
        a = answers.get(g["id"])
        g = usable(g, lenient) if a else None
        if g is None:
            continue
        group = a.get("group") or "baseline"
        rows.append({
            "id": g["id"], "qid": a["qid"], "provider": a["provider"], "judge": g["judge"],
            "block": a.get("block"), "cue_type": a.get("cue_type"), "channel": a.get("channel"),
            "exemplar": a.get("exemplar") or "0", "group": group,
            "total": g["total"], **{k: g[k] for k in CRITERIA},
        })
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no usable grades of cue answers")
    race = df["group"].str.split().str[0]
    gender = df["group"].str.split().str[-1]
    df["race"] = race.map({"Black": 0.5, "White": -0.5})
    df["gender"] = gender.map({"woman": 0.5, "man": -0.5})
    df["edu"] = df["group"].map({"did not finish high school": 0.5, "doctorate": -0.5})
    df["channel_c"] = df["channel"].map({"memory": 0.5, "user": -0.5})
    return df


def formulas(outcome, one_question):
    q = "" if one_question else " + C(qid)"
    common = " + C(provider, Sum) + C(judge)" + q
    return {
        "vs baseline": (None, f"{outcome} ~ C(group, Treatment('baseline'))" + common),
        "race-gender": ("race_gender",
                        f"{outcome} ~ race * gender + race * channel_c + race * C(cue_type, Sum)"
                        " + race:C(provider, Sum) + channel_c * C(cue_type, Sum) + C(exemplar)" + common),
        "education": ("education",
                      f"{outcome} ~ edu * channel_c + edu * C(cue_type, Sum) + edu:C(provider, Sum)"
                      " + channel_c * C(cue_type, Sum) + C(exemplar)" + common),
    }


NUISANCE = re.compile(r"^(Intercept|C\((provider|judge|qid|exemplar)[^)]*\)\[[^]]*\])$")


def label(term):
    term = term.replace("channel_c", "channel")
    return re.sub(r"C\((\w+)(?:, \w+(?:\([^)]*\))?)?\)\[(?:S\.|T\.)?([^]]+)\]", r"\1=\2", term)


def omitted(fe, cov, data):
    """Sum coding leaves out one level per factor; its deviation is minus the
    sum of the others. Returns {term: (estimate, variance)} for each left out."""
    out = {}
    for factor in ("provider", "cue_type"):
        levels = sorted(data[factor].unique())
        for prefix in ("", "race:", "edu:", "channel_c:"):
            names = [f"{prefix}C({factor}, Sum)[S.{lv}]" for lv in levels[:-1]]
            if (factor, prefix) == ("provider", "") or len(levels) < 2 or not all(n in fe.index for n in names):
                continue
            out[f"{prefix}C({factor}, Sum)[S.{levels[-1]}]"] = (
                -fe[names].sum(), float(cov.loc[names, names].values.sum()))
    return out


def fit(df, formula, one_question):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mixed = smf.mixedlm(formula, df, groups=df["id"]).fit(reml=True)
    clusters = pd.factorize(df["id"] if one_question else df["qid"])[0]
    ols = smf.ols(formula, df).fit(cov_type="cluster", cov_kwds={"groups": clusters})
    notes = sorted({str(w.message).split("\n")[0] for w in caught})
    fe = mixed.fe_params
    est = {t: (fe[t], mixed.bse_fe[t] ** 2) for t in fe.index if not NUISANCE.match(t)}
    rob = {t: (ols.params[t], ols.bse[t] ** 2) for t in est}
    est |= omitted(fe, mixed.cov_params().loc[fe.index, fe.index], df)
    rob |= omitted(ols.params, ols.cov_params(), df)
    rows = []
    for t, (b, v) in est.items():
        rb, se, rse = rob[t][0], v ** 0.5, rob[t][1] ** 0.5
        rows.append({"term": label(t), "estimate": b, "se": se,
                     "ci_low": b - 1.96 * se, "ci_high": b + 1.96 * se, "p": 2 * norm.sf(abs(b / se)),
                     "robust_ci_low": rb - 1.96 * rse, "robust_ci_high": rb + 1.96 * rse,
                     "robust_p": 2 * norm.sf(abs(rb / rse))})
    # Benjamini-Hochberg across this model's reported terms
    for key, name in (("p", "q"), ("robust_p", "robust_q")):
        order = sorted(range(len(rows)), key=lambda i: rows[i][key])
        q, m = 1.0, len(rows)
        for rank, i in reversed(list(enumerate(order, 1))):
            q = min(q, rows[i][key] * m / rank)
            rows[i][name] = q
    # each left-out level next to its siblings
    family = [re.sub(r"=.*", "", r["term"]) for r in rows]
    rows = [r for _, r in sorted(enumerate(rows), key=lambda x: (family.index(family[x[0]]), x[0]))]
    return rows, {"answer_variance": float(mixed.cov_re.iloc[0, 0]),
                              "residual_variance": float(mixed.scale), "converged": bool(mixed.converged),
                              "warnings": notes}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("responses", type=Path)
    ap.add_argument("judgments", type=Path)
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--outcomes", default="total", help=f"comma-separated: total,{','.join(CRITERIA)}")
    args = ap.parse_args()
    responses, judgments = read(args.responses), read(args.judgments)

    results, fits = [], []
    for rule in ("strict", "lenient"):
        df = frame(responses, judgments, rule == "lenient")
        one_question = df["qid"].nunique() == 1
        for outcome in args.outcomes.split(","):
            for model, (block, formula) in formulas(outcome, one_question).items():
                data = df if block is None else df[df["block"] == block]
                rows, info = fit(data, formula, one_question)
                fits.append({"rule": rule, "outcome": outcome, "model": model, "grades": len(data),
                             "answers": data["id"].nunique(), "questions": data["qid"].nunique(), **info})
                results += [{"rule": rule, "outcome": outcome, "model": model, **r} for r in rows]

    out = pd.DataFrame(results)
    for (outcome, model), part in out.groupby(["outcome", "model"], sort=False):
        print(f"\n## {model}: {outcome}\n")
        wide = part.pivot_table(index="term", columns="rule", values="estimate", sort=False)
        strict = part[part["rule"] == "strict"].set_index("term")
        print("| term | strict | 95% CI | q | robust CI | robust q | lenient |")
        print("|---|---|---|---|---|---|---|")
        for term, r in strict.iterrows():
            print(f"| {term} | {r.estimate:+.2f} | {r.ci_low:+.2f} to {r.ci_high:+.2f} | {r.q:.3f} | "
                  f"{r.robust_ci_low:+.2f} to {r.robust_ci_high:+.2f} | {r.robust_q:.3f} | "
                  f"{wide.loc[term, 'lenient']:+.2f} |")
    print()
    for f in fits:
        flag = "" if f["converged"] and not f["warnings"] else f"  (check: {'; '.join(f['warnings']) or 'not converged'})"
        print(f"{f['rule']:7} {f['outcome']:12} {f['model']:12} {f['grades']:>7} grades "
              f"{f['answers']:>6} answers {f['questions']:>4} questions{flag}")
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        out.to_csv(args.out_dir / "cue_model.csv", index=False)
        (args.out_dir / "cue_model_fits.json").write_text(json.dumps(fits, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
