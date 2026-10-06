# Apple Health Shortcut setup

The web app cannot directly write Apple Health from Windows. The iPhone Shortcut is the bridge.

The app sends one JSON text payload to a Shortcut named **MELB Log Nutrition**. The payload looks like:

```json
{
  "source": "MELB Nutrition",
  "date": "2026-10-06",
  "calories": 2427,
  "protein": 162,
  "carbs": 231,
  "fat": 61,
  "fiber": 31
}
```

## Shortcut 1 — MELB Log Nutrition

Create a new Shortcut on the iPhone and name it exactly:

`MELB Log Nutrition`

The app name can be changed later from **Settings**, but the two names must match.

Build the Shortcut with this logic:

1. Add **Get Dictionary from Input** and give it **Shortcut Input**.
2. Get the dictionary value for `date`. Convert that ISO date text to a Date (the action may appear as **Get Dates from Input**). Keep this as `Log Date`.
3. Get dictionary value `calories`.
4. Add **Log Health Sample**:
   - Type: **Dietary Energy**
   - Value: the `calories` value
   - Unit: kcal
   - Date: `Log Date`
5. Get dictionary value `protein`.
6. Add **Log Health Sample**:
   - Type: **Protein**
   - Value: the `protein` value
   - Unit: g
   - Date: `Log Date`
7. Do the same for:
   - `carbs` → **Carbohydrates** → g
   - `fat` → **Total Fat** → g
   - `fiber` → **Dietary Fiber** → g
8. Optional: add **Show Notification** at the end, e.g. `MELB nutrition logged`.

The first time it runs, iOS should ask for permission to write those Health categories. Allow the categories you want MELB to log.

### Important: avoid duplicate Health entries

**Log Health Sample creates new samples.** The dashboard therefore treats the Apple Health button as an end-of-day export. If you run it twice for the same day, Apple Health can count both sets of samples.

If you edit the day after exporting it, do not simply export it again unless you first remove the earlier MELB/Shortcuts nutrition entries from Apple Health.

## Shortcut 2 — optional Health → PC snapshot

The PC app also exposes an endpoint that can receive Health totals from the iPhone. This is optional; the nutrition logger works without it.

Open **Settings** in the MELB app *from the iPhone*. It displays:

- the correct `/api/health-snapshot` URL for the address you are currently using
- your private `X-MELB-Token`

An iPhone Shortcut can use **Find Health Samples** to collect values such as today's Active Energy, Resting Energy, Steps, and latest Weight, then send JSON with **Get Contents of URL**:

```json
{
  "day": "2026-10-06",
  "active_calories": 814,
  "resting_calories": 1731,
  "steps": 12483,
  "weight": 139.2
}
```

Use:
- Method: `POST`
- Request Body: JSON
- Header: `X-MELB-Token` with the token shown in MELB Settings

After a successful POST, the newest snapshot appears on the dashboard and MELB calculates `food calories - active calories - resting calories`.

The exact aggregation steps for Health samples vary slightly with the iOS/Shortcuts version. Get the basic nutrition-writing Shortcut working first; the endpoint is already ready when you want to add this second Shortcut.
