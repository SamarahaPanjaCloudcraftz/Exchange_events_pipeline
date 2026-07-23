# User Guide — Accessing the Dashboard

For whoever opens the live dashboard day to day (not a developer setup guide —
see [README.md](../README.md) for that). Covers the integrated dashboard once
this pipeline is deployed on the same server as the HARCJ dashboard, wrapped
into it as a second tab.

## Accessing it

The server has no public URL — access is SSH-tunnel-only, same as it's
always been for HARCJ. The integrated dashboard now uses **two** ports, so
the tunnel needs to forward both at once:

```bash
ssh -L 8501:127.0.0.1:8501 -L 8502:127.0.0.1:8502 <user>@<host>
```

- `8501` — HARCJ's existing Streamlit dashboard (unchanged port).
- `8502` — this pipeline's dashboard, loaded inside HARCJ's second tab via an
  iframe. If this port isn't forwarded too, the HARCJ tab still works fine,
  but the Exchange Events tab will show a broken/unreachable frame.

Once tunneled, open **`http://localhost:8501/`** in a browser — that's the
one and only URL. Everything below lives inside it.

## What you'll see

Two tabs in the same window:

1. **HARCJ** — the existing dashboard, exactly as before. Nothing about it
   changed.
2. **Exchange Events** — this pipeline's dashboard: exchange holidays, DST
   shifts, derivative expiries, and US economic releases, plus an alerts
   feed, tabbed by exchange (XCME/XNSE/XBOM/XKRX) with a Consolidated View.

## Alert severity, at a glance

| Severity | Meaning | Where it shows |
|---|---|---|
| INFO | Event is far enough out that no action is needed yet | Dashboard only |
| WARNING | Within 2 days (1 day for expiries, which have no CRITICAL tier) | Dashboard + Teams |
| CRITICAL | Within 1 day | Dashboard + Teams + Email |

Each alert's title names what's happening, when, and which exchange/
underlying/country it applies to. The alerts card has a "show next N days"
filter (default 1) and, on the calendar, an Upcoming/All-dates toggle.

## Something looks wrong?

- **Exchange Events tab is blank/unreachable, HARCJ tab is fine** — almost
  always the tunnel missing the `-L 8502:127.0.0.1:8502` forward above.
- **Data looks stale** — the pipeline re-fetches on its own schedule (every 6h)
  and re-evaluates alerts every 15 minutes; it isn't tied to page refreshes.
- **Anything else** — see [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
  §6 (post-deploy verification) or [DECISIONS.md](DECISIONS.md) for why any
  particular behavior is the way it is.
