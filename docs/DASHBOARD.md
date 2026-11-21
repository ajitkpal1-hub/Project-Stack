# Management dashboard (Coefficient + Google Sheets)

A Google Sheet that management can open any time, showing per week and per area (Dombivli, Thakurli, Kalyan):
how many items people classified, how many were hazardous or medical, and how many donations were listed,
approved and completed. Coefficient refreshes it from Supabase on a schedule.

```
Supabase ── reporting views (weekly counts only) ── read-only login reloop_reporting
   │
Coefficient (Google Sheets add-on, PostgreSQL connector, scheduled refresh)
   │
Sheet "RELOOP management dashboard": data tabs + a Dashboard tab with charts
```

## What the numbers mean (say this to management)
- **Classifications** = items identified by the website scanner or the voice helper. Counted from the day migration
  0006 went live; earlier weeks have no data. Demo-mode answers are not counted.
- **Area** for scans comes from an optional "Your area" question on the scan page; many people skip it, so expect a
  large "Other / not given" group. Voice classifications are "Other / not given" (the voice tools don't receive an area).
  Donation areas come from the locality and PIN code the donor typed.
- **Donations listed / approved / completed**: listings created that week, those an admin approved (available, reserved
  or completed), and those marked completed.
- No carbon, weight or impact figures: RELOOP has no measured basis for them.
- No personal data: the views hold counts only. The usage table stores date, channel, lane and area, never photos,
  text, IP addresses or accounts.

## 1. Run the migration (once)
Supabase → SQL Editor → New query → paste `supabase/migrations/0006_reporting.sql` → Run.

## 2. Give the read-only login a password (once)
Make a password (e.g. `.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(24))"`), then in the
SQL editor run, with your password in place of the placeholder:
```sql
alter role reloop_reporting with login password 'PASTE-PASSWORD-HERE';
```
Keep the password only in Coefficient (and a password manager). Never commit it.

**Optional: confirmed PIN codes.** Areas are matched from the locality name first. To also match by PIN, add only
PIN codes you have checked:
```sql
insert into reporting.area_pins (pin_code, area) values ('421201', 'Dombivli');  -- example: check before adding
```

## 3. Connect Coefficient
1. Create a Google Sheet **RELOOP management dashboard** → Extensions → Add-ons → Get add-ons → install **Coefficient**.
2. Coefficient sidebar → **Import from…** → **PostgreSQL** → add a connection:
   - **Host / Port:** Supabase → **Connect** (top of the project) → **Session pooler**: copy the host
     (it looks like `aws-…-ap-northeast-2.pooler.supabase.com`) and port **5432**
   - **Database:** `postgres`
   - **Username:** `reloop_reporting.ilkhnbdamwisdraxdzdo` (role name, a dot, then the project ref)
   - **Password:** the one from step 2; SSL on if asked
3. Import each view into its own tab (Coefficient: **Custom SQL** or pick the table):
   - tab **weekly_summary**: `select * from reporting.weekly_summary`
   - tab **weekly_donations**: `select * from reporting.weekly_donations order by week_start desc`
   - tab **weekly_classifications**: `select * from reporting.weekly_classifications order by week_start desc`
4. For each import: **Schedule** → refresh **daily** (or weekly, Monday morning). Scheduled refresh may need a paid
   Coefficient plan; otherwise press **Refresh** before a meeting.

`weekly_summary` columns: A `week_start`, B `area`, C `classifications`, D `hazardous_or_medical_classifications`,
E `donations_listed`, F `donations_approved`, G `donations_completed`.

## 4. Build the Dashboard tab
Add a tab **Dashboard**:

| Cell | Put | Formula |
|---|---|---|
| A1 | `Week starting` | |
| B1 | latest week | `=MAX(weekly_summary!A2:A)` |
| A3:A6 | `Dombivli`, `Thakurli`, `Kalyan`, `Other / not given` | |
| B2 / B3 | `Classifications` / per area | `=SUMIFS(weekly_summary!$C:$C, weekly_summary!$A:$A, $B$1, weekly_summary!$B:$B, $A3)` (fill down) |
| C2 / C3 | `Hazardous or medical` | same with `$D:$D` |
| D2 / D3 | `Donations listed` | same with `$E:$E` |
| E2 / E3 | `Donations completed` | same with `$G:$G` |
| A7 | `Total` | `=SUM(B3:B6)` and across |

Charts (Insert → Chart, from a pivot table: Insert → Pivot table on `weekly_summary`):
- **Classifications per week by area:** rows `week_start`, columns `area`, values SUM `classifications` → line chart.
- **Donations per week by area:** same with `donations_listed` and `donations_completed` → column chart.
- **What people ask about:** pivot on `weekly_classifications`, rows `lane`, values SUM `classifications` → bar chart.

Share the sheet with management as **Viewer**. Coefficient's refresh keeps it current.

## Checking it works
Do one real scan on `/scan`, choosing an area, then press Refresh in Coefficient: this week's row for that area should
show 1 more classification.
