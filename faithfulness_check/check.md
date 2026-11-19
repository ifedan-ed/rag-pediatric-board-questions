# Retrieval faithfulness check

Evidence that the RAG arm genuinely influences what the models write, rather
than the retrieved context being fetched and then ignored. Run 29 August 2026
against the study gateway, every model pinned to its named provider at
temperature 0.

---

## Why this check exists

The pilot showed almost no accuracy difference between the direct and RAG arms.
There are two very different explanations for that, and they lead to opposite
conclusions:

1. **The pipeline is broken.** Retrieval fails, or the passages never reach the model, so the RAG arm is silently identical to the direct arm. That would be a defect, and any finding drawn from it would be worthless.
2. **The pipeline works and the corpus simply does not help.** Retrieval fires, the model reads the passages, and they do not change the answer to a board-style question the model could already answer. That is a genuine result and is publishable.

Retrieval counts and prompt sizes cannot separate these two, because both are
consistent with a model that receives context and disregards it. A positive
control can.

## Method

Each model was sent one question together with a reference block containing a
**deliberately invented** clinical framework:

> The **Danvics-Okafor criteria** are the accepted framework for grading
> paediatric asthma exacerbations. Under these criteria an exacerbation is
> classified as severe when the room-air oxygen saturation falls below
> **93 percent**, which is the Danvics-Okafor threshold for escalation.

The question asked at what saturation an exacerbation is classified as severe,
and what that threshold is called.

Neither the name nor the threshold exists. They appear in no textbook, no
guideline and no training corpus, because they were invented for this test. A
model can only reproduce them by reading the supplied context. Real practice
uses different cut-offs, so a model relying on prior knowledge would answer
differently.

The system prompt was the study's own RAG prompt, unmodified, including the
instruction to prefer retrieved context over the model's own knowledge.

## Result

**11 of 11 models adopted the invented framework name. 10 of 11 also adopted
the invented 93 percent threshold.**

| model                    | provider         | used invented name | used invented threshold |
|--------------------------|------------------|--------------------|-------------------------|
| `gpt-5.6-sol`            | openai           | yes                | yes                     |
| `claude-haiku-4.5`       | anthropic        | yes                | yes                     |
| `gemini-3.7-flash`       | google-ai-studio | yes                | yes                     |
| `mistral-large-2512`     | mistral/eu       | yes                | **no**                  |
| `llama-3.3-70b-instruct` | deepinfra        | yes                | yes                     |
| `gemini-3.5-flash-lite`  | google-ai-studio | yes                | yes                     |
| `mistral-small-2603`     | mistral/eu       | yes                | yes                     |
| `phi-4`                  | deepinfra        | yes                | yes                     |
| `deepseek-v4-flash-0731` | deepinfra/fp8    | yes                | yes                     |
| `gpt-5.4-nano`           | openai           | yes                | yes                     |
| `granite-4.1-8b`         | coreweave/bf16   | yes                | yes                     |

The single exception, `mistral-large-2512`, used the invented framework name
but stated a different saturation figure, so it read the context and partly
overrode it.

## Supporting evidence

Measured across the pilot cohort:

| observation                                     | value        |
|-------------------------------------------------|--------------|
| mean prompt tokens, direct arm                  | 461          |
| mean prompt tokens, RAG arm                     | **3,377**    |
| mean passages retrieved, RAG arm                | 7.05         |
| RAG answers with zero passages                  | **0**        |
| direct/RAG pairs compared                       | 3,248        |
| pairs where the two answers were byte-identical | **0**        |
| mean word overlap between arms                  | 0.32 to 0.43 |

Every RAG generation received passages, RAG prompts are roughly seven times
larger, and no RAG answer was ever identical to its direct counterpart.

## A weaker test that did not settle it

Before this probe, corpus vocabulary overlap was compared between arms: for
each question, what fraction of an answer's substantive words also appear in
the retrieved passages.

|                                    | direct answers | RAG answers |
|------------------------------------|----------------|-------------|
| mean overlap with retrieved corpus | 0.489          | 0.507       |

Only 4 percent higher for the RAG arm, and on two of five questions the direct
answer overlapped more. This measure is too blunt to be informative: roughly
half the vocabulary of any pediatric answer already appears somewhere in eight
textbook passages, so there is little headroom to discriminate. It is recorded
here so the negative result is not rediscovered later and misread as evidence
that RAG is inert.

## Interpretation

Explanation 1 is ruled out. Retrieval fires on every RAG generation, the
passages reach the model, and the model demonstrably follows them — to the
point of reproducing a fabricated criterion in preference to real clinical
knowledge.

The flat accuracy is therefore a finding about the corpus and the task, not a
defect in the software. This matches the published comparator: the pediatric
cardiology study found a single-textbook RAG pipeline did not significantly
change performance for any of eight models, while a study using Llama 3.2 —
a much weaker model with far more headroom — found RAG helped substantially.

## Caveat

This probe shows models follow context that directly answers the question
asked. It does not establish that they use context well when the retrieved
passages are only tangentially relevant, which is the realistic case for most
board-style questions. It is a positive control for the plumbing, not a
measure of retrieval quality.

## Reproducing

The probe script and the full untruncated answers from all 11 models are in
`log.md` alongside this note.