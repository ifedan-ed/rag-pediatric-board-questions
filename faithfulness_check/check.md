# Context-utilization check

A check that the models read the passages supplied with a question and let them change the answer. Run on 29 August 2026 through the study gateway, each model on its named provider at temperature 0.

## Method

Each model was asked one question with a reference block describing an invented clinical framework:

> The Danvics-Okafor criteria are the accepted framework for grading paediatric asthma exacerbations. Under these criteria an exacerbation is classified as severe when the room-air oxygen saturation falls below 93 percent, which is the Danvics-Okafor threshold for escalation.

The question asked at what room-air oxygen saturation a paediatric asthma exacerbation is classified as severe, and what that threshold is called.

The name and the threshold do not exist outside this check, so a model can give them only by reading the supplied text. The system prompt was the study's retrieval prompt, unchanged, including the instruction to prefer the supplied context over the model's own knowledge.

## Results

All 11 models used the invented name, and 10 of 11 also gave the invented 93 percent threshold.

| Model | Provider | Invented name | Invented threshold |
| --- | --- | --- | --- |
| gpt-5.6-sol | openai | yes | yes |
| claude-haiku-4.5 | anthropic | yes | yes |
| gemini-3.7-flash | google-ai-studio | yes | yes |
| mistral-large-2512 | mistral/eu | yes | no (gave 92 percent) |
| llama-3.3-70b-instruct | deepinfra | yes | yes |
| gemini-3.5-flash-lite | google-ai-studio | yes | yes |
| mistral-small-2603 | mistral/eu | yes | yes |
| phi-4 | deepinfra | yes | yes |
| deepseek-v4-flash-0731 | deepinfra/fp8 | yes | yes |
| gpt-5.4-nano | openai | yes | yes |
| granite-4.1-8b | coreweave/bf16 | yes | yes |

granite-4.1-8b was included in this check but is not one of the 10 models in the study.

## Limits

The check shows that the models follow supplied text when it directly answers the question. It does not show whether the passages retrieved for the study questions were relevant or sufficient; that was assessed separately (`data/passage_audit.csv`).

## Files

`log.md` has the probe script and every model's full answer.
