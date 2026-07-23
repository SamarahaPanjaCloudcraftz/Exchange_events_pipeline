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

## 2026-07-23 — First real deployment: SUCCESS

Cloned `https://github.com/SamarahaPanjaCloudcraftz/Exchange_events_pipeline`
into `/root/cloudcraftz/harcj_dash/exchange_event_pipeline` (empty sibling
directory to HARCJ's own `dashboard_new`, confirmed no interference — see
prior entry). Ran:
```bash
PYTHON=/root/.local/bin/python3.11 INSTALL_DIR=/root/cloudcraftz/harcj_dash/exchange_event_pipeline ./scripts/bootstrap_server.sh
```
Completed with no errors: venv built from Python 3.11.15, `.env` scaffolded,
systemd units installed, schema applied, all three units enabled and
started.

**Verified live, all green:**
- `exchange-events-web.service`: active, gunicorn running, `/` and
  `/api/v1/exchanges` both return 200 with real data on `127.0.0.1:8080`.
- `systemctl list-timers`: both timers registered with correct next-run
  times (alert ~15min cadence, ingest ~6h cadence) — **empirically confirms
  the `OnCalendar` step syntax (`0/15`, `0/6`) parses correctly on this
  host's systemd 219**, the one thing that couldn't be checked beforehand
  (`systemd-analyze calendar` doesn't exist on this version).
- **HARCJ fully undisturbed**: Streamlit's PID (12903) and start time
  (`May15`) unchanged -- never restarted. Both scheduler processes still
  running normally. Port 8501 still 200. `crontab -l` byte-identical to
  before, nothing added.

**Remaining steps:**
1. Fill in `/root/cloudcraftz/harcj_dash/exchange_event_pipeline/.env` with
   real secrets (FRED/BLS/BEA/CME keys, SMTP, Teams webhook,
   `ALERT_RECIPIENT_EMAIL`), then `systemctl restart exchange-events-web`.
2. Wire the "Exchange Events" tab into the *real* HARCJ `app.py` on this
   server (not just the local replica) -- add a new `app_new.py` there too,
   per the same pattern already proven locally, then have HARCJ's actual
   Streamlit process pick it up (needs a restart of that one process --
   coordinate timing since it's the one long-running process HARCJ never
   restarts on its own).
3. Post-deploy verification per DEPLOYMENT_CHECKLIST.md §6 once secrets are
   in and the tab is wired.

## 2026-07-23 — Paused: everything stopped at user's request

Per explicit instruction, stopped and disabled all three units right after
confirming the successful first deployment:
```bash
systemctl stop exchange-events-web exchange-events-ingest.timer exchange-events-alert.timer
systemctl disable exchange-events-web exchange-events-ingest.timer exchange-events-alert.timer
```
Confirmed: all three `inactive (dead)`, `ps aux | grep -i exchange` returns
nothing -- zero exchange-events processes running on the server. HARCJ
remains completely unaffected (never touched by any of this). Nothing from
this pipeline is live until deliberately restarted.

## 2026-07-23 — Port changed to 8502

User chose `8502` for this pipeline's web service instead of the app's own
generic default `8080` (already confirmed free on the real server in the
same recon check that found `8501` — HARCJ's port — in use). Updated every
deployment-specific reference: `deploy/systemd/exchange-events-web.service`
(`--bind`), `scripts/redeploy.sh`/`rollback.sh` (`HEALTH_URL` default),
`scripts/bootstrap_server.sh` (post-install verification message),
`wsgi.py` (docstring example), `docs/USER_GUIDE.md` and
`docs/DEPLOYMENT_CHECKLIST.md` (tunnel command, port table). Left
`README.md`/`CLAUDE.md` untouched -- those document the app's own generic
local-dev default (any machine, `exchange-events serve --port 8080`),
unrelated to this specific server's chosen port. Verified: `bash -n` on all
three scripts, `systemd-analyze verify` on the web unit (clean besides the
expected missing-venv error in this sandbox), full test suite still 453
passed.

**Still to update once we get there:** `app_new.py`'s iframe URL (currently
defaults to `http://127.0.0.1:8080`) needs `EXCHANGE_EVENTS_URL=http://127.0.0.1:8502`
when actually wired into the real HARCJ `app.py` on the server.

## 2026-07-23 — Eliminated port duplication

User pointed out the port number was hardcoded in multiple places after the
8080->8502 change and asked for a single source of truth. Fixed properly:

- **New single source**: `EXCHANGE_EVENTS_PORT` in `.env` (documented in
  `.env.example`, default `8080`; `bootstrap_server.sh` writes the real
  value in via its own `PORT=` env var, replacing the template line with
  `sed` rather than appending -- appending would have left two
  `EXCHANGE_EVENTS_PORT=` lines in the resulting `.env`, the same kind of
  duplication being fixed).
- `deploy/systemd/exchange-events-web.service`: `--bind
  127.0.0.1:${EXCHANGE_EVENTS_PORT}` -- systemd's own native `ExecStart`
  variable substitution (no shell wrapper), reading from `EnvironmentFile=`.
- `scripts/redeploy.sh` / `rollback.sh`: `HEALTH_URL` now derives its port
  from the same `.env` (`grep`), only falling back to `8080` if genuinely
  absent; `HEALTH_URL` itself can still be overridden directly if ever
  needed.
- `wsgi.py`: docstring made generic (`${PORT}` placeholder) rather than
  hardcoding a number that would go stale again.

**Verified rigorously, not assumed** -- this changes what actually
determines whether the web service binds to the right port at all, so a
mistake here would be a real outage risk:
1. A minimal test (`echo`, `EnvironmentFile` + native `${VAR}` in
   `ExecStart`, no shell) confirmed the substitution mechanism works on
   this sandbox's systemd 249. An earlier attempt with `printf`'s `%s` gave
   a confusing wrong result -- turned out to be a **test-design bug**, not a
   real finding: literal `%` characters in `ExecStart=` collide with
   systemd's *own* `%h`/`%i`-style specifier syntax, unrelated to `$VAR`
   environment substitution. Redone cleanly with `echo` (no `%` anywhere).
2. Full realistic test: real venv, real database, the actual unit file
   (paths substituted, run as a **user-scope** systemd service so no root
   was needed), a real `.env` with `EXCHANGE_EVENTS_PORT=18081` --
   `systemctl status` showed the live process's real command line as
   `--bind 127.0.0.1:18081`, and `curl` confirmed it actually served real
   data on that exact port. Fully cleaned up afterward.
3. This was tested on systemd **249** (this sandbox), not this host's
   systemd **219** -- the substitution mechanism itself is old, basic
   systemd behavior (not a newer feature like the calendar-timer step
   syntax was), so risk is low, but **re-confirm on first start on the real
   server anyway** (`systemctl status exchange-events-web`, check the
   command line shows the real port, not a literal `${EXCHANGE_EVENTS_PORT}`
   string) before relying on it there.

Full test suite still 453 passed / ruff+mypy clean throughout (deploy
tooling only, no application source touched).

## 2026-07-23 — First real redeploy attempt: caught a gap in redeploy.sh itself

User ran `scripts/redeploy.sh` for the first time on the real server (to
pick up the port fixes above). It failed at the test-gate step: `No module
named pytest`. Root cause: `bootstrap_server.sh` only ever installs
`requirements.lock.txt` (the `postgres`+`deploy` extras) into the production
venv -- `pytest`/`ruff`/`mypy` live in the `dev` extra, which nothing had
ever installed there. The script's own safety design worked exactly as
intended despite the bug: it failed *before* restarting anything, reverted
the working tree to the previous known-good commit, and never touched the
live service.

**Fixed** `scripts/redeploy.sh` to install `-e ".[dev]"` alongside the
locked deps before running its test gate -- mirrors what CI already does.
Verified by reproducing the exact failure in a fresh venv (lockfile only,
confirmed `pytest` genuinely absent), then confirming the fix installs
pytest/ruff/mypy and the full suite passes (453 passed) in that same venv.

**Next:** push, then re-run the same `redeploy.sh` invocation on the server.

## 2026-07-23 — Manual bypass executed successfully; one more bug caught and fixed live

Since the server was stuck at commit `12224ae` (predating the re-exec and
`.env`-hiding fixes, so `redeploy.sh` alone couldn't self-heal -- see prior
entries), did the one-time manual bypass: `git checkout origin/main`,
installed lockfile + `-e .` + `-e ".[dev]"`, **hid `.env` before testing**
(`mv .env .env.bak`), ran the real suite -- **453 passed, 19 skipped**, on
the real server, Python 3.11.15 -- then restored `.env`.

**A second real bug surfaced live**, caught before it caused lasting
confusion: the manual instructions given for "sync the updated unit file"
used a plain `cp deploy/systemd/exchange-events-web.service
/etc/systemd/system/` -- but that copies the file **as-is**, with its
literal `/opt/exchange-events` paths. It overwrote the unit file
`bootstrap_server.sh` had originally installed (which *did* have the paths
correctly substituted to the real
`/root/cloudcraftz/harcj_dash/exchange_event_pipeline` directory) with the
raw, un-substituted template. Symptom: the service still started (`active
(running)`), but bound to `127.0.0.1:8080` instead of `8502` -- because
`EnvironmentFile` now pointed at a nonexistent `/opt/exchange-events/.env`,
so `EXCHANGE_EVENTS_PORT` was never actually available to substitute.

**Fixed** by redoing the copy with the same `sed` substitution
`bootstrap_server.sh` itself uses:
```bash
sed "s#/opt/exchange-events#/root/cloudcraftz/harcj_dash/exchange_event_pipeline#g" \
    deploy/systemd/exchange-events-web.service > /etc/systemd/system/exchange-events-web.service
```
Re-verified: `WorkingDirectory`/`EnvironmentFile`/`ExecStart` all show the
real path; after `daemon-reload` + `restart`, the live process's actual
command line shows `--bind 127.0.0.1:8502` -- **confirming the
`${EXCHANGE_EVENTS_PORT}` substitution genuinely works on this host's real
systemd 219**, not just the sandbox's 249 tested earlier. `curl` against
`127.0.0.1:8502` returns `200`, 4 gunicorn workers healthy, no errors beyond
the expected "email/teams not configured" notices (secrets not filled in
yet).

**Lesson for future manual-bypass situations**: never hand-copy a systemd
unit file from this repo directly to `/etc/systemd/system/` if `INSTALL_DIR`
isn't the literal default `/opt/exchange-events` -- always run it through
the same `sed` substitution `bootstrap_server.sh` uses, or the paths will
silently be wrong in a way that doesn't necessarily stop the service from
starting.

**Current state**: web service live and verified on `8502`. Ingest/alert
timers still stopped/disabled (per the earlier explicit pause) -- not yet
re-enabled. Real secrets (`FRED_API_KEY`, SMTP, Teams webhook, CME creds,
etc.) not yet filled in. HARCJ's real `app.py` (not the local replica) not
yet wired with the "Exchange Events" tab.

## 2026-07-23 — Real secrets filled in, real ingest run, dashboard confirmed live with real data

User filled in `.env` with real credentials (FRED, CME, plus notification
secrets) and restarted the web service. Ran a full ingest across every
source:

**789 real records upserted** -- CME (100), NSE (64), IANA (12), FRED (578),
BLS (23), FOMC (12). Failures matched documented expectations exactly, none
blocking: BSE (known broken endpoint), ISM (no free source exists),
MarketWatch/econ_calendar (blocked, not needed -- waterfall covers required
data), BEA (optional PCE backstop, key not yet added).

Ran `exchange-events alert` afterward. User confirmed via the actual browser
(tunneled `ssh -L 8502:localhost:8502 215` -> `http://localhost:8502/`,
after an initial mixup pointing at the wrong local port 8503) that the
dashboard shows real data and real alerts -- the first genuine end-to-end
confirmation of this pipeline working live on the production server.

**Still open**: ingest/alert timers remain stopped/disabled (from the
earlier explicit pause) -- this ingest/alert run was manual, one-off.
HARCJ's real `app.py` still not wired with the "Exchange Events" tab.

## 2026-07-23 — redeploy.sh confirmed working end-to-end, unassisted

Full arc of testing `scripts/redeploy.sh` for real, on the actual server:

1. Added a small, visible test change (a highlighted banner on the XCME
   tab) specifically to make a real redeploy observable in the browser,
   not just in logs.
2. First `redeploy.sh` run failed on the same `.env`-contamination bug
   fixed earlier -- root cause: the server was still on commit `f735026`,
   5 commits behind (missing both the re-exec and `.env`-hiding fixes) --
   the earlier manual bypass hadn't actually reached the latest commit,
   most likely because not everything was pushed to GitHub at that exact
   moment. Confirmed via `git log HEAD..origin/main --oneline`.
3. One more manual bypass (same pattern as before: checkout, install,
   hide `.env`, test -- 453 passed, restore `.env`, init-db, restart) got
   the server onto commit `5795637`, with both self-healing fixes finally
   in place. No unit-file changes needed this time (nothing under
   `deploy/systemd/` changed in this range).
4. Confirmed the banner rendered live in the browser.
5. **The real test**: removed the banner (commit `a6c3f51`, an ordinary
   fresh change, not another bypass), pushed, and ran plain
   `./scripts/redeploy.sh` on the server with no assistance. It completed
   the full cycle on its own -- fetch, checkout, install, test gate
   (`.env` safely hidden throughout), restart -- and the banner's removal
   was confirmed live in the browser afterward.

`scripts/redeploy.sh` is now confirmed to work end-to-end, unassisted, on
the real production server.

## 2026-07-23 — redeploy.sh made a genuine one-stop-shop, with full clarity

User asked: since redeploy.sh only updated code but never systemd unit
files, shouldn't *any* change anywhere be reflected on the server through
this one script? Also asked two sharp follow-up questions before accepting
the fix: does the script verify the timers' next-fire time (it hadn't --
only checked manually before), and does it actually *start* both timers
(it would have, via an unconditional `restart`, which is wrong if one was
deliberately left off).

