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

### Start automatically on Windows

After setup, double-click ENABLE_AUTOSTART.bat once. It adds a shortcut to
your current Windows user's Startup folder. MELB then runs silently when you
sign in; VS Code and a command window are not needed. Open
http://127.0.0.1:8501 on the PC or your existing phone address.

Startup errors are saved in logs/startup.log. Logs stay local and are ignored
by Git. The launcher exits if MELB is already running. Keep this project folder
in place; rerun ENABLE_AUTOSTART.bat if you move it.

To disable automatic startup, press Win+R, enter shell:startup, and remove
the MELB Nutrition shortcut. This does not stop a currently running instance.
The app is unavailable while the PC is shut down or asleep, and starts after
Windows sign-in rather than before sign-in.

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

## Foods for just one day

On the dashboard, select a date and use **Add food for this day**:

- **Food lookup** accepts a product name, a short description such as
  "Oh I had a rice krispy treat", or a package barcode. Choose the matching
  brand and size, review the nutrition, and adjust the servings before saving.
- **Enter macros** lets you enter the calories, protein, carbs, fat, and
  optional fiber you know. Enter values for one serving and the number of
  servings eaten. Leave fiber blank when unknown.

These foods are saved only to the selected date in melb.db; they do not become
rows in the permanent foods list. You can add the same food more than once and
remove individual entries. They count toward daily totals, energy balance, and
the Apple Health export. **Reset day** clears both regular entries and these
foods for that date.

