# Vessel Tracking: setup guide

A hands-off tracker for a list of ships. It runs entirely on GitHub's servers, so your computer can stay off.

- **Dashboard:** a web page with a map of each ship's last known position, a list with "last seen" status, and a live VesselFinder map per ship.
- **Position log:** every 3 hours (02:37, 05:37, 08:37 … 23:37 SGT; an off-peak minute so GitHub is less likely to delay or skip the run), a script listens to AISStream for 30 minutes and saves the position of every ship it hears.
- **Weekly report:** every Monday at 07:50 SGT, a printable report is created, linked on the dashboard and emailed (with CSV files) to the private recipient list.
- **Monthly report:** on the 1st of each month at 08:20 SGT, a report for the previous month (tracks, days heard, positions logged, distance) is created, linked on the dashboard and emailed.
- **Passcode lock:** positions, run records and reports are stored encrypted. The dashboard asks for the passcode before showing anything.

**Cost:** $0. GitHub (public project) and AISStream (non-commercial use) are free.

**Privacy:** the project is public, but all position data and reports are encrypted (see "Passcode lock"). `vessels.csv` stays readable so it can be edited on GitHub: use IDs and vessel names only. Never put personal names, phone numbers or emails in it.

---

## What you need first

For each ship:

| Column in `vessels.csv` | What it is | Where to find it |
|---|---|---|
| `id` | Your own ID, e.g. A01 | You choose |
| `vessel_name` | Ship name | Your records |
| `company` | Shipping company | Your records |
| `category` | Your own grouping, e.g. a group code or ship type (optional). Each category gets its own colour | You choose |
| `imo` | 7-digit IMO number (used for the live map) | Search the ship name on vesselfinder.com |
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
1. Open `vessels.csv` in the repository and click the **pencil** icon.
2. Replace the sample rows with your ships (keep the first header line unchanged).
3. Click **Commit changes**.

### Step 8: Test it now (don't wait for tomorrow)
1. Open the **Actions** tab. If asked, click **I understand my workflows, go ahead and enable them**.
2. Click **Daily position log > Run workflow > Run workflow**.
3. It runs for about 30 minutes. A green tick means it worked.
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
| See a ship's live position | Set a map panel to **Live (VesselFinder)** and click the ship |
| See where a ship has been | Click the ship in the table: the top map zooms to it and the bottom map shows its route (7 d, 30 d, All or Dates) |
| Show another category | Ships are grouped by category. The latest category (highest number, ignoring test "TS" categories) is open; click a category heading to open or close it |
| Hide a category on the fleet map | Click its chip in the fleet map toolbar (click again to show it). Remembered on this device; the table is not affected |
| Change what a map panel shows | Use the panel's menu: **Fleet map**, **Vessel route / history** or **Live (VesselFinder)** |
| Resize the panels | Drag the dividers between the maps and the table; your layout is remembered in your browser |
| Get a report as PDF | Open the report, then **Print > Save as PDF** |
| Make a monthly report for a past month | Actions > Monthly report > Run workflow, type the month as YYYY-MM |
| Stop the monthly email | Delete the last step in `.github/workflows/monthly-report.yml` |
| Add, change or remove a ship | Edit `vessels.csv` on GitHub (pencil icon) |
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
emailed on 1 Jan/Apr/Jul/Oct at 08:30 SGT. Port calls are also sent as a CSV file.

## Status colours

- **Green:** position received in the last 3 days
- **Amber:** 3 to 7 days old
- **Red:** over 7 days old, listed under "Follow up" in the weekly report
- **Grey:** no position received yet

## Limits to know

- **Coastal coverage only.** AISStream uses shore-based receivers. Ships mid-ocean keep their last known position until they come back into range, so red does not mean something is wrong.
- **Snapshots, not a continuous track.** The log records where each ship was during each 30-minute listen (every 3 hours). Use **Live** for the current position.
- **AIS switched off.** Ships in high-risk areas sometimes switch AIS off.
- **AISStream is free with no uptime guarantee.** A missed day just means a gap in the log. The next day's run continues normally.
- **Scheduled runs can start late.** GitHub may start scheduled jobs late, or occasionally skip one, at busy times. The dashboard shows **Logger late** if no run has happened for over 9 hours.

## Files in this project