**Built and rigorously tested, in order:**
1. `redeploy.sh` now re-renders every file under `deploy/systemd/` with the
   same path substitution `bootstrap_server.sh` uses, and only touches
   `/etc/systemd/system/` for ones that actually changed (root-only; skips
   with a clear warning otherwise).
2. **Bug caught immediately by testing the diff logic directly** (a
   standalone harness, run 1/2/3 against a fake target dir): comparing via
   process substitution without a trailing newline against a file written
   with one meant it always reported "changed," even with identical
   content -- every redeploy would have reinstalled and restarted both
   timers regardless. Fixed by diffing real temp files.
3. **Second real bug, this one from the user's own question**: both the
   web service and (when a unit changed) the timers were restarted
   *unconditionally* -- meaning a routine deploy could silently reactivate
   something deliberately stopped (e.g. the alert timer, left off on
   purpose). Fixed: everything is now only restarted if already active;
   if inactive, the file/code still updates, but redeploy never flips
   anything on. Verified with real user-scope systemd units in both
   states -- active+changed restarts (confirmed via the unit's own
   `Description` picking up the new content); inactive+changed is left
   alone, confirmed via `systemctl is-active` unchanged after the run.
4. Added a full status report every run: each timer's active/enabled
   state, what action (if any) was taken, and its real next-fire time --
   via each unit's own `NextElapseUSecRealtime` property, not `systemctl
   list-timers` (found to silently omit inactive timers even with
   `--all`, which would have hidden exactly the case that matters most).
5. Re-ran the full E2E redeploy harness for both web-service states
   (active-before -> restarts + health-checks; inactive-before -> code
   updates but stays stopped) -- both confirmed exactly right, real venv,
   real git history, real systemd units throughout.

`redeploy.sh` is now confirmed to update code, config, and systemd units
together, in one run, without ever overriding a deliberate operator
decision about what should currently be running.

## 2026-07-23 — Timer status report now shows even with nothing to deploy

Follow-up to the same conversation: the user wanted to enable both timers
and re-run redeploy.sh to see their status reflected -- but since nothing
new would be pushed, the script would have exited at "nothing to deploy"
before ever reaching the status report. Fixed by extracting it into a
`report_timer_status()` function called from both that early-exit path and
the normal post-deploy path, verified directly (a real clone already at the
latest commit correctly showed the full report instead of just the
one-line "nothing to deploy" message). A plain re-run of `redeploy.sh` is
now a legitimate way to check current timer state at any time.

## 2026-07-23 — Real bug caught live: --value unsupported on this host's systemctl

User enabled both timers and re-ran redeploy.sh; the report showed both as
`active, enabled` but with "next fire: not scheduled" for both -- a real
contradiction, since an active timer must have a scheduled next fire.
Diagnosed directly: `systemctl list-timers` on the real server showed the
correct, real next-fire times (18:00:00 ingest, 18:10:00 alert, correctly
staggered) -- confirming the timers themselves were fine, and the bug was
in the report's own query. Root cause: `systemctl show ... --value` most
likely isn't supported by this host's older systemctl (systemd 219); it
silently failed, and the `|| true` fallback swallowed the error, reporting
empty (misread as "not scheduled") even though the timer was genuinely
correctly scheduled the whole time.

Fixed by parsing the plain `Key=Value` output of `systemctl show` instead
of depending on `--value`, which is universally supported. Re-verified
locally with a real active/inactive timer pair: active one now correctly
shows its real next-fire time, inactive one still correctly shows "not
scheduled".

## 2026-07-23 — Second real bug on the same query, caught immediately after the first fix

After fixing the `--value` issue, the very next redeploy run on the real
server showed both timers as `active, enabled` (correct) but with next-fire
times of "56y 6month 2w 6d 21h 30min" -- obviously wrong. Root cause: this
host's systemd 219 pretty-prints `NextElapseUSecRealtime` as a *relative
duration* rather than an absolute calendar date (the ~56 years roughly
matches misinterpreting an epoch-based value as elapsed time -- 2026 minus
1970 is ~56 years). Since `systemctl list-timers` was already confirmed
correct on this exact host, switched to parsing that instead of the `show`
property at all: `--no-legend` gives exactly one clean data line for an
active timer, nothing for an inactive one. Re-verified locally with a real
active/inactive pair before pushing.

Two real, host-specific systemd-219 incompatibilities found and fixed in
quick succession, both only surfaced by actually running the script live on
the real server rather than trusting the sandbox's newer systemd (249).

## 2026-07-23 — Both timers live, correctly scheduled, fully confirmed

Final confirmation after the two systemd-219 query fixes: `redeploy.sh`'s
report now shows both timers correctly --
`exchange-events-ingest.timer: active, enabled`, next fire
`Thu 2026-07-23 18:00:00 IST`; `exchange-events-alert.timer: active,
enabled`, next fire `Thu 2026-07-23 18:10:00 IST` -- exactly the intended
10-minute stagger. Deploy completed cleanly, web service restarted and
healthy.

**Status as of this entry**: web service live and healthy on `8502`;
ingest timer live (every 6h); alert timer live (every 6h, 10min offset);
`redeploy.sh` fully proven as a one-stop-shop -- code, config, and systemd
units all sync through it, nothing reactivates a deliberately-stopped unit,
and full timer status is always visible. Real secrets in place for
FRED/CME/SMTP/Teams; 789 real records ingested and growing automatically
from here. Still open: HARCJ's real `app.py` not yet wired with the
"Exchange Events" tab (only proven against the local replica so far).

## 2026-07-23 — Real CME "series" bug found by the user on the live dashboard, fixed

User noticed the XCME tab's calendar showed an ES expiry on 2026-07-24
labeled "quarterly" -- factually impossible, since standard quarterly ES
futures only expire Mar/Jun/Sep/Dec. Investigated (via a research agent,
not guessed): root cause was `adapters/cme.py` setting `series` from a
static per-underlying config value (`DEFAULT_PRODUCTS`), applied uniformly
to every instrument CME's API returned for "ES" regardless of the actual
contract month -- never derived from CME's own data. Confirmed the date
itself was genuine live CME data, only the label was fabricated by our own
code.

**Fixed** (`src/exchange_events/adapters/cme.py`): added `_series_for()`,
deriving each instrument's real cadence from its own Globex symbol's month
code (standard CME futures month-code table, e.g. "U" -> September ->
quarterly; "N" -> July -> not quarterly -> "monthly"), falling back to the
product's configured default only if the symbol doesn't parse as expected.
Two new regression tests added and passing (455 total, was 453). Corrected
the flawed "series are 1:1 with the underlying" assumption recorded in
DECISIONS.md's earlier "CME dashboard expansion" entry, as its own new
entry with full detail.

**Separate, real production-data issue found while cleaning up**: the
2026-07-24 ES record that triggered this whole investigation turned out to
be `source='cme'` (singular) in the database -- not `source='cme_calendar'`
(the real adapter's actual source name) -- meaning it was a **stale,
orphaned row from old demo/test data**, unrelated to today's code bug at
all. It had `source_raw_id=null` and an older `ingested_at` timestamp than
every other real record. Confirmed via `SELECT source, event_type,
COUNT(*) FROM events GROUP BY source, event_type` that this was an isolated
single row (every other source in the database was correctly named) before
deleting it (`DELETE FROM events WHERE source='cme' AND
event_type='expiry'`) -- verified gone afterward, nothing else affected.

Two real, independent bugs found from one user observation: (1) a genuine
code bug in how CME expiry series gets classified, now fixed and tested;
(2) leftover stale demo data sitting in the production database, now
cleaned up. Neither would have been caught without the user actually
looking at the live dashboard's real data.
