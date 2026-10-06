# MELB Nutrition

This is the phone-friendly version of the uploaded MELB Jupyter notebook.

## What was carried over

Only the foods referenced by these four notebook groups were kept:

- `MELB_sources` → **Meal**
- `cream_sources` → **Cream**
- `things` → **Calories**
- `test_sources` → **Test**

That is **35 foods total**. Everything else from the notebook ingredient dictionary was omitted.

The app preserves the notebook's:
- label calories
- calculated calories from protein/carbs/fat
- protein, carbs, and fat
- fiber
- soluble/insoluble fiber metadata where your selected foods already had it

## What the app does

- Runs on the Windows PC.
- Opens in a normal browser on the PC or iPhone.
- Saves each day's entries in `melb.db`.
- Keeps foods in the editable `foods.json`.
- Lets you add foods from the phone or PC by entering a nutrition label.
- Converts new foods to the same per-gram model as the notebook.
- Generates a one-tap iPhone Shortcut handoff for Apple Health.
- Has an optional private API for sending Apple Health daily totals back to the PC.
- Can be added to the iPhone Home Screen so it behaves much more like an app.

## 1. First-time PC setup

You need Python 3.11+ installed.

1. Extract this folder somewhere permanent, for example:
   `C:\Users\YOURNAME\Documents\MELB Nutrition`
2. Double-click `SETUP_WINDOWS.bat`.
3. When setup finishes, double-click `RUN_MELB_APP.bat`.
4. Leave that black command window open while using the app.
5. On the PC, open:
   `http://127.0.0.1:8501`

Your foods and logs live inside this folder, so don't delete `foods.json` or `melb.db`.

## 2. Open it on the iPhone at home

The PC and iPhone need to be on the same Wi-Fi.

1. On Windows, open Command Prompt and run:
   `ipconfig`
2. Find the PC's **IPv4 Address** under the active Wi-Fi/Ethernet adapter, for example `192.168.1.123`.
3. On the iPhone open Safari and visit:
   `http://192.168.1.123:8501`
4. If Windows Firewall asks whether Python can accept connections, allow it on **Private networks**.

If the page does not load, Windows Firewall is the first thing to check.

## 3. Access it away from home — recommended

Use Tailscale instead of exposing port 8501 to the public internet.

1. Install Tailscale on the Windows PC and iPhone.
2. Sign in to the same Tailscale account on both.
3. Find the Windows PC's Tailscale IP (normally `100.x.x.x`).
4. On the iPhone visit:
   `http://100.x.x.x:8501`

Keep Tailscale connected on the iPhone. Do **not** port-forward 8501 on your router.

## 4. Make it feel like an iPhone app

Open MELB Nutrition in Safari, then:

1. Tap **Share**.
2. Tap **Add to Home Screen**.
3. Name it `MELB`.

It will launch from the Home Screen in a standalone web-app view.

## 5. Apple Health

Read `APPLE_HEALTH_SHORTCUTS.md`.

The important part is creating an iPhone Shortcut named:

`MELB Log Nutrition`

The dashboard's **Send totals to Apple Health** button launches that Shortcut and passes the selected day's calorie/macro totals as JSON.

Apple's Shortcuts URL scheme supports passing text to a Shortcut from another app/browser, which is the bridge used here.

## 6. Adding foods

Open **Add Food**.

Enter:
- name
- Meal / Cream / Calories / Test category
- serving size in grams
- calories per serving
- protein, carbs, fat, fiber per serving

The app automatically converts the label to per-gram values and saves it to `foods.json`.

New foods stay there across restarts.

## 7. The special Calories controls

Your notebook's pseudo-food controls were preserved:

- `Cal`, `Cal2`, `Cal3`, `Cal4`: the amount field represents **kcal**
- `Protein`: amount represents grams protein
- `carb`: amount represents grams carbs
- `Fat`: amount represents grams fat

They calculate exactly like your existing notebook model.

## 8. Backup

Back up these files occasionally:
- `foods.json`
- `melb.db`
- `config.json` (created on first run)

`MELB_filtered.ipynb` is included as a cleaned notebook backup containing only the same 35 foods.
