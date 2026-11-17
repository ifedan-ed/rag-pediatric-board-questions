"""Build Multimedia Appendix 5 (xlsx): hand-read answers, passage audit by question,
per-model control-condition results. Contains no question, option, key or passage text."""
import json, glob, pandas as pd
P = 'data/private'
q = {x['qid']: x for x in json.load(open(f'{P}/questions.json'))}
key = lambda qid: q[qid]['answer_key'].upper()

# Hand-read answers: August (selected_source == manual) and November (manual_letters.json).
rows = []
for g in json.load(open(f'{P}/august_generations.json')):
    if g['selected_source'] == 'manual':
        rows.append({'run': 'August 2026', 'condition': 'direct' if g['arm'] == 'direct' else 'retrieval',
                     'model': g['model'], 'question id': g['qid'], 'edition': q[g['qid']]['edition'],
                     'letter read': g['selected'], 'correct': int(g['selected'].upper() == key(g['qid']))})
names = {'gen_direct_r2': 'direct repeat 1', 'gen_direct_r3': 'direct repeat 2',
         'gen_rag_noprefer_r1': 'retrieval without prefer instruction',
         'gen_rag_replay_r1': 'retrieval with original prompt (stored passages)'}
for k, v in json.load(open(f'{P}/out/manual_letters.json')).items():
    run, m, qid = k.split('|'); qid = int(qid)
    rows.append({'run': 'November 2026', 'condition': names[run], 'model': m, 'question id': qid,
                 'edition': q[qid]['edition'], 'letter read': v, 'correct': int(v.upper() == key(qid))})
A = pd.DataFrame(rows).sort_values(['run', 'condition', 'model', 'question id'])

# Passage audit: primary rating for all 300, second rating for 60. Rater notes are left out
# because they paraphrase passage content.
lab = {2: 'relevant', 1: 'partly relevant', 0: 'irrelevant'}
prim = [r for f in sorted(glob.glob(f'{P}/audit/ratings/primary_*.json')) for r in json.load(open(f))]
sec = [r for f in sorted(glob.glob(f'{P}/audit/ratings/second_*.json')) for r in json.load(open(f))]
B = pd.DataFrame([{'question id': r['qid'], 'edition': q[r['qid']]['edition'], 'passages': len(r['passages']),
                   'relevant': r['passages'].count(2), 'partly relevant': r['passages'].count(1),
                   'irrelevant': r['passages'].count(0),
                   'rating by passage (P1, P2, ...)': '; '.join(lab[p] for p in r['passages']),
                   'sufficient to identify key': r['sufficient'], 'a passage supports key': r['supports_key'],
                   'passages support another option': bool(r['supports_other'])} for r in prim])
S = pd.DataFrame([{'question id': r['qid'], 'second rater: sufficient': r['sufficient'],
                   'second rater: supports key': r['supports_key'],
                   'second rater: supports another option': bool(r['supports_other']),
                   'second rater: by passage': '; '.join(lab[p] for p in r['passages'])} for r in sec])
B = B.merge(S, on='question id', how='left').sort_values('question id')

def tidy(df):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == float:
            df[c] = df[c].round(3 if c in ('p', 'p_bonferroni') else 1)
    return df

res = 'analysis/results/'
readme = pd.DataFrame({'Multimedia Appendix 5': [
    'Hand-read answers, passage audit ratings by question, and per-model results of the control conditions.',
    'No question text, answer options, answer keys, explanations or passage text are included (copyright).',
    'Question id: study item number. Edition: edition of the question bank.',
    'Hand-read answers: replies whose option letter could not be read by the fixed rule, with the letter read from the answer text.',
    'Passage audit: primary rating of the passages for all 300 questions; second independent rating for 60.',
    'Control sheets: per-model accuracy (%, Wilson 95% CI), paired difference in percentage points (Newcombe 95% CI), broken and corrected answers, exact McNemar P and Bonferroni-adjusted P.']})
sheets = {'Read me': readme, 'Hand-read answers': A, 'Passage audit': B,
          'Repeat direct': tidy(pd.read_csv(res + 'repeat_direct_runs.csv')),
          'Retrieval, no prefer': tidy(pd.read_csv(res + 'table_noprefer.csv')),
          'Retrieval, replay': tidy(pd.read_csv(res + 'table_rag_replay.csv')),
          'Prefer vs no prefer': tidy(pd.read_csv(res + 'table_prefer_vs_noprefer.csv'))}
with pd.ExcelWriter('revision/supporting/Multimedia Appendix 5.xlsx', engine='openpyxl') as w:
    for name, df in sheets.items():
        df.to_excel(w, sheet_name=name, index=False)
        s = w.sheets[name]
        for col in s.columns:
            s.column_dimensions[col[0].column_letter].width = min(70, max(10, max(len(str(c.value or '')) for c in col) + 2))
print(A.groupby(['run', 'condition']).size().to_string())
