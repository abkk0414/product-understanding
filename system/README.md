# Evidence extraction system

For running the website from a fresh clone, start with the
[local website setup guide](../README.md), including its example configuration.

This directory implements the four-stage evidence pipeline for Python 3.12.
Claims remain immutable `CANDIDATE` records; verifier findings live in
`verdicts.json`, and human publication dispositions live in `reviews.json`.
The verifier never writes a publication disposition.

Install the pinned runtime:

```bash
python3.12 -m pip install -r system/requirements.txt
```

## Run the stages

Stage 1 — Detective/orchestrator. A new extraction uses `--product`; an
existing pack must use append-only `--topup`. Each attempt runs in
`system/staging/`, passes the deterministic gate there, and is atomically
promoted only when green. The Claude Agent SDK uses its normal Claude
authentication (for API usage, set `ANTHROPIC_API_KEY`).

```bash
python3.12 system/extract_orchestrator.py --product <product>
python3.12 system/extract_orchestrator.py --topup <product>
```

Stage 2 — Guard Dog:

```bash
python3.12 evidence-packs/validate.py
python3.12 scripts/validate_vault.py
```

Stage 3 — Verifier. Set `FAL_KEY` in the process environment; never place it
in repository files or command arguments. The pinned independent model is
`qwen/qwen3-vl-235b-a22b-instruct` through fal's OpenAI-compatible
`openrouter/router/openai/v1/chat/completions` route, prompt version `v2`.
The response's serving-model field must exactly match the requested model or
the run stops. No Claude/Anthropic model is permitted for this stage.

Version 2 verifies each claim once against the union of its exact quotes. It
projects away claim-schema scaffolding (for example procedure IDs, step
numbers, target-part IDs, and state IDs) and audits only semantic content.
Omission is allowed unless it drops a governing condition or direction and
thereby broadens the assertion. The claim-level result is repeated on text
binding rows for artifact compatibility; `basis: CLAIM_QUOTE_UNION` makes the
scope explicit.

```bash
python3.12 system/verify_claims.py
python3.12 system/verify_claims.py --product <product>
python3.12 system/verify_claims.py --product <product> --conflicts
```

Exit codes are `0` complete, `10` complete with `MEANING_CHANGED` alarms,
`20` partial, `30` provider/credential failure, and `40` malformed provider
output after retry. Exit `50` means the serving-model attestation was missing
or did not exactly match the pinned Qwen ID. Responses are cached under
`system/cache/` using claim ID, the ordered quote-hash union, semantic
projection hash, tier, model, endpoint, verification scope, and prompt
version. `verdicts.json` records the endpoint, serving model, estimated spend,
and provider-reported spend in `run_metadata`. The estimate uses the
documented model token prices; actual provider billing can differ. A five-pack
run is expected to stay within single-digit dollars. Stop if projected spend
would exceed that range.

Stage 4 — human queue:

```bash
python3.12 system/review_queue.py
python3.12 system/review_queue.py --product <product>
```

Queues are written as each pack's `review-queue.md`, ordered from semantic
alarms through conflicts, C3/C2, unresolved C0/C1 verification, gaps, and
C0/C1 batch-eligibility spot audits. The five-item sample is selected by a
stable SHA-256 rank and the complete eligible batch is listed in the queue.
Any new v2 `MEANING_CHANGED` alarm reopens an older human disposition and is
shown explicitly; a prior decision never causes a fresh alarm to disappear.
Humans record individual or explicitly confirmed batch decisions in
`reviews.json`; they do not edit claims or verdicts.

## Tests and live canary

The complete offline suite uses mocked providers and OS-temporary scratch
packs, never real pack mutation:

```bash
python3.12 -m compileall system/ evidence-packs/
python3.12 -m pytest -q system/tests
```

With a rotated `FAL_KEY` configured, the manual canary checks four known v1
noise cases, the three genuine defects from the owner spot-check, and exact
serving-model attestation:

```bash
python3.12 system/tests/live_canary.py
```

## Answer tool (serving preview)

`system/answer.py` answers a product question from the packs with citations —
purely lexical retrieval, no model calls, no network:

```bash
python3.12 system/answer.py "what is the max child weight for the snugride?"
python3.12 system/answer.py "how do I fold the stroller?" --preview
python3.12 system/answer.py "..." --product levoit-core-300s --top 5 --json
```

Serving policy: by default only `PUBLISHED` claims are answered — latest
human disposition `APPROVED_FOR_PUBLISH` with no outstanding
`MEANING_CHANGED` verdict. Approved claims under a live alarm are
`SUSPENDED`; unreviewed claims are `CANDIDATE`; both are hidden by default
and shown clearly labeled under `--preview`. `REJECTED_FOR_SERVING` claims
are never served. The tool reads `claims.json`, `reviews.json`, and
`verdicts.json` directly; the review pass immediately changes what it serves.

Current repository note: the Bose curated video index is registered as
`src_video_index`; the hardened vault validator is expected to pass all five
packs.

## Luna-assisted answer app

The local app uses two independently versioned `gpt-5.6-luna` turns: an
intent/tool planner before local evidence retrieval and a response-composition
planner after retrieval. The server validates every selected tool, procedure,
and media ID. Luna cannot create product facts or make an unpublished asset
eligible.

Create an OpenAI API Platform project key and expose it only to the server
process. Do not put the key in source files, browser code, command arguments,
or a committed `.env` file.

```bash
export OPENAI_API_KEY="your-project-key"
python3 app/server.py --reviewer owner@example.com
```

Without `OPENAI_API_KEY`, the same command starts normally and reports
`Luna planning: deterministic fallback (credentials_missing)`. Set
`SHOWME_LUNA_ENABLED=0` to force that mode. `SHOWME_LUNA_MODEL` and
`SHOWME_LUNA_TIMEOUT_SECONDS` provide explicit server-side overrides; the
defaults are `gpt-5.6-luna` and four seconds per turn.
