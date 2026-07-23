# Real Deployment Log

Chronological, running log of the **actual** deployment of this pipeline onto
the real production server (`CloudCraftz_2`, root SSH access) and its
integration with the existing HARCJ dashboard already running there. Kept
separate from [PROGRESS_LOG.md](PROGRESS_LOG.md) (that one tracks building
*this codebase*; this one tracks getting it live on the real box and wired
into HARCJ). Appended to as each step happens — not written after the fact.

---

## 2026-07-23 — Dashboard integration design + local proof

**Decision: embed, don't rewrite.** Considered rewriting this pipeline's
dashboard in Streamlit so it could live inside HARCJ's own `app.py` process,
vs. keeping it as a fully separate Flask process and embedding it as a tab
via an iframe. Chose **embed** — a Streamlit rewrite would run inside HARCJ's
own Python process (shared memory, shared venv, shared dependency pins:
`streamlit>=1.44,<1.51`, `pandas<2.3`, etc.), reopening exactly the
process/dependency isolation risk this whole deployment has been designed
around: a bug on our side could crash HARCJ's dashboard too, and our
dependencies would need installing into their pinned venv. Embedding via
`st.components.v1.iframe()` keeps the two fully separate — HARCJ's Streamlit
process never imports our code, shares no memory, no venv, no dependencies
with it.

**Local implementation + proof, against a local replica of the real HARCJ
codebase** (`harcj_dashboard/dashboard_new`, kept as an exact copy for exactly
this kind of testing):
- Added `app_new.py` **alongside** the existing `app.py` (per explicit
  instruction — the original file is never edited in place). Only change:
  one new "Exchange Events" tab added to the existing `st.tabs([...])` call,
  rendering `components.iframe(EXCHANGE_EVENTS_URL, height=1400,
  scrolling=True)` where `EXCHANGE_EVENTS_URL` defaults to
  `http://127.0.0.1:8080` (overridable via env var).
- Verified end-to-end with a real headless browser (Playwright): started our
  real gunicorn+wsgi.py server on `127.0.0.1:8080` and the modified Streamlit
  app on a separate port, drove it with an actual browser, confirmed via the
  page's own frame list that the iframe loaded `http://127.0.0.1:8080/`
  (not a broken/blocked frame), and screenshotted both tabs: the original
  "Dashboard" tab renders unchanged, the new "Exchange Events" tab shows our
  full dashboard (calendar, exchange sub-tabs, alerts) live inside the frame.
- All test processes/venvs/artifacts cleaned up afterward; the real
  `exchange_events_pipeline` and HARCJ replica repos were confirmed
  untouched/clean apart from the one new `app_new.py` file (the HARCJ replica
  did have substantial *pre-existing* uncommitted changes unrelated to this
  session — noted, not touched).

**Operational note for later:** since the iframe's `src` is resolved by the
*browser*, not the server, viewing the integrated dashboard over the real
SSH tunnel needs both ports forwarded, not just Streamlit's:
```bash
ssh -L 8501:127.0.0.1:8501 -L 8080:127.0.0.1:8080 <user>@<host>
```
Already documented in [USER_GUIDE.md](USER_GUIDE.md).

## 2026-07-23 — Real server recon

First real SSH session against the production box (`CloudCraftz_2`). Findings:

- **Access:** logged in as `root`, passwordless `sudo` available.
- **OS:** CentOS 7 (`/dev/mapper/centos-root`), `systemd 219` (~2014-era —
  `systemd-analyze calendar` doesn't even exist as a subcommand on this
  version, so our timers' `OnCalendar=` step syntax (`0/6`, `0/15`) can't be
  pre-verified with that tool; will confirm via `systemctl list-timers`'
  computed "NEXT" time right after installing instead).
- **Port 8080:** free. Only `127.0.0.1:8501` (HARCJ's real Streamlit port,
  confirming the prose description — the local replica's `8502` was just a
  test-local artifact) is listening.
- **`/opt`:** exists, essentially empty (just an old `rh` dir), 378G free —
  fine as the install location (`/opt/exchange-events`).
- **The crontab is far more crowded than described** — not just the one
  HARCJ line, but several unrelated teams' jobs: live-monitoring uploaders
  and alert systems for NSE/BSE/CME, a recon-data OneDrive upload, broker
  report automation (`ayush`'s scripts), CME preprocessing, plus the HARCJ
  scheduler restart. This **strongly confirms** the earlier decision to use
  systemd timers instead of adding a crontab line — this file is shared,
  actively used by multiple unrelated projects, and hand-editing it would be
  genuinely risky.
- **Python version blocker:** system `python3` is 3.6.8 (CentOS 7's ancient
  distro package) or 3.9.18 depending on `PATH` order; `/usr/local/bin/
  python3.9` is a manually-installed interpreter that several existing
  live-monitoring cron jobs already depend on (`/usr/local/bin/python3` in
  their shebangs/invocations) — **must not be touched or upgraded**. This
  pipeline requires Python `>=3.11`. No Red Hat Software Collections (`scl -l`
  empty, `/opt/rh` empty) and no newer Python available via `rpm -qa`.
  `/root/miniconda3` is on `PATH` but **doesn't actually exist** (stale PATH
  entry) — dead end. Internet egress from the box does work (confirmed via
  `curl` to python.org), so fetching a self-contained Python build is viable.
