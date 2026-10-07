# Vozonda quality rubric

Used by the benchmark for every Vozonda run and every NotebookLM reference, so
both are judged on the same scale. Builds on the podcast-studio expressivity
work (tests/expressivity, kb/back-channels.md, kb/repair-templates.md,
sovereign-kb/mistral-overuse-phrases.md) instead of starting over.

Three layers: automatic script metrics, automatic audio metrics, and a judged
score. The human ear (blind A/B, H+/H0/H−) stays the final verdict; the
numbers only decide what is worth listening to.

## A. Script metrics (automatic, from the script or the reference transcript)

| id | what | target (NotebookLM-like dialog) |
|---|---|---|
| words | spoken words | report only |
| turns | speaker turns | report only |
| turn_len_mean / turn_len_cv | words per turn, coefficient of variation | CV >= 0.8 (mix of one-word reactions and long explanations; a lecture has CV < 0.5) |
| short_turn_share | turns with <= 4 words | 0.15 - 0.35 |
| question_share | turns containing "?" | 0.12 - 0.25 |
| speaker_balance | words of the less talkative host / more talkative | 0.4 - 1.0 |
| bc_distinct | distinct back-channels from kb/back-channels.md | >= 3, never the same one twice in a row, no bare "Mhm." |
| repair_count | repair sequences (kb/repair-templates.md patterns) | 1 - 3 |
| overuse_hits | phrases from sovereign-kb/mistral-overuse-phrases.md | 0 |
| markup_hits | [tags], (stage directions), SSML/HTML, *emphasis*, ALL-CAPS > 6 letters | 0 (unless the engine declares paralinguistic tags) |
| hook_words | words before the first concrete claim from the source | <= 40 |

## B. Audio metrics (automatic, from the final mp3)

| id | what | target |
|---|---|---|
| duration_s | length | report only |
| lufs_i / true_peak / lra | ffmpeg ebur128 | -16 LUFS +- 1, true peak <= -1.5 dBFS, LRA <= 11 (style_base.yaml) |
| wpm | spoken words per minute (whisper word timestamps) | 150 - 185 |
| gap_median_ms / gap_p90_ms | silence between speech segments | median 150 - 400, p90 < 900; a fixed gap everywhere = robotic |
| gap_cv | variation of gaps | >= 0.5 (turn-taking is irregular in real talk) |
| wer | whisper transcript vs script (Vozonda runs only) | < 0.08; higher = mispronunciation, skipped or hallucinated words |

## C. Judged score (LLM judge, 1-10 each, with one-sentence reasons)

The judge gets the source text (excerpt) and the transcript, never the engine
or model name.

1. **Hook**: would a stranger keep listening after 20 seconds?
2. **Grounding**: every claim traceable to the source; invented facts are a hard fail (score 1 and list them).
3. **Explanation**: complex points made simple with an example or analogy, without dumbing down.
4. **Dialogue dynamics**: hosts react to each other, ask real questions, disagree or build on each other; not two people taking turns reading.
5. **Arc**: clear shape (setup, turns, payoff) and an ending that lands instead of a summary.
6. **Naturalness**: sounds like people talking (contractions, reactions, a repair or two), not like written prose.

Total = mean of the six, reported next to the reference's total for the same source.

## D. Human verdict (blind)

Per source, the listener hears Vozonda and reference without labels and marks
each H+ (NotebookLM-like, want it), H0 (flat), H− (broken) plus a 1-5 note.
That scale is the one from tests/expressivity/v2_en/EVALUATION_V2.md.
