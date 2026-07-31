# Gather pilot showcase

An offline, self-contained example of the Gather pilot evidence engine. Run it
from this directory (the repository root works too):

```text
python -m gather pilot run examples/pilot/showcase-offline.json --output .tmp-showcase --json
```

Then refresh the monitored source and re-verify:

```text
python -m gather pilot refresh .tmp-showcase --json
python -m gather pilot refresh .tmp-showcase --json
python -m gather pilot verify .tmp-showcase --json
```

## What you should observe

The showcase monitors the `portfolio-watch` web source, which has an initial
fixture (`venture/portfolio-v1.html`) and a refresh fixture
(`venture/portfolio-v2.html`) that changes one product status.

- The **initial run** reports a monitor count of `NEW: 1` (first observation).
- The **first refresh** reports `CHANGED: 1` (the portfolio status moved from
  `seed` to `series-a`). The prior report and receipt are archived under
  `history/0001-*` and a new current view is written.
- The **second refresh** reports `UNCHANGED: 1` (the refresh fixture is
  identical to the prior observation). Another history triplet is archived.

`verify` returns `ok: true` after each step. Open `report.html` in a browser to
see the self-contained evidence view (no remote requests, no unescaped markup,
no private target).

## Packaging a shareable bundle

```text
python -m gather pilot bundle .tmp-showcase --output showcase-shared.zip --visibility shared
```

The shared bundle carries only the public surfaces (report, receipt, manifest
digest, bundle receipt). A full bundle adds the corpus, monitor state, and
history and requires `--include-private-evidence`.

## Files

- `showcase-offline.json` — the closed manifest (three missions, six adapters).
- `showcase-live.json` — a controlled-live template (not part of offline CI).
- `fixtures/` — original synthetic content with fictional names and reserved
  example domains. No real person, customer, or secret.
- `sample/` — a checked-in redacted sample regenerated from the offline
  showcase. `tests/test_pilot_sample.py` pins it against regeneration drift.

Remove the temporary root when done (`.tmp-showcase` is gitignored).
