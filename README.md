# Fundo AI Reviewer

An LLM reviewer for a legacy keyword engine that labels bank transactions for
revenue-based advance underwriting, plus the credit impact of its corrections.
Read `SOLUTION.md` first; this file is only how to run it.

## Requirements

- Python 3.10+ (tested on 3.12). Replaying from cache uses only the standard library.
- To call the model: the `anthropic` package and `ANTHROPIC_API_KEY`.

## Re-generate the output from the cache (no API key)

```bash
python src/run.py --offline
python -m unittest discover -s tests -v
```

`--offline` never touches the network. Every model response lives in `cache/`, keyed by
a hash of model + prompt version + system prompt + exact request, so the output in
`output/report.md` and `output/results.json` is reproduced byte for byte.

## Full run (calls Claude only for cache misses)

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...      # PowerShell: $env:ANTHROPIC_API_KEY = "..."
python src/run.py
```

To force fresh model calls, delete `cache/` (or change `PROMPT_VERSION` in
`src/reviewer.py`). A full run costs about US$0.50 with `claude-opus-5-5`.
`REVIEWER_MODEL=<model id>` runs another model; it gets its own cache entries.

## Review transactions you bring (no ground truth needed)

```bash
python src/run.py --input path/to/transactions.json
```

Accepts a Plaid `/transactions/get` response, a bare list of Plaid transactions (grouped by
`account_id`, one account = one business), or this repo's format. Writes
`output/input_report.md`: offers with legacy vs reviewed labels and the underwriter queue.
New data means new model calls, so this needs `ANTHROPIC_API_KEY`. The bundled example
replays from cache: `python src/run.py --offline --input examples/sample_input.json`.

## Experiments (model choice, Plaid-category ablation)

```bash
python src/experiments.py --offline   # -> output/experiments.md
```

## Individual steps

```bash
python src/generate_data.py   # rebuilds data/ (deterministic, seed 7)
python src/keyword_engine.py  # legacy engine accuracy per business vs truth
```

## Layout

```
src/taxonomy.py        13 groups, the revenue rule (shared by everything)
src/generate_data.py   synthetic Plaid-format data + ground truth
src/keyword_engine.py  deliberately imperfect legacy labeler
src/reviewer.py        patterns, prompt, Claude call, cache, validation, decision gates
src/evaluate.py        scoring vs truth: dollars, hard negatives, adversarial, mistakes
src/credit_impact.py   features, offer rule, mislabel simulation
src/run.py             one command for all of the above (+ --input for new data)
src/experiments.py     Opus vs Haiku, with/without Plaid category
data/                  transactions.json (what the system sees), truth.json (evaluation only)
cache/                 committed model responses
output/                report.md, results.json
tests/                 unit tests + offline reproducibility test
examples/              an unseen business in raw Plaid shape (61 days)
```
