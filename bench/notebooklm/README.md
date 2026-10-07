# NotebookLM comparison test

The "done" test of the source tray (`docs/plan-multisource-tray.md`, section 6): the same
three trays go through NotebookLM and through Vozonda; the operator listens to both.

## Run it

1. `python3 make_screenshots.py` (only if the PNGs are missing; the output is the same every time).
2. **Vozonda:** for each tray in `trays.json`, add the sources in the given order and roles,
   default style and length, press make it talk. Note the job id.
3. **NotebookLM** (operator, own Google account): a new notebook per tray with the same
   sources, Audio Overview with default settings. Download the audio.
4. Listen to both, blind if possible (someone else names the files A/B).

## Score per tray

| Question | A | B |
|---|---|---|
| Closer to the sources (nothing invented, nothing important missing) | | |
| Nicer to listen to | | |
| Easier to get there (setup, waiting, errors) | | |

Measured on the Vozonda side, from the job and the tray:

- **time to start:** first source pasted -> make it talk pressed
- **errors caught before start:** red cards with a hint vs. failures during the run
- **cited lines:** share of script lines with a valid `[n]`, and how many of 20 random
  cited lines really come from that source (check by hand)
- **condensing:** T2's paper must show `condensed` in the extract stage, not a cut

The result goes into `docs/archive/internal/quality-log.md` with the date, the commit and
both audio files' paths; repeat after any bigger change to the tray or the script prompts.