| File | Purpose | Edit it? |
|---|---|---|
| `vessels.csv` | Your list of ships | **Yes** |
| `index.html` | The dashboard page | No |
| `vault/` | Encrypted position history, last positions, run records and reports | No, written automatically |
| `data/status.json` | Run health (times and counts only, no ship details); not locked | No |
| `scripts/vault.py` | Locks and unlocks the data | No |
| `scripts/` | The logger and report programs | No |
| `assets/ports.json` | World port list used for place names (World Port Index, NGA Pub. 150) | No |
| `.github/workflows/` | The daily, weekly and monthly schedules | Only to change times |

## Changing the schedule

Times are in UTC (Singapore is UTC+8). In `.github/workflows/daily-log.yml`, the line `cron: "37 */3 * * *"` means every 3 hours at :37 UTC = 02:37, 05:37 … 23:37 SGT. Avoid minute 0 (the busiest time on GitHub). To listen longer each day, change `'30'` in `LISTEN_MINUTES` (max about 50).

## Troubleshooting

| Problem | Fix |
|---|---|
| Header says **Logger problem** | Hover over it to see the reason. Most often the `AISSTREAM_API_KEY` secret is missing or mistyped (Step 4). |
| Header says **Logger not run yet** | Run it by hand (Step 8), or wait for the next run (11:47 or 23:47 SGT). |
| A ship never gets a position | Check its MMSI is correct (9 digits). It may also simply be out of coastal range. |
| No `.github` folder after upload | Click **Add file > Create new file**, type `.github/workflows/daily-log.yml` as the name, paste the file's contents, commit. Repeat for `weekly-report.yml`. |
| Dashboard shows "Could not load vessels.csv" | Open it through the github.io link, not as a file on your computer. |
| Live map is blank | The IMO number may be wrong, or VesselFinder has no recent data for that ship. |
| No weekly email | Check the email secrets and your spam folder. The report is still on the dashboard under **Reports**. |
| Runs fail at "Unlock the data" | The `REPORT_PASSCODE` secret is missing or was changed. Set it back to the passcode the data was locked with. |
| Dashboard keeps saying "Wrong passcode" | Check for typing errors. The passcode is the value of the `REPORT_PASSCODE` secret. |

## Private report emails

Weekly and monthly reports are emailed directly (with the report attached) to the addresses in the
`EMAIL_TO` secret. Recipients, the sending account and its password are stored only as GitHub
**secrets**: they never appear in the project files, on the dashboard, or in the public run logs, and
recipients are sent as Bcc. Secrets to add under **Settings > Secrets and variables > Actions**:

| Secret | Value |
|---|---|
| `EMAIL_TO` | Recipients, separated by `;` |
| `SMTP_USER` | Sending address, e.g. a Gmail account made for this |
| `SMTP_PASS` | That account's **app password** (Gmail: needs 2-Step Verification, then Google Account > Security > App passwords) |
| `SMTP_HOST`, `SMTP_PORT` | Optional; default `smtp.gmail.com` and `587` |

Until these are set, no email is sent (the report is still on the dashboard). Nothing is ever posted publicly.

## Passcode lock

All position data, run records and reports are stored **encrypted** (AES-256) in `vault/`. Anyone can
download those files, but without the passcode they are unreadable. The passcode is the GitHub secret
`REPORT_PASSCODE` (12+ characters). The scheduled jobs use it to unlock the data during a run and lock it
again before saving.

- **Dashboard:** enter the passcode once. Tick **Remember on this device** to skip it next time; **Lock** (top right) forgets it.
- **Reports:** open from **Reports ▾** on the dashboard. They open unlocked in a new tab. The emailed copy is readable as it is.
- **Share with someone:** give them the dashboard link and the passcode (separately, e.g. link by email, passcode by phone).
- **Forgotten passcode:** read it from wherever you stored it. GitHub never shows a secret again, and the data cannot be recovered without it.
- **Change the passcode:** add a secret `REPORT_PASSCODE_NEW`, run **Actions > Change passcode**, then straight away set `REPORT_PASSCODE` to the new value and delete `REPORT_PASSCODE_NEW`. Everyone needs the new passcode afterwards.
- **What stays readable:** `vessels.csv` (so it can be edited on GitHub), `data/status.json` (run times and counts only) and the program files.
- **Run logs** on the Actions tab are public. They show counts only, never ship IDs, names or positions.
