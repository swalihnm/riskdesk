# Judge labelling guide

Purpose: a human decides whether each cited policy passage supports the claim beside it. The keyword judge's answer is then compared with the human answer, and the agreement (Cohen's kappa) is reported.

## What to do
1. Open `evals/judge_labels.csv` in a spreadsheet.
2. Read the `claim`, the `classification` and the `passage` on each row.
3. Fill `human_label` with exactly one of:
   - `SUPPORTED` if the passage states how a case of that classification should be handled.
   - `NOT_SUPPORTED` if it does not. A passage about a different kind of case, a past incident, or a general fact is not support.
4. Fill `human_reviewer` with your name.
5. Save as CSV and run `python evals/judge.py --kappa`.

Label all 75 rows. Some rows are negative controls: the passage is deliberately from a different kind of case. Judge each one on its text, not on the fact that it is a control.

## Rules of thumb
- Support means the passage governs handling of this case type. A passage that mentions a related word is not enough.
- "Data" or "limit" appearing in the passage does not make it support a data issue or a limit error.
- If you are unsure, choose `NOT_SUPPORTED` and note why in your head; disagreements are informative.

## What the file contains
- `automated_label` and `automated_reviewer` hold an automated reviewer's labels. They are not human labels and are kept separately on purpose.
- `judge_label` is the rule-based judge's answer.
- `human_label` and `human_reviewer` are for you.

Do not copy the automated labels into the human columns. Their agreement with the judge is already reported, and copying would make the human result meaningless.

## Time
About 30 minutes for 75 rows, because each cited passage is shared by many rows.