Lookup uses a small set of verified [USDA FoodData Central](https://fdc.nal.usda.gov/)
reference foods for plain-food searches, and [Open Food Facts](https://world.openfoodfacts.org)
for packaged products. No API key or extra package is required. This is food
database lookup with support for simple descriptions, not a general AI nutrition
estimator. Plain foods in generic_foods.json (such as carrot, apple, banana,
rice, and egg) work offline. All supported reference foods show a typical
USDA household portion with estimated edible grams, preparation, and a source
link. Choose a size or household measure, or enter your measured grams.
The per-serving macros scale automatically; servings eaten multiplies that
portion once. For example, a medium raw carrot defaults to approximately 61 g,
an apple to 182 g, and a cup of cooked rice to 158 g. Size words such as
"large carrot" select a sourced size where available. These are estimates,
not measurements of your individual food. Packaged-product lookup needs internet access;
match the brand, flavor, size, and label because community data cannot guarantee
an exact package match.

Clearing or changing the search text clears its results and cancels the pending
request. Press Enter or Look up food once and wait for its status. Transient
packaged-food database errors retry automatically once; a slow lookup times out
with a retry message. Packaged results are matched against product names and
brands, rather than words found only in ingredients.

When a product has no usable serving information, its results are explicitly
shown **per 100 g**, with a required blank weight field. Enter grams to calculate
the macros for your portion before saving. The app never treats 100 g as one
bar or item. Packaged label servings keep their label macros and weight when
available; volume-only servings (such as 250 ml) remain usable without assuming
milliliters equal grams. Item-count hints prefill only known single-item reference
portions; check the servings eaten for household measures and packaged labels.
Macro edits remain proportional when you subsequently change size or grams.
Logged entries keep their final serving label and macro snapshot for that date.
Reference coverage comes from generic_foods.json; foods without reliable portion
information need a measured weight or manual label entry.
Missing core macros are excluded from search results; missing fiber stays
unknown. Data is attributed to Open Food Facts under
[ODbL](https://opendatacommons.org/licenses/odbl/1-0/).


## Salt shaker spins

The dashboard estimates spins as Meal-category grams plus the mass of checked
daily logged foods, divided by 29 (one decimal place). Other permanent categories
do not contribute. Temporary foods start unchecked; use Include in spins after
logging them. Their mass is grams per serving times servings eaten, counted once.

Lookup entries preserve their selected portion weight. Existing entries use an
unambiguous gram weight written in their serving label when available. Foods
without a known gram mass have a Grams per serving field in the logged list; enter
that weight first, then check Include in spins. Volume is never treated as grams.
Selections and weights stay with that entry and date, without changing nutrition.


For rice, salt weight includes the entered grams plus an additional 1.5 times
that weight: 200 g rice adds 300 g extra, counting as 500 g for spins.
The summary shows this rice bonus separately. Checked temporary plain-rice
entries use the same rule. Rice treats/cakes do not get the rice bonus.
This multiplier affects the salt calculation only, not calories or other macros.


## Food-library backups and advanced salt settings

Saved foods offers Export all foods (JSON), Import foods, Remove on each food,
and Advanced settings. Exports include all nutrition fields, categories, fiber
fractions, and salt_extra_weight_factor. They do not include daily logs, which
remain in melb.db. Imports accept the versioned MELB export or original foods.json.

Merge adds new foods and updates matching names; Replace restores the library
exactly from the file. Validation completes before any changes. Invalid files
leave the library untouched. An automatic backup is saved before each import,
removal, or advanced-setting change in food_backups/ (ignored by Git). The five
most recent backups can be downloaded from the Saved foods page; older backups
remain in that directory.

Removing a food removes it from the current library and sliders. Existing daily
amounts remain in the database and become usable again if the same food name is
restored. Temporary daily food snapshots are independent of the library.

Extra weight for salt spins is configured per food: 0 uses entered grams only;
1.5 adds 150 percent extra, giving 2.5 times salt weight. The setting affects
Meal foods only and does not alter macros. Rice defaults to 1.5 when an older
file has no setting; an explicit 0 disables its bonus. Slider badges show the
actual configured multiplier. Selected temporary foods preserve their own salt
factor with their nutrition snapshot.

When choosing an import file, a validated preview lists each food, its category,
whether it updates an existing name, and any extra salt-weight setting. All foods
start checked. Uncheck individual foods or use Select all to select/clear the
list. Import selected foods applies only checked entries. Merge keeps unchecked
current foods; Replace keeps only the selected backup foods. Previewing a file
does not change the library or create an automatic backup.

## Categories and past-day food libraries

Dawg Bowl always exists, including when the food library is empty. It is the
category used for current salt calculations. Existing Meal foods stay in Meal;
use Move to another category on Saved foods to move individual foods into
Dawg Bowl or any other category. New-category fields on food creation and food
moves create custom categories. Empty categories are retained and exported.

The SQLite database now stores food-library versions, including nutrition,
categories, and salt settings. A past day uses the final library version known
for that day; today's moves, removals, settings edits and imports do not replace
past definitions. Past-day sliders can still update that day's amounts using
their preserved nutrition. Older Meal-based salt rules stay with historical
versions, while new/current versions use Dawg Bowl.

Before the initial upgrade, the existing database is backed up automatically to
database_backups/ (ignored by Git). Dates from before version tracking use the
definitions available at the upgrade as their baseline. Changes made before
tracking began cannot be reconstructed automatically without an older backup.
Temporary foods already retain their own nutrition and salt snapshots.

## Checkbox foods

Choose Dashboard control: Checkbox when adding a new saved food. One check
includes exactly the serving size and calories/macros entered in that form;
unchecked contributes zero. Other foods remain sliders.

Existing foods can switch control type under Advanced settings. Amount per check
sets the fixed grams (or kcal for calorie-adjustment entries), using that food's
saved nutrition. Saved foods displays the complete macros added by one check.
Dawg Bowl checkbox foods also contribute their fixed mass and configured extra
salt weight. The multiplier never changes nutrition.

Control type and checkbox_amount are stored with food definitions, exported
with backups, and included in library history. Converting a currently logged
slider food to a checkbox, or changing its checked portion, updates today's
nonzero amount to one configured portion. Past days retain their old control,
portion and logged amount.

## Locking a day

Use Lock day on the dashboard to freeze the selected day's food library,
categories, nutrition settings, amounts, temporary foods, salt selections and
Health snapshot. The lock persists in melb.db across restarts. Library edits,
imports, removals and checkbox-portion changes do not alter a locked day's view
or totals. Entry edits, additions/removals, reset and Health imports are rejected
by the server while locked, including requests from another tab or phone.

Unlock day re-enables editing. A current/future unlocked day resumes using the
current food library; historical days continue to use their historical version.
If a checked portion changed while locked, it is applied when unlocking a current
or future day. The lock button waits for pending quantity saves before capturing
the snapshot. Apple Health export and navigation remain available while locked.


Empty categories have a Remove category button on Saved foods. Removal deletes
the category from the current library and dropdowns, with an automatic backup.
Populated categories must have their foods moved or removed first. Dawg Bowl
cannot be removed. Historical versions and locked-day snapshots retain their
original category definitions.

In **Saved foods**, use **Up** and **Down** beneath a food to reorder it within its category on the homepage. Order is saved in food backups and daily library history; past and locked days keep their saved order.

### Local food library and Git

Your editable `foods.json` and `categories.json` are local data and are ignored
by Git, like `melb.db`. A fresh clone creates `foods.json` from the tracked
`foods.default.json` on first use and derives its categories automatically.
Existing local files, including an intentionally empty library, are preserved.
Use Saved foods export/import to transfer or back up your personalized library.

When upgrading an older checkout, commit the staged removal of the local files
from Git along with the starter-library change. The files remain on disk.
Older branches that still track these filenames can overwrite ignored local
files during checkout; back up your library and bring this change into those
branches before switching to them.
