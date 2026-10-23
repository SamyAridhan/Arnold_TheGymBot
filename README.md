# Gym log bot

A one-handed gym logbook in Telegram. It records plates and reps for every set,
shows your last record next to today's, and saves everything to a Google Sheet.
It never gives advice.

## Setup (about 20 minutes, once)

### 1. Telegram bot
1. In Telegram, message **@BotFather** → `/newbot` → pick a name. Copy the **token**.
2. Message **@userinfobot** to get your numeric **chat id**.

### 2. Google Sheet
1. In Google Sheets: **File → Import → Upload** `gym-log.xlsx` → *Replace spreadsheet*
   (or create a new one). Copy the **sheet id** from the URL:
   `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.
2. In [Google Cloud Console](https://console.cloud.google.com): create a project →
   **APIs & Services → Enable APIs** → enable **Google Sheets API**.
3. **IAM & Admin → Service Accounts → Create**. Open it → **Keys → Add key → JSON**.
   A `.json` file downloads; keep it private.
4. Back in the sheet, **Share** it with the service account's email
   (`...@...iam.gserviceaccount.com`) as **Editor**.

The bot creates the `Test Sets`, `Test Sessions` and `Test Notes` tabs itself on first run.

### 3. GitHub
1. Create a **private** repo and push this folder to it.
2. **Settings → Secrets and variables → Actions → New repository secret**, add:

   | Secret | Value |
   | --- | --- |
   | `TELEGRAM_TOKEN` | the BotFather token |
   | `CHAT_ID` | your numeric chat id |
   | `SHEET_ID` | the sheet id |
   | `GOOGLE_CREDENTIALS` | the whole contents of the JSON key file |

3. **Actions → gym-bot → Run workflow** to start it now. After that it keeps itself
   running (each run ~5h40m, the next one takes over).

> **Minutes:** GitHub Free gives a private repo 2,000 Actions minutes a month, and
> running 24/7 needs about 44,000. Standard runners are free in a **public** repo,
> which is how Hans runs. Your secrets stay hidden either way; only the code is visible.
> Your workout data lives in the sheet, not the repo (`tests/gym-log.xlsx` is
> git-ignored). The other option is a small always-on host.

## Using it

| You do | Where |
| --- | --- |
| `/go` | Home, or back to your open session |
| Tap UB1 / LB1 / UB2 / LB2 | Starts a session (start time recorded) |
| Tap **✅ Log**, or type `7 9`, `7x9`, `7 9 +` | Logs the set shown by the stepper |
| `− / +` | Adjust plates or reps first; the stepper starts on last time's numbers |
| `✏ S1` | Edit or delete a logged set |
| `/undo` | Remove the last logged set |
| 📋 Pick next | Choose the next exercise, add one from another session, or Finish |
| 🔁 Variant | Switch machine or technique; Last follows the variant |
| 📝 Notes | Workout note (today) or setup note (every time) |
| 🏁 Finish | Ends the session (end time recorded); add a session note there |

Sessions with no sets for 90 minutes close themselves, with the end time set to your
last set. If the bot restarts mid-workout, `/go` resumes where you were.

### Test mode
`/test` starts a session that saves to the **Test** tabs only. At Finish, tap
**🔍 Check save** to re-read the sheet and confirm every set arrived, then
**🧹 Clear test data** (or `/cleartest`). Your real log and program are never touched.

## Changing the program
Edit the sheet, then restart the bot (re-run the workflow):
- **Program** tab: which exercises are in each session, in default order.
- **Exercises** tab: one row per exercise variant. `unit` = plates / lb / reps,
  `steps` = loads for + and − (e.g. `0, 10, 12`), `warmups`, `working_sets`,
  `hidden` = yes to retire a variant without losing its history.

## Developing
```
pip install -r requirements.txt pytest openpyxl
python -m pytest            # offline: fake Telegram, fake sheet, your real data
python -m gymbot.demo       # print the main screens
```
Run locally with the four secrets as environment variables: `python -m gymbot`.
Only one copy can poll the bot at a time, so stop the GitHub run first.