- **Status: blocked on getting a compliant Python 3.11+ runtime onto this box
  without touching the existing 3.6/3.9 installs.** Next candidate: install
  `uv` (a single static binary, same team as `ruff` which this project
  already uses) and use `uv python install 3.11` to fetch a fully
  self-contained interpreter with no system dependencies, no compiler
  needed, no interaction with the existing Python installs.

**Still open / next steps:** resolve the Python runtime, then proceed with
`scripts/bootstrap_server.sh` (adjusted to point at whatever Python 3.11
ends up available), fill in `.env` secrets, verify the web service + timers,
confirm HARCJ is completely undisturbed, then wire `app_new.py`'s tab into
the real (not replica) HARCJ `app.py` on the server.

## 2026-07-23 — Python 3.11 resolved (no download needed)

Attempted the `uv`-based fallback (installing `uv` itself first via `pip
install --user uv`, since `curl | sh` from `releases.astral.sh` was measured
at ~6.5KB/s — would've taken 40+ minutes — while PyPI delivered a larger
wheel in 43s; that CDN edge is specifically throttled from this box, not
general internet). Before letting `uv python install 3.11` attempt its own
(possibly equally slow) download, ran it anyway to see what it would do --
turned out **a real Python 3.11.15 was already sitting at
`/root/.local/bin/python3.11`** (self-contained, `uv python list` confirms
it's a proper standalone build under `.local/share/uv/python/`), left over
from some earlier, unrelated setup on this box. `uv` just verified and
registered it; nothing was downloaded this round. Confirmed functional
directly (`--version`, a real interpreter invocation).

**Resolved:** `/root/.local/bin/python3.11` is what `bootstrap_server.sh`
will use (`PYTHON=/root/.local/bin/python3.11`), fully isolated from the
system's `python3.6.8` and the existing `/usr/local/bin/python3.9` other
cron jobs depend on.

**Next:** clone the repo into `/opt/exchange-events`, run
`bootstrap_server.sh` with that Python, fill in `.env`, verify.

## 2026-07-23 — Project directory + root-vs-dedicated-user decision

User created the project directory at `/root/cloudcraftz/harcj_dash/exchange_event_pipeline`
— alongside HARCJ's own `dashboard_new`, under the same parent. Flagged a
real conflict before anything was cloned there: `/root` is mode `700` (root
only), and this pipeline's design so far assumed a dedicated, unprivileged
`exchange-events` system user running the web service and cron jobs — that
user would be unable to reach anything under `/root` (working directory,
`.env`, venv, all of it). HARCJ's own processes never hit this because they
already run as root.

**Decision (explicit, host-specific):** keep the project directory under
`/root/cloudcraftz/harcj_dash/` as the user wanted, and run this pipeline's
systemd units **as root** too, matching HARCJ's existing model on this box,
rather than relocating everything to `/opt` to preserve a dedicated
low-privilege user. Trade-off accepted knowingly: this pipeline's blast
radius is now "root on a shared production box" rather than "one isolated
low-privilege account" if its code were ever compromised. The alternative
(move to `/opt/exchange_event_pipeline`, keep the dedicated user) was
offered and declined in favor of matching the existing convention.

**Consequence, and a simplification it produces:** since everything now runs
as root, the earlier plan to relocate the standalone Python 3.11 interpreter
out from under `/root/.local/...` (because a non-root service user couldn't
reach it) is no longer needed — root can read `/root/.local/bin/python3.11`
directly. One less step.

**Changes made:**
- `scripts/bootstrap_server.sh` — removed the `useradd`/dedicated-user logic
  entirely; directories/`.env` are created root-owned; `init-db` runs
  directly instead of via `sudo -u`.
- `deploy/systemd/exchange-events-{web,ingest,alert}.service` — removed
  `User=`/`Group=` (systemd defaults to root when unset), with a comment
  explaining why, pointing back here.
- `scripts/redeploy.sh` / `scripts/rollback.sh` — dropped the `sudo` prefix
  on `systemctl restart` (this server operates as root directly already).
- All changes verified: `bash -n` on all three scripts, `systemd-analyze
  verify` on the web unit (clean parse, only the expected "gunicorn not
  installed here" error since this sandbox has no venv at that path), full
  test suite still 453 passed / ruff+mypy clean (no application source
  touched, deploy tooling only).

**Next:** clone the repo into
`/root/cloudcraftz/harcj_dash/exchange_event_pipeline`, then run
`PYTHON=/root/.local/bin/python3.11 ./scripts/bootstrap_server.sh`.
