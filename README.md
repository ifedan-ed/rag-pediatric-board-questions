# Retrieval-augmented generation and language model accuracy on pediatric board-style questions

Code and answer-level data for the paper "Retrieval-Augmented Generation and Large Language Model Accuracy on Pediatric Board-Style Questions: Paired Evaluation of 10 Models With a Context-Utilization Check and Cost Analysis" (JMIR AI, under review).

Ten language models answered the same 300 multiple-choice questions twice: once directly and once with passages retrieved from pediatric reference texts. Retrieval did not improve accuracy.

## Contents

| Folder | What it holds |
| --- | --- |
| `data/answers.csv` | Every answer (18,000 rows): run, condition, model, study question number, question bank edition, letter chosen, whether it was read by rule or by hand, correct or not, tokens, cost, provider, and the source documents of the retrieved passages |
| `data/retrieval_november_2026.csv` | The repeated retrieval used for the passage audit and the control runs: source documents of the passages for each question, in rank order |
| `data/passage_audit.csv` | Relevance and sufficiency ratings of the retrieved passages for all 300 questions, with a second rating for 60 |
| `results/` | The tables and summary statistics reported in the paper |
| `code/` | Generation runner, statistical analysis and audit analysis scripts |
| `prompts/prompts.md` | Exact system and user prompts |
| `faithfulness_check/` | The context-utilization check (29 August 2026): each model was given an invented framework, the "Danvics-Okafor criteria", and asked a question only it answers. `check.md` has the method and results, `log.md` the probe script and every model's full answer |
| `config/` | Gateway configuration for the 10 study models (provider-pinned, no fallback, temperature 0) |

## Runs

| `run` | `condition` | What it is |
| --- | --- | --- |
| `august_2026` | `direct`, `retrieval` | The main comparison, generated on 29 August 2026 |
| `november_2026_repeat1`, `november_2026_repeat2` | `direct` | Two repeats of the direct condition, to measure run-to-run change |
| `november_2026` | `retrieval_original_prompt_stored_passages` | The retrieval condition rerun with the original prompt on stored passages |
| `november_2026` | `retrieval_no_prefer_instruction` | The same passages without the instruction to prefer them |

## What is not included

Question stems, answer options, answer explanations, the models' full replies and the text of retrieved passages are not included. The questions come from a subscription question bank (American Academy of Pediatrics PREP Self-Assessment), and the passages from copyrighted reference texts. Questions are identified only by a study number and the question bank edition. Source documents are identified by number. The paper's Multimedia Appendix 3 lists the corpus.

The analysis scripts document exactly what was run. Because they read the question bank, they cannot be run without it, but every reported statistic can be recomputed from `data/answers.csv`.

## Statistics

Accuracy uses Wilson 95% confidence intervals, and paired differences use Newcombe intervals. Each model is compared with itself using exact McNemar tests with Bonferroni adjustment. The pooled comparison uses generalized estimating equations (binomial, logit link, exchangeable correlation, clustered on question). Analysis used Python with statsmodels and SciPy.

## Licence

Code: MIT. Data: CC BY 4.0.
