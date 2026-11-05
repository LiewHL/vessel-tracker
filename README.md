# Vessel Tracking: setup guide

A hands-off tracker for a list of ships. It runs entirely on GitHub's servers, so your computer can stay off.

- **Dashboard:** a web page with a map of each ship's last known position, a list with "last seen" status, and a ↗ link to each ship's live position on VesselFinder.
- **Position log:** every hour (started by cron-job.org, with GitHub's timer as a backup), a script listens to AISStream for 15 minutes and saves the position of every ship it hears.
- **Weekly report:** every Monday at about 08:15 SGT, a printable report is created and emailed (with one Excel workbook: ship summary, positions, port calls, full history) to the private recipient list. **The email is the only copy** (see Private report emails).
- **Monthly report:** on the 1st of each month at about 07:15 SGT, a report for the previous month (tracks, days heard, positions logged, distance) is created and emailed (email only, no copy kept).
- **Passcode lock:** positions, run records and the sent log are stored encrypted. The dashboard asks for the passcode before showing anything.

**Cost:** $0. GitHub (public project) and AISStream (non-commercial use) are free.

**Privacy:** the project is public, but all position data and reports are encrypted (see "Passcode lock"). The vessel list (`vessels.csv`) is kept in the **private** repo `vessel-tracker-requests`, so it is not public either: use codes and vessel names only. Never put personal names, phone numbers or emails in it.

---

## What you need first

For each ship:

| Column in `vessels.csv` | What it is | Where to find it |
|---|---|---|
| `id` | Your own ID, e.g. A01 | You choose |
| `vessel_name` | Ship name | Your records |
| `company` | Shipping company | Your records |
| `category` | Your own grouping, e.g. a group code or ship type (optional). Each category gets its own colour | You choose |
| `imo` | 7-digit IMO number (used for the VesselFinder link) | Search the ship name on vesselfinder.com |
| `mmsi` | 9-digit MMSI number (used for the daily log) | Same VesselFinder page, under the ship details |
| `start_date` | Sign-on date, format YYYY-MM-DD | Your records |
| `end_date` | Sign-off date; **leave blank while on board** | Your records |
| `notes` | Anything else (optional) | |

**Signing off and on again (stints).** The tracking period is **26 weeks = 182 days on board**; days signed
off don't count. When someone signs off, fill in `end_date` on their row: the dashboard shows
"Paused since …", tracking and alerts stop. When they sign on again (same or another vessel), add a **new row
with the same ID**, the ship's details and the new `start_date` (leave `end_date` blank). The expected finish
moves later automatically. The vessel list check flags stints that overlap or a missing sign-off date.

**Standby places.** A row with an ID and category but no IMO/MMSI is a place with no vessel yet: listed as
"Standby", never tracked.

> The daily log needs the **MMSI**. A ship without a correct MMSI will never get a logged position.

---

## One-time setup (about 30–45 minutes)

### Step 1: Create a GitHub account
Go to **github.com**, sign up (free). Your username becomes part of the dashboard link.

### Step 2: Get an AISStream API key
1. Go to **aisstream.io** and sign in (you can sign in with your GitHub account).
2. Open **API keys** and create a key.
3. Copy the key somewhere safe. It is shown only once.

### Step 3: Create the project and upload the files
1. On GitHub, click **+** (top right) > **New repository**.
2. Name it e.g. `vessel-tracking`, choose **Public**, tick **Add a README file**, click **Create repository**.
3. Unzip the package on your computer.
4. In the repository, click **Add file > Upload files**, then drag in **everything inside** the unzipped `vessel-tracker` folder (including the `.github` folder). Click **Commit changes**.
   - **Mac:** the `.github` folder is hidden in Finder. Press **Cmd + Shift + .** to show it before dragging.
   - Check afterwards that you can see a `.github/workflows` folder in the repository. If it is missing, see "Troubleshooting".

### Step 4: Save the AISStream key as a secret
1. In the repository, open **Settings > Secrets and variables > Actions**.
2. Click **New repository secret**.
3. Name: `AISSTREAM_API_KEY` (exactly). Secret: paste your key. Click **Add secret**.

The key stays hidden, even though the project is public.

### Step 5: Allow the jobs to save data
**Settings > Actions > General > Workflow permissions**: select **Read and write permissions**, click **Save**.

### Step 6: Turn on the dashboard website
1. **Settings > Pages**.
2. Source: **Deploy from a branch**. Branch: **main**, folder **/ (root)**. Click **Save**.
3. After 1–2 minutes the page shows your link: `https://<your-username>.github.io/vessel-tracking/`
4. Bookmark it. This is the link you share with others (together with the passcode).

### Step 7: Put in your real ships
1. Open `vessels.csv` in the private repo `vessel-tracker-requests` and click the **pencil** icon.
2. Replace the sample rows with your ships (keep the first header line unchanged).
3. Click **Commit changes**.

### Step 8: Test it now (don't wait for tomorrow)
1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily position log > Run workflow > Run workflow**.
3. It runs for about 15–20 minutes. A green tick means it worked.
4. Refresh the dashboard. Ships heard in that run show a position. The header shows "Logger OK".
5. Click **Weekly report > Run workflow** to test the report and the email.

### Step 9: Set up the report emails and the passcode
See "Private report emails" and "Passcode lock" below.

Setup is done. From now on nothing needs your computer.

---

## Day to day

| You want to… | Do this |
|---|---|
| See where ships are | Open the dashboard link |
| See a ship's live position | Tap **↗** next to the ship in the table (opens VesselFinder) |
| See where a ship has been | Click the ship in the table: the top map zooms to it and the bottom map shows its route (7 d, 30 d, All or Dates) |
| Show another category | Ships are grouped by category. The latest category (highest number, ignoring test "TS" categories) is open; click a category heading to open or close it |
| Hide a category on the fleet map | Click its chip in the fleet map toolbar (click again to show it). Remembered on this device; the table is not affected |
| Change what a map panel shows | Use the panel's menu: **Fleet map**, **Vessel route / history** or **Timeline (periods)** |
| Resize the panels | Drag the dividers between the maps and the table; your layout is remembered in your browser |
| Get a report as PDF | Open the report, then **Print > Save as PDF** |
| Make a monthly report for a past month | Actions > Monthly report > Run workflow, type the month as YYYY-MM |
| Stop the monthly email | Delete the last step in `.github/workflows/monthly-report.yml` |
| Add, change or remove a ship | Edit `vessels.csv` in the private repo `vessel-tracker-requests` (pencil icon) |
| Remove a ship's logged data too, or change IDs | After editing `vessels.csv`, run **Actions > Tidy data** with every kept ship as OLD=NEW, e.g. `MR01=MR01,TS07=TS02` |
| Run the log now | Actions > Daily position log > Run workflow |

## Alerts and extra views

**Alert emails** (to the same private list as the reports; one email per run with anything new):

| Alert | When |
|---|---|
| Entered / left risk area | A ship's position is inside an area in `config/risk_areas.json`. "Left" is sent after it has been heard outside on 2 runs in a row |
| Storm nearby | A current tropical cyclone (GDACS, gdacs.org) is within 300 nm of a ship heard in the last 3 days |
| Gone quiet / back in contact | A ship has not been heard for 7 days although its last position was within 30 nm of a port (where coverage is normally good) |
| Vessel list check | Each time `vessels.csv` is saved: wrong MMSI/IMO, bad dates, duplicate IDs |
| Logger health | Daily at 09:41 SGT, if the logger has not run for 24 hours or its last run failed |

Only ships inside their tracking period (or without dates) get position alerts.

**Change the risk areas:** edit `config/risk_areas.json` on GitHub. Each area is a list of `[latitude, longitude]`
corners; set `"active": false` to pause one, and update `"updated"` (shown in alert emails).
`storm_distance_nm` sets the storm distance.

**Dashboard extras:**
- **Timeline (periods):** a map-panel option showing every ship's tracking period (coloured by category), with today marked. Click a bar to select the ship; click a category chip to hide/show it (remembered on this device, separately from the fleet map).
- **Info ▾** in the route panel: flag, type, size, draught, call sign, destination/ETA (from the ship's AIS), tracking period, ship time, countries visited and recent port calls.
- **Port calls** on the route map: B = berthed, A = at anchor, S = stopped offshore.
- **Ship time:** under "Last seen" (nautical time zone, so approximate near coasts).
- A banner warns if `vessels.csv` has a mistake.

**Reports:** all reports now include alerts, "coming up in the next 14 days" (periods starting/ending) and port calls.
Monthly and quarterly also include the timeline and countries/ports visited. A **quarterly one-page summary** is
emailed on 1 Jan/Apr/Jul/Oct at about 06:15 SGT. Port calls are also a sheet in the emailed Excel workbook.

## Countries visited

A country counts as **visited** when the ship **berthed or anchored at one of its ports** (a port call) during
the period on board. Passing close by does not count. Counts are a minimum: short calls between hourly
positions, or where there is no AIS coverage, can be missed.

- **Weekly / monthly / quarterly reports:** countries visited in the period; monthly and quarterly also show
  **countries to date** for each ID's whole period, with a map (all ships, a category, or one ship).
- **Countries report on demand:** Actions > **Countries report** > Run workflow. Leave the dates empty for each
  ID's whole period so far, or give from/to dates; optionally one category. Emailed only.
- **End-of-period summary:** made and emailed automatically when an ID completes 182 days on board
  (countries, ports, every port call, map). Emailed only.
- **Dashboard:** map panel option **Countries visited** (all ships / category / one ship; period, 30 days or
  7 days), with a list of countries, ports, calls and time in port.
- Country outlines: Natural Earth (refresh with Actions > Update port codes and map data).

### ASEAN, China, India (ACI)

How many **IDs** (standby places not counted) called at a port in ASEAN, China or India.
**ASEAN** = Brunei, Cambodia, Indonesia, Laos, Malaysia, Myanmar, Philippines, Thailand, Timor-Leste, Vietnam
(**Singapore is not counted**). **China** includes **Hong Kong and Macao**; **Taiwan is not counted** (an ID that only went to Taiwan is non-ACI).

- **Weekly / monthly / quarterly reports and their email text:** counts for the report period and for the whole period
  to date ("X of Y"), then category > ID: ASEAN countries, China, India.
- **Countries report:** the same for the chosen dates and to date; the Excel file has an **ASEAN China India** sheet.
- **End-of-period summary:** one line, e.g. "ASEAN: Malaysia, Vietnam · China: yes · India: no".
- **Dashboard:** Countries visited panel shows "ASEAN · China · India of N"; the List adds each ID's ACI countries.

## Status colours

- **Green:** position received in the last 3 days
- **Amber:** 3 to 7 days old
- **Red:** over 7 days old, listed under "Follow up" in the weekly report
- **Grey:** no position received yet

## Limits to know

- **Coastal coverage only.** AISStream uses shore-based receivers. Ships mid-ocean keep their last known position until they come back into range, so red does not mean something is wrong.
- **Snapshots, not a continuous track.** The log records where each ship was during each 15-minute listen (every hour). Use the ship's **↗** VesselFinder link for its current position.
- **AIS switched off.** Ships in high-risk areas sometimes switch AIS off.
- **AISStream is free with no uptime guarantee.** A missed day just means a gap in the log. The next day's run continues normally.
- **Scheduled runs can start late.** GitHub may start scheduled jobs late, or occasionally skip one, at busy times. The dashboard shows **Logger late** if no run has happened for over 4 hours.

## Files in this project

| File | Purpose | Edit it? |
|---|---|---|
| `vessels.csv` | Your list of ships: kept in the private repo `vessel-tracker-requests` (a locked copy is in `vault/` for the dashboard) | **Yes**, in the private repo |
| `index.html` | The dashboard page | No |
| `vault/` | Encrypted position history, last positions, run records and reports | No, written automatically |
| `data/status.json` | Run health (times and counts only, no ship details); not locked | No |
| `scripts/vault.py` | Locks and unlocks the data | No |
| `scripts/` | The logger and report programs | No |
| `assets/ports.json` | World port list used for place names (World Port Index, NGA Pub. 150) | No |
| `assets/locode.json` | UN/LOCODE port codes, to show AIS destinations like `CNYSA` as "Yangshan, China" (refresh with Actions > Update port codes) | No |
| `.github/workflows/` | The daily, weekly and monthly schedules | Only to change times |

## Reliable start (cron-job.org)

GitHub's own timer often starts runs late or skips them, so the logger is started by **cron-job.org**
(free) every hour. GitHub's own timer stays on as a backup; a timed start is skipped if the logger
already ran in the last 40 minutes.

1. **GitHub key:** profile picture > Settings > Developer settings > Personal access tokens >
   Fine-grained tokens > Generate new token. Repository access: *Only select repositories* > this project.
   Permissions > Repository permissions > **Actions: Read and write** (nothing else). Copy the token.
2. **cron-job.org job:** URL `https://api.github.com/repos/<username>/<project>/actions/workflows/daily-log.yml/dispatches`,
   schedule every hour, on the hour (time zone Asia/Singapore).
   Advanced: method **POST**; headers `Accept: application/vnd.github+json`,
   `Authorization: Bearer <token>`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`;
   body `{"ref":"main","inputs":{"source":"cron"}}`. A test run should return **204**.
3. When the token expires, generate a new one and paste it into the cron-job.org header.

The token can only start runs on this project; it cannot read or change anything.

## Changing the schedule

Times are in UTC (Singapore is UTC+8). In `.github/workflows/daily-log.yml`, the line `cron: "25 * * * *"` is only the backup timer (every hour at :25); the main start times are set on cron-job.org.

## Troubleshooting

| Problem | Fix |
|---|---|
| Header says **Logger problem** | Hover over it to see the reason. Most often the `AISSTREAM_API_KEY` secret is missing or mistyped (Step 4). |
| Header says **Logger not run yet** | Run it by hand (Step 8), or wait for the next run (11:47 or 23:47 SGT). |
| A ship never gets a position | Check its MMSI is correct (9 digits). It may also simply be out of coastal range. |
| No `.github` folder after upload | Click **Add file > Create new file**, type `.github/workflows/daily-log.yml` as the name, paste the file's contents, commit. Repeat for `weekly-report.yml`. |
| Dashboard shows "Could not load vessels.csv" | Open it through the github.io link, not as a file on your computer. |
| VesselFinder link shows the wrong ship | The IMO number may be wrong (the vessel list check emails you about invalid IMOs). |
| No weekly email | Check the email secrets and your spam folder. The run log says if addresses were skipped (non-SP). A report that wasn't sent stays due and is retried next hour; any report can be rebuilt with Actions > Run workflow. |
| Runs fail at "Unlock the data" | The `REPORT_PASSCODE` secret is missing or was changed. Set it back to the passcode the data was locked with. |
| Dashboard keeps saying "Wrong passcode" | Check for typing errors. The passcode is the value of the `REPORT_PASSCODE` secret. |

## Private report emails

Weekly and monthly reports are emailed directly (with the report attached) to the addresses in the
`EMAIL_TO` secret. Recipients, the sending account and its password are stored only as GitHub
**secrets**: they never appear in the project files, on the dashboard, or in the public run logs.

- **The email is the only copy.** No report is kept in the project, on the dashboard or in the sending
  account. Only a sent log (report type, period, counts, time sent) is stored, encrypted; the dashboard
  shows it under **Reports ▾**. Reports can be rebuilt any time from the position data (Actions > Run workflow).
- **Recipients are hidden:** they are given to the mail server only (the email shows "undisclosed
  recipients"), so they never see each other and the sending account's inbox gets no copy.
- **Sent copy deleted:** right after sending, the job deletes the email from the sending account's Sent
  folder and Trash (needs IMAP, which Gmail has on by default). If that fails the run shows a warning.
- **SP addresses only:** only `@sp.edu.sg` addresses are sent to; others are skipped and the run log
  shows how many (never the addresses). Change with an optional `EMAIL_DOMAIN` secret.

Secrets to add under **Settings > Secrets and variables > Actions**:

| Secret | Value |
|---|---|
| `EMAIL_TO` | Recipients, separated by `;` |
| `SMTP_USER` | Sending address, e.g. a Gmail account made for this |
| `SMTP_PASS` | That account's **app password** (Gmail: needs 2-Step Verification, then Google Account > Security > App passwords) |
| `SMTP_HOST`, `SMTP_PORT` | Optional; default `smtp.gmail.com` and `587` |

Until these are set, no email is sent and nothing is kept. Nothing is ever posted publicly.

## Your own list in a report: Load and Export

Reports only ever contain the tracker codes (e.g. MR05). Your own list is never stored in the tracker, on
GitHub, or sent by email. Keep it in your SP OneDrive, with these headings in row 1:

| Code | ST.ID | ST.N | SF.I |
|---|---|---|---|
| MR05 | … | … | … |

- Open an emailed report and press **Load**, then pick that Excel (.xlsx) or .csv file. Codes then show as
  "MR05 · ST.ID · ST.N" and an **SF.I** column appears. A note lists codes missing from your list and codes
  listed twice.
- **Export** (appears after Load) saves an Excel with one row per code: Code, ST.ID, ST.N, SF.I, category,
  vessel, period, status, last position, countries and ACI. Keep it in SP OneDrive.
- **Hide** switches back to codes. Printouts made while the list shows are marked "Confidential".
- Everything happens in your browser: nothing is uploaded, saved or sent, and closing the tab clears it.
  Works offline.

## Staff codes and per-staff emails

A code of the form **letters-hyphen-letters-number**, e.g. `MR-SRHDV1`, belongs to staff number **S1**
(`MR-KQTX12` → S12). The letters can be anything; only the number at the end matters. Codes of any other
shape (TS01, MR01) belong to no staff member and appear only in the full reports.

- After the weekly and monthly reports go to the main list, each staff number with ships gets its own
  report (and Excel) covering only its codes, sent to its address in the `STAFF_EMAILS` secret
  (`S1=name@sp.edu.sg`, one line each). Alerts about a ship also go to its staff member.
- Changing the staff for a code = renaming the code: edit `vessels.csv`, then run **Actions > Tidy data** with
  `OLD=NEW` (e.g. `MR-SRHDV1=MR-SRHDV4`) so the history moves with it.
- A staff number with ships but no address in `STAFF_EMAILS` is skipped; the run log shows only a count.

## Send button (email a report on request)

After unlocking the dashboard, **Send** emails the latest Weekly, Monthly (last full month), Quarterly (last
full quarter) or Countries (whole period) report to the SP address linked to the person's **Send code**.

- Each staff member has a staff number (S1, S2, …) and their own Send code, given out privately.
- Safety: the dashboard's key (inside the locked data) can only start the job in a small **private request
  repo**. That job checks the Send code (10 wrong tries a day pauses Send) and starts the report in this repo
  for that staff number only. The address comes from the `STAFF_EMAILS` secret; public run logs show only "S3".
  At most 5 sends a day per staff number. Reports sent this way show as "on request · S3" under Reports and
  don't affect the scheduled reports.
- Secrets in **this** repo: `SEND_KEY` (token for the request repo, "Actions: read and write" on that repo
  only) and `STAFF_EMAILS` (one line each, `S3=name@sp.edu.sg`). The hourly run locks `SEND_KEY` into the
  data; set it to `off` to remove the Send button.
- Secrets in the **request repo** (`vessel-tracker-requests`, private): `SEND_CODES` (one line each,
  `<send code>=S3`) and `MAIN_TOKEN` (token for this repo, "Actions: read and write" only). Its job is
  `setup/request-repo/send.yml`, saved as `.github/workflows/send.yml` there.
- Add a staff member: one line in `STAFF_EMAILS` and one in `SEND_CODES`. Stop one: delete their line.

## Passcode lock

All position data, run records and the report sent log are stored **encrypted** (AES-256) in `vault/`. Anyone can
download those files, but without the passcode they are unreadable. The passcode is the GitHub secret
`REPORT_PASSCODE` (12+ characters). The scheduled jobs use it to unlock the data during a run and lock it
again before saving.

- **Dashboard:** enter the passcode once. Tick **Remember on this device** to skip it next time; **Lock** (top right) forgets it.
- **Reports:** emailed only (readable as attached). **Reports ▾** on the dashboard lists what was sent and when.
- **Share with someone:** give them the dashboard link and the passcode (separately, e.g. link by email, passcode by phone).
- **Forgotten passcode:** read it from wherever you stored it. GitHub never shows a secret again, and the data cannot be recovered without it.
- **Change the passcode:** add a secret `REPORT_PASSCODE_NEW`, run **Actions > Change passcode**, then straight away set `REPORT_PASSCODE` to the new value and delete `REPORT_PASSCODE_NEW`. Everyone needs the new passcode afterwards.
- **What stays readable:** `data/status.json` (run times and counts only) and the program files. The vessel list is in the private repo, read each run with the `LIST_KEY` secret (a read-only key for that repo).
- **Run logs** on the Actions tab are public. They show counts only, never ship IDs, names or positions.
