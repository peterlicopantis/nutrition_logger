from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager, closing
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from food_lookup import FoodLookupError, lookup_foods
from food_library import (FORMAT as FOOD_BACKUP_FORMAT, VERSION as FOOD_BACKUP_VERSION,
                          validate_foods, extra_factor, checked_number as checked_library_number,
                          category_name, category_list, PERMANENT_CATEGORY)

BASE_DIR = Path(__file__).resolve().parent
FOODS_PATH = BASE_DIR / "foods.json"
DB_PATH = BASE_DIR / "melb.db"
CONFIG_PATH = BASE_DIR / "config.json"
SALT_CATEGORY = PERMANENT_CATEGORY
CATEGORIES = [SALT_CATEGORY]

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
FOOD_LIBRARY_LOCK = threading.RLock()


def load_foods() -> dict:
    with FOODS_PATH.open("r", encoding="utf-8") as f:
        foods = json.load(f)
    for name, meta in foods.items():
        meta.setdefault("salt_extra_weight_factor", extra_factor(name, meta))
    return foods


def save_foods(foods: dict, categories: list[str] | None = None) -> None:
    with FOOD_LIBRARY_LOCK:
        init_db()
        names = category_list(foods, load_categories() if categories is None else categories)
        write_library_files(foods, names)
        record_library_version(foods, names)


def locked_day_snapshot(day: str) -> dict | None:
    with db() as conn:
        try:
            row = conn.execute("SELECT snapshot_json FROM day_locks WHERE day = ?", (day,)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table: day_locks" in str(exc):
                return None  # Existing databases may be read before their first upgrade.
            raise
    return json.loads(row["snapshot_json"]) if row else None


def locked_day_error(day: str):
    if locked_day_snapshot(day) is not None:
        return jsonify(ok=False, error="This day is locked. Unlock it before making changes."), 423
    return None


def serialize_day_write(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        # Serialize locking against all entry writes, including requests from
        # another tab or phone. No write can pass a check and then race a lock.
        with FOOD_LIBRARY_LOCK:
            init_db()
            return function(*args, **kwargs)
    return wrapped


def normalize_checkbox_entries(conn, foods: dict, day: str | None = None) -> None:
    today = day or date.today().isoformat()
    if conn.execute("SELECT 1 FROM day_locks WHERE day = ?", (today,)).fetchone():
        return
    for name, meta in foods.items():
        if meta.get("input_mode") == "checkbox":
            conn.execute("""UPDATE daily_entries SET amount = ?, updated_at = ?
                            WHERE day = ? AND food_name = ? AND amount > 0 AND amount != ?""",
                         (meta["checkbox_amount"], datetime.now().isoformat(timespec="seconds"),
                          today, name, meta["checkbox_amount"]))


def load_categories(foods: dict | None = None) -> list[str]:
    path = FOODS_PATH.with_name("categories.json")
    stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return category_list(load_foods() if foods is None else foods, stored)


def write_library_files(foods: dict, categories: list[str]) -> None:
    tmp = FOODS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(foods, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(FOODS_PATH)
    path = FOODS_PATH.with_name("categories.json")
    tmp_categories = path.with_suffix(".json.tmp")
    tmp_categories.write_text(json.dumps(categories, indent=2), encoding="utf-8")
    tmp_categories.replace(path)


def database_history_backup() -> None:
    if not DB_PATH.exists():
        return
    with closing(sqlite3.connect(DB_PATH)) as source:
        if source.execute("SELECT 1 FROM sqlite_master WHERE name = 'food_library_versions'").fetchone():
            return
        folder = DB_PATH.parent / "database_backups"
        folder.mkdir(exist_ok=True)
        path = folder / ("before-library-history-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".db")
        with closing(sqlite3.connect(path)) as destination:
            source.backup(destination)


def initialize_library_history() -> None:
    with db() as conn:
        if conn.execute("SELECT 1 FROM food_library_versions LIMIT 1").fetchone():
            return
        foods = load_foods()
        categories = load_categories(foods)
        values = (json.dumps(foods, allow_nan=False), json.dumps(categories), datetime.now().isoformat(timespec="seconds"))
        # The old application used Meal for salt, so its baseline retains that rule.
        conn.execute("""INSERT INTO food_library_versions(effective_day, foods_json, categories_json, salt_category, created_at)
                        VALUES ('0001-01-01', ?, ?, 'Meal', ?)""", values)
        conn.execute("""INSERT INTO food_library_versions(effective_day, foods_json, categories_json, salt_category, created_at)
                        VALUES (?, ?, ?, ?, ?)""",
                     (date.today().isoformat(), values[0], values[1], SALT_CATEGORY, values[2]))
    path = FOODS_PATH.with_name("categories.json")
    if not path.exists():
        path.write_text(json.dumps(categories, indent=2), encoding="utf-8")


def record_library_version(foods: dict, categories: list[str]) -> None:
    with db() as conn:
        latest = conn.execute("SELECT * FROM food_library_versions ORDER BY id DESC LIMIT 1").fetchone()
        if latest and json.loads(latest["foods_json"]) == foods and json.loads(latest["categories_json"]) == categories and latest["salt_category"] == SALT_CATEGORY:
            return
        normalize_checkbox_entries(conn, foods)
        conn.execute("""INSERT INTO food_library_versions(effective_day, foods_json, categories_json, salt_category, created_at)
                        VALUES (?, ?, ?, ?, ?)""",
                     (date.today().isoformat(), json.dumps(foods, allow_nan=False), json.dumps(categories),
                      SALT_CATEGORY, datetime.now().isoformat(timespec="seconds")))


def library_state_for_day(day: str) -> dict:
    init_db()
    snapshot = locked_day_snapshot(day)
    if snapshot is not None:
        return {**snapshot["library"], "historical": day < date.today().isoformat()}
    with FOOD_LIBRARY_LOCK:
        current = load_foods()
        categories = load_categories(current)
        # This also records manual JSON edits when the application next observes them.
        record_library_version(current, categories)
        with db() as conn:
            row = conn.execute("""SELECT * FROM food_library_versions
                                  WHERE effective_day <= ? ORDER BY effective_day DESC, id DESC LIMIT 1""",
                               (day,)).fetchone()
    return {"foods": json.loads(row["foods_json"]),
            "categories": category_list(json.loads(row["foods_json"]), json.loads(row["categories_json"])),
            "salt_category": row["salt_category"],
            "historical": day < date.today().isoformat()}


def load_foods_for_day(day: str) -> dict:
    return library_state_for_day(day)["foods"]


def selected_category(form, categories: list[str]) -> str:
    name = category_name(form.get("new_category", "").strip() or form.get("category", SALT_CATEGORY))
    return next((existing for existing in categories if existing.casefold() == name.casefold()), name)




def load_config() -> dict:
    if not CONFIG_PATH.exists():
        cfg = {
            "shortcut_name": "MELB Log Nutrition",
            "health_import_token": secrets.token_urlsafe(24),
        }
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        return cfg
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with FOOD_LIBRARY_LOCK:
        database_history_backup()
        with db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_entries (
                    day TEXT NOT NULL,
                    food_name TEXT NOT NULL,
                    amount REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (day, food_name)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS day_foods (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    name TEXT NOT NULL,
                    serving_label TEXT NOT NULL,
                    servings REAL NOT NULL,
                    calories REAL NOT NULL,
                    protein REAL NOT NULL,
                    carbs REAL NOT NULL,
                    fat REAL NOT NULL,
                    fiber REAL,
                    source_url TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(day_foods)")}
            if "serving_g" not in columns:
                conn.execute("ALTER TABLE day_foods ADD COLUMN serving_g REAL")
                for row in conn.execute("SELECT id, serving_label FROM day_foods").fetchall():
                    grams = serving_grams_from_label(row["serving_label"])
                    if grams is not None:
                        conn.execute("UPDATE day_foods SET serving_g = ? WHERE id = ?", (grams, row["id"]))
            if "salt_extra_weight_factor" not in columns:
                conn.execute("ALTER TABLE day_foods ADD COLUMN salt_extra_weight_factor REAL NOT NULL DEFAULT 0")
                for row in conn.execute("SELECT id, name FROM day_foods").fetchall():
                    factor = 1.5 if is_rice_for_spins(row["name"]) else 0.0
                    conn.execute("UPDATE day_foods SET salt_extra_weight_factor = ? WHERE id = ?", (factor, row["id"]))
            if "include_in_spins" not in columns:
                conn.execute("ALTER TABLE day_foods ADD COLUMN include_in_spins INTEGER NOT NULL DEFAULT 0")
            conn.execute("CREATE INDEX IF NOT EXISTS day_foods_day ON day_foods(day)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS health_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    day TEXT NOT NULL,
                    active_calories REAL,
                    resting_calories REAL,
                    steps REAL,
                    weight REAL,
                    captured_at TEXT NOT NULL
                )
                """
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS food_library_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, effective_day TEXT NOT NULL,
                foods_json TEXT NOT NULL, categories_json TEXT NOT NULL,
                salt_category TEXT NOT NULL, created_at TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS food_library_versions_day ON food_library_versions(effective_day)")
            conn.execute("""CREATE TABLE IF NOT EXISTS day_locks (
                day TEXT PRIMARY KEY, snapshot_json TEXT NOT NULL, locked_at TEXT NOT NULL)""")
        initialize_library_history()


def safe_day(raw: str | None) -> str:
    if not raw:
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return date.today().isoformat()


def load_amounts(day: str) -> dict[str, float]:
    snapshot = locked_day_snapshot(day)
    if snapshot is not None:
        return snapshot["amounts"]
    with db() as conn:
        rows = conn.execute(
            "SELECT food_name, amount FROM daily_entries WHERE day = ?", (day,)
        ).fetchall()
    return {r["food_name"]: float(r["amount"]) for r in rows}


def totals_for(foods: dict, amounts: dict[str, float]) -> dict[str, float]:
    totals = {
        "calc_calories": 0.0,
        "calories": 0.0,
        "protein": 0.0,
        "carbs": 0.0,
        "fat": 0.0,
        "fiber": 0.0,
        "soluble_fiber": 0.0,
        "insoluble_fiber": 0.0,
        "unknown_fiber": 0.0,
    }
    for name, amount in amounts.items():
        if name not in foods or not amount:
            continue
        meta = foods[name]
        p = float(meta.get("protein_per_g", 0) or 0)
        c = float(meta.get("carbs_per_g", 0) or 0)
        f = float(meta.get("fat_per_g", 0) or 0)
        kcal = float(meta.get("cal_per_g", 0) or 0)
        fiber = float(meta.get("fiber_per_g", 0) or 0)
        s_frac = meta.get("soluble_frac")
        i_frac = meta.get("insoluble_frac")

        totals["calc_calories"] += amount * (p * 4 + c * 4 + f * 9)
        totals["calories"] += amount * kcal
        totals["protein"] += amount * p
        totals["carbs"] += amount * c
        totals["fat"] += amount * f

        item_fiber = amount * fiber
        totals["fiber"] += item_fiber
        if s_frac is not None and i_frac is not None:
            totals["soluble_fiber"] += item_fiber * float(s_frac)
            totals["insoluble_fiber"] += item_fiber * float(i_frac)
        else:
            totals["unknown_fiber"] += item_fiber

    return {k: round(v, 2) for k, v in totals.items()}


def load_day_foods(day: str) -> list[dict]:
    snapshot = locked_day_snapshot(day)
    if snapshot is not None:
        return snapshot["day_foods"]
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM day_foods WHERE day = ? ORDER BY id", (day,)
        ).fetchall()
    return [dict(row) for row in rows]


def day_food_totals_for(entries: list[dict]) -> dict[str, float]:
    # Rows preserve nutrition for one serving at the time they were logged.
    foods = {}
    amounts = {}
    for entry in entries:
        key = str(entry["id"])
        foods[key] = {
            "cal_per_g": entry["calories"],
            "protein_per_g": entry["protein"],
            "carbs_per_g": entry["carbs"],
            "fat_per_g": entry["fat"],
            "fiber_per_g": entry["fiber"],
        }
        amounts[key] = entry["servings"]
    return totals_for(foods, amounts)


def combined_totals(foods: dict, amounts: dict, day_foods: list[dict]) -> dict:
    regular = totals_for(foods, amounts)
    extra = day_food_totals_for(day_foods)
    return {key: round(value + extra[key], 2) for key, value in regular.items()}


def day_totals_for(day: str, foods: dict | None = None) -> dict:
    snapshot = locked_day_snapshot(day)
    if snapshot is not None:
        foods = snapshot["library"]["foods"]
    return combined_totals(
        foods if foods is not None else load_foods_for_day(day),
        load_amounts(day),
        load_day_foods(day),
    )


def required_day(payload: dict) -> str:
    raw = payload.get("day")
    if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        raise ValueError("Choose a valid date for this food.")
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise ValueError("Choose a valid date for this food.") from None


def nutrition_number(payload: dict, key: str, optional: bool = False) -> float | None:
    value = payload.get(key)
    if optional and value in (None, ""):
        return None
    if value is None or isinstance(value, bool):
        raise ValueError(f"Enter a valid number for {key}.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"Enter a valid number for {key}.") from None
    if not math.isfinite(number) or number < 0 or number > 1_000_000:
        raise ValueError(f"{key.capitalize()} must be a finite number from 0 to 1,000,000.")
    return number


def serving_grams_from_label(label: str) -> float | None:
    """Only an explicit, unambiguous gram mass can describe one serving."""
    matches = re.findall(r"(?<![0-9.,])([0-9]+(?:[.,][0-9]+)?)\s*(?:g|grams?)\b", label, re.I)
    if len(matches) != 1:
        return None
    grams = float(matches[0].replace(",", "."))
    return grams if 0 < grams <= 1_000_000 else None


def is_rice_for_spins(name: str) -> bool:
    key = name.strip().casefold()
    return key in {"enriched rice", "rice", "white rice", "brown rice", "cooked rice",
                   "cooked white rice", "cooked brown rice"} or key.startswith("rice,")


app.jinja_env.globals["is_rice_for_spins"] = is_rice_for_spins
app.jinja_env.globals["salt_extra_factor"] = extra_factor

def salt_spins_for(foods: dict, amounts: dict, entries: list[dict], salt_category: str = SALT_CATEGORY) -> dict:
    grams = 0.0
    rice_bonus = 0.0
    for name, meta in foods.items():
        if meta.get("category") != salt_category or name.startswith("Cal"):
            continue
        amount = float(amounts.get(name, 0))
        grams += amount
        rice_bonus += amount * extra_factor(name, meta)
    for entry in entries:
        if not entry.get("include_in_spins") or entry.get("serving_g") is None:
            continue
        mass = float(entry["serving_g"]) * float(entry["servings"])
        grams += mass
        rice_bonus += mass * extra_factor(entry.get("name", ""), entry)
    grams += rice_bonus
    return {"grams": round(grams, 3), "spins": round(grams / 29, 1),
            "rice_bonus": round(rice_bonus, 3)}


def day_food_response(day: str, **extra):
    return jsonify(
        ok=True,
        totals=day_totals_for(day),
        day_food_totals=day_food_totals_for(load_day_foods(day)),
        **extra,
    )


@app.get("/api/food-lookup")
def api_food_lookup():
    query = request.args.get("q", "").strip()
    if not query or len(query) > 250:
        return jsonify(ok=False, error="Enter a food name, a short description, or a barcode (up to 250 characters)."), 400
    try:
        result = lookup_foods(query)
    except FoodLookupError as exc:
        return jsonify(ok=False, error=str(exc)), 503
    return jsonify(ok=True, **result)


@app.post("/api/day-food")
@serialize_day_write
def api_add_day_food():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send the food details as JSON."), 400
    try:
        day = required_day(payload)
        name = payload.get("name", "")
        serving_label = payload.get("serving_label", "1 serving")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
            raise ValueError("Enter a food name (up to 160 characters).")
        if not isinstance(serving_label, str) or not serving_label.strip() or len(serving_label.strip()) > 120:
            raise ValueError("Enter a serving description (up to 120 characters).")
        servings = nutrition_number(payload, "servings")
        if servings <= 0:
            raise ValueError("Servings must be greater than zero.")
        nutrition = {key: nutrition_number(payload, key) for key in ("calories", "protein", "carbs", "fat")}
        nutrition["fiber"] = nutrition_number(payload, "fiber", optional=True)
        salt_factor = extra_factor(name, payload)
        checked_library_number(salt_factor, "Extra salt weight", 100)
        serving_g = nutrition_number(payload, "serving_g", optional=True)
        if serving_g is None:
            serving_g = serving_grams_from_label(serving_label)
        elif serving_g <= 0:
            raise ValueError("Grams per serving must be greater than zero.")
        source_url = payload.get("source_url") or ""
        if not isinstance(source_url, str):
            raise ValueError("Invalid nutrition source.")
        if source_url and not re.fullmatch(
            r"https://(?:world[.]openfoodfacts[.]org/product/[0-9]{8,14}|fdc[.]nal[.]usda[.]gov/food-details/[0-9]+/nutrients)",
            source_url,
        ):
            raise ValueError("Invalid nutrition source.")
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400

    error = locked_day_error(day)
    if error is not None:
        return error
    init_db()
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO day_foods(
                day, name, serving_label, servings, calories, protein, carbs, fat,
                fiber, source_url, created_at, serving_g, salt_extra_weight_factor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day, name.strip(), serving_label.strip(), servings,
                nutrition["calories"], nutrition["protein"], nutrition["carbs"],
                nutrition["fat"], nutrition["fiber"], source_url,
                datetime.now().isoformat(timespec="seconds"), serving_g, salt_factor,
            ),
        )
        entry = dict(conn.execute("SELECT * FROM day_foods WHERE id = ?", (cursor.lastrowid,)).fetchone())
    return day_food_response(day, entry=entry)


@app.patch("/api/day-food/<int:entry_id>/salt")
@serialize_day_write
def api_update_day_food_salt(entry_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send the selected date and salt selection as JSON."), 400
    try:
        day = required_day(payload)
        included = payload.get("include_in_spins")
        if not isinstance(included, bool):
            raise ValueError("Choose whether to include this food in spins.")
        grams = nutrition_number(payload, "serving_g", optional=True) if "serving_g" in payload else None
        if "serving_g" in payload and (grams is None or grams <= 0):
            raise ValueError("Enter grams per serving greater than zero.")
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    error = locked_day_error(day)
    if error is not None:
        return error
    init_db()
    with db() as conn:
        row = conn.execute("SELECT * FROM day_foods WHERE id = ? AND day = ?", (entry_id, day)).fetchone()
        if row is None:
            return jsonify(ok=False, error="That food was not found on this date."), 404
        if grams is None:
            grams = row["serving_g"]
        if included and grams is None:
            return jsonify(ok=False, error="Enter this food's grams per serving before including it in spins."), 400
        conn.execute("UPDATE day_foods SET serving_g = ?, include_in_spins = ? WHERE id = ? AND day = ?",
                     (grams, int(included), entry_id, day))
        entry = dict(conn.execute("SELECT * FROM day_foods WHERE id = ?", (entry_id,)).fetchone())
    return day_food_response(day, entry=entry)


@app.delete("/api/day-food/<int:entry_id>")
@serialize_day_write
def api_remove_day_food(entry_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send the selected date as JSON."), 400
    try:
        day = required_day(payload)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    error = locked_day_error(day)
    if error is not None:
        return error
    init_db()
    with db() as conn:
        cursor = conn.execute(
            "DELETE FROM day_foods WHERE id = ? AND day = ?", (entry_id, day)
        )
    if not cursor.rowcount:
        return jsonify(ok=False, error="That food was not found on this date."), 404
    return day_food_response(day)


def latest_health_snapshot(day: str):
    snapshot = locked_day_snapshot(day)
    if snapshot is not None:
        return snapshot["health_snapshot"]
    with db() as conn:
        row = conn.execute(
            """
            SELECT day, active_calories, resting_calories, steps, weight, captured_at
            FROM health_snapshots
            WHERE day = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (day,),
        ).fetchone()
    return dict(row) if row else None


@app.get("/")
def dashboard():
    init_db()
    cfg = load_config()
    day = safe_day(request.args.get("day"))
    library_state = library_state_for_day(day)
    foods = library_state["foods"]
    amounts = load_amounts(day)

    grouped = {cat: [] for cat in library_state["categories"]}
    for name, meta in foods.items():
        cat = meta.get("category", "Test")
        grouped.setdefault(cat, []).append(
            {
                **meta,
                "name": name,
                "amount": amounts.get(name, 0.0),
            }
        )

    # Keep category definitions in the library, but show only populated
    # dashboard sections apart from the permanent Dawg Bowl category.
    grouped = {category: items for category, items in grouped.items()
               if items or category == PERMANENT_CATEGORY}

    day_foods = load_day_foods(day)
    totals = combined_totals(foods, amounts, day_foods)
    snapshot = latest_health_snapshot(day)
    balance = None
    if snapshot:
        active = snapshot.get("active_calories")
        resting = snapshot.get("resting_calories")
        if active is not None and resting is not None:
            balance = round(totals["calories"] - float(active) - float(resting), 2)

    return render_template(
        "dashboard.html",
        day=day,
        salt_spins=salt_spins_for(foods, amounts, day_foods, library_state["salt_category"]),
        salt_category=library_state["salt_category"],
        historical_library=library_state["historical"],
        day_locked=locked_day_snapshot(day) is not None,
        grouped=grouped,
        day_foods=day_foods,
        day_food_totals=day_food_totals_for(day_foods),
        totals=totals,
        shortcut_name=cfg["shortcut_name"],
        health_snapshot=snapshot,
        energy_balance=balance,
    )


@app.post("/api/day-lock")
@serialize_day_write
def api_day_lock():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send the selected day and lock state as JSON."), 400
    try:
        day = required_day(payload)
        locked = payload.get("locked")
        if not isinstance(locked, bool):
            raise ValueError("Choose lock or unlock for this day.")
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    existing = locked_day_snapshot(day)
    if locked:
        if existing is None:
            library = library_state_for_day(day)
            snapshot = {"library": library, "amounts": load_amounts(day),
                        "day_foods": load_day_foods(day),
                        "health_snapshot": latest_health_snapshot(day)}
            with db() as conn:
                conn.execute("INSERT INTO day_locks(day, snapshot_json, locked_at) VALUES (?, ?, ?)",
                             (day, json.dumps(snapshot, allow_nan=False),
                              datetime.now().isoformat(timespec="seconds")))
    else:
        with db() as conn:
            conn.execute("DELETE FROM day_locks WHERE day = ?", (day,))
            if day >= date.today().isoformat():
                normalize_checkbox_entries(conn, load_foods(), day)
    return jsonify(ok=True, day=day, locked=locked)


@app.post("/api/entry")
@serialize_day_write
def api_entry():
    init_db()
    payload = request.get_json(force=True)
    day = safe_day(payload.get("day"))
    error = locked_day_error(day)
    if error is not None:
        return error
    food_name = str(payload.get("food_name", ""))
    try:
        amount = float(payload.get("amount", 0))
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid amount")
    except (TypeError, ValueError, OverflowError):
        return jsonify({"ok": False, "error": "Invalid amount"}), 400

    foods = load_foods_for_day(day)
    if food_name not in foods:
        return jsonify({"ok": False, "error": "Unknown food"}), 404
    meta = foods[food_name]
    if meta.get("input_mode") == "checkbox" and amount not in (0, float(meta["checkbox_amount"])):
        return jsonify(ok=False, error="Checkbox foods must be unchecked or one configured portion."), 400

    with db() as conn:
        if amount == 0:
            conn.execute(
                "DELETE FROM daily_entries WHERE day = ? AND food_name = ?",
                (day, food_name),
            )
        else:
            conn.execute(
                """
                INSERT INTO daily_entries(day, food_name, amount, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(day, food_name)
                DO UPDATE SET amount = excluded.amount, updated_at = excluded.updated_at
                """,
                (day, food_name, amount, datetime.now().isoformat(timespec="seconds")),
            )

    # Return authoritative totals so the UI stays in sync.
    return jsonify({"ok": True, "totals": day_totals_for(day, foods)})


@app.post("/reset")
@serialize_day_write
def reset_day():
    init_db()
    day = safe_day(request.form.get("day"))
    error = locked_day_error(day)
    if error is not None:
        return error
    with db() as conn:
        conn.execute("DELETE FROM daily_entries WHERE day = ?", (day,))
        conn.execute("DELETE FROM day_foods WHERE day = ?", (day,))
    return redirect(url_for("dashboard", day=day))


@app.route("/foods", methods=["GET", "POST"])
def foods_page():
    init_db()
    foods = load_foods()
    message = None
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        try:
            category = selected_category(request.form, load_categories(foods))
            mode = request.form.get("input_mode", "slider")
            if mode not in ("slider", "checkbox"):
                raise ValueError("Choose slider or checkbox for this food.")
            serving_g = float(request.form.get("serving_g", "0"))
            calories = float(request.form.get("calories", "0"))
            protein = float(request.form.get("protein", "0"))
            carbs = float(request.form.get("carbs", "0"))
            fat = float(request.form.get("fat", "0"))
            fiber = float(request.form.get("fiber", "0"))
        except ValueError as exc:
            error = str(exc) if ("Category" in str(exc) or "slider" in str(exc)) else "All nutrition values must be numbers."
        else:
            if not name or len(name) > 160:
                error = "Enter a food name up to 160 characters."
            elif name in foods:
                error = "That food already exists."
            elif serving_g <= 0:
                error = "Serving size must be greater than 0 g."
            elif not all(math.isfinite(value) and 0 <= value <= 1_000_000 for value in (serving_g, calories, protein, carbs, fat, fiber)):
                error = "Serving size and nutrition must be finite numbers up to 1,000,000."
            else:
                foods[name] = {
                    "cal_per_g": calories / serving_g,
                    "protein_per_g": protein / serving_g,
                    "carbs_per_g": carbs / serving_g,
                    "fat_per_g": fat / serving_g,
                    "fiber_per_g": fiber / serving_g,
                    "soluble_frac": None,
                    "insoluble_frac": None,
                    "category": category,
                    "input_mode": mode,
                    "checkbox_amount": serving_g,
                }
                with FOOD_LIBRARY_LOCK:
                    current = load_foods()
                    if name in current:
                        return foods_page_result(error="That food already exists.", status=400)
                    current[name] = foods[name]
                    current[name]["salt_extra_weight_factor"] = extra_factor(name, current[name])
                    save_foods(current)
                message = f"Added {name}."

    return foods_page_result(message=message, error=error)



def library_backup_payload(foods: dict) -> dict:
    return {"format": FOOD_BACKUP_FORMAT, "version": FOOD_BACKUP_VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "categories": load_categories(foods), "foods": validate_foods(foods)}


def backup_food_library(foods: dict) -> None:
    folder = FOODS_PATH.parent / "food_backups"
    folder.mkdir(exist_ok=True)
    name = "foods-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + secrets.token_hex(4) + ".json"
    (folder / name).write_text(json.dumps(library_backup_payload(foods), indent=2, allow_nan=False), encoding="utf-8")


def foods_page_result(message=None, error=None, status=200):
    init_db()
    foods = load_foods()
    categories = load_categories(foods)
    grouped = {category: [] for category in categories}
    for name, meta in foods.items():
        grouped[meta.get("category", "Test")].append((name, meta))
    folder = FOODS_PATH.parent / "food_backups"
    backups = sorted((p.name for p in folder.glob("foods-*.json")), reverse=True)[:5] if folder.exists() else []
    return render_template("foods.html", grouped=grouped, categories=categories,
                           message=message, error=error, backups=backups), status


@app.get("/foods/export")
def export_food_library():
    init_db()
    payload = library_backup_payload(load_foods())
    response = app.response_class(json.dumps(payload, indent=2, allow_nan=False), mimetype="application/json")
    response.headers["Content-Disposition"] = 'attachment; filename="melb-foods-' + date.today().isoformat() + '.json"'
    return response


@app.get("/foods/backups/<filename>")
def download_food_backup(filename):
    if not re.fullmatch(r"foods-[0-9]{8}-[0-9]{6}-(?:[0-9]{6}-)?[0-9a-f]{8}[.]json", filename):
        return jsonify(ok=False, error="Backup not found."), 404
    return send_from_directory(FOODS_PATH.parent / "food_backups", filename, as_attachment=True)


def read_import_bundle() -> tuple[dict, list[str]]:
    if request.content_length is not None and request.content_length > 2_000_000:
        raise ValueError("The food backup must be smaller than 1 MB.")
    uploaded = request.files.get("backup")
    if uploaded is None or not uploaded.filename:
        raise ValueError("Choose a food backup JSON file.")
    raw = uploaded.stream.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("The food backup must be smaller than 1 MB.")
    def invalid_constant(value):
        raise ValueError("Backup numbers must be finite.")
    payload = json.loads(raw.decode("utf-8-sig"), parse_constant=invalid_constant)
    foods = validate_foods(payload)
    categories = payload.get("categories", []) if isinstance(payload, dict) and payload.get("format") == FOOD_BACKUP_FORMAT else []
    return foods, category_list(foods, categories)


@app.post("/foods/import/preview")
def preview_food_import():
    init_db()
    try:
        imported, imported_categories = read_import_bundle()
    except (ValueError, UnicodeError) as exc:
        return jsonify(ok=False, error=str(exc)), 400
    current = load_foods()
    return jsonify(ok=True, foods=[
        {"name": name, "category": meta["category"],
         "salt_extra_weight_factor": meta["salt_extra_weight_factor"],
         "exists": name in current}
        for name, meta in imported.items()
    ])


@app.post("/foods/import")
def import_food_library():
    try:
        if request.content_length is not None and request.content_length > 2_000_000:
            raise ValueError("The food backup must be smaller than 1 MB.")
        mode = request.form.get("mode", "merge")
        if mode not in ("merge", "replace"):
            raise ValueError("Choose merge or replace.")
        imported, imported_categories = read_import_bundle()
        if "selection_present" in request.form:
            if request.form["selection_present"] != "1":
                raise ValueError("Preview the backup and choose foods first.")
            selected = set(request.form.getlist("selected_food"))
            if not selected:
                raise ValueError("Select at least one food to import.")
            if not selected.issubset(imported):
                raise ValueError("A selected food is not in this backup. Preview the file again.")
            all_selected = len(selected) == len(imported)
            imported = {name: meta for name, meta in imported.items() if name in selected}
            if not all_selected:
                imported_categories = category_list(imported)
        init_db()
        with FOOD_LIBRARY_LOCK:
            current = load_foods()
            updated = {**current, **imported} if mode == "merge" else imported
            categories = category_list(updated, load_categories(current) + imported_categories if mode == "merge" else imported_categories)
            backup_food_library(current)
            save_foods(updated, categories=categories)
    except (ValueError, UnicodeError) as exc:
        return foods_page_result(error=str(exc), status=400)
    return foods_page_result(message=f"Imported {len(imported)} foods ({mode}). A backup of the previous library was saved.")


@app.post("/foods/remove")
def remove_library_food():
    init_db()
    name = request.form.get("name", "")
    with FOOD_LIBRARY_LOCK:
        foods = load_foods()
        if name not in foods:
            return foods_page_result(error="That food is no longer in the library.", status=404)
        backup_food_library(foods)
        del foods[name]
        save_foods(foods)
    return foods_page_result(message=f"Removed {name} from the library. A backup was saved.")


@app.post("/foods/category/remove")
def remove_library_category():
    init_db()
    category = request.form.get("category", "")
    with FOOD_LIBRARY_LOCK:
        foods = load_foods()
        categories = load_categories(foods)
        if category == PERMANENT_CATEGORY:
            return foods_page_result(error="Dawg Bowl is permanent and cannot be removed.", status=400)
        if category not in categories:
            return foods_page_result(error="That category is no longer in the library.", status=404)
        if any(meta["category"] == category for meta in foods.values()):
            return foods_page_result(error="Move or remove this category's foods before removing it.", status=400)
        backup_food_library(foods)
        save_foods(foods, categories=[name for name in categories if name != category])
    return foods_page_result(message=f"Removed the empty {category} category. Past days are unchanged; a backup was saved.")


@app.post("/foods/move")
def move_library_food():
    init_db()
    name = request.form.get("name", "")
    try:
        with FOOD_LIBRARY_LOCK:
            foods = load_foods()
            if name not in foods:
                return foods_page_result(error="That food is no longer in the library.", status=404)
            category = selected_category(request.form, load_categories(foods))
            backup_food_library(foods)
            foods[name]["category"] = category
            save_foods(foods)
    except ValueError as exc:
        return foods_page_result(error=str(exc), status=400)
    return foods_page_result(message=f"Moved {name} to {category}. Past days keep their original library.")


@app.post("/foods/advanced")
def update_food_advanced():
    init_db()
    name = request.form.get("name", "")
    try:
        factor = checked_library_number(float(request.form.get("salt_extra_weight_factor", "")), "Extra salt weight", 100)
    except ValueError as exc:
        return foods_page_result(error=str(exc), status=400)
    with FOOD_LIBRARY_LOCK:
        foods = load_foods()
        if name not in foods:
            return foods_page_result(error="That food is no longer in the library.", status=404)
        updated = dict(foods[name])
        updated["salt_extra_weight_factor"] = factor
        if "input_mode" in request.form:
            updated["input_mode"] = request.form["input_mode"]
        if "checkbox_amount" in request.form:
            try:
                updated["checkbox_amount"] = float(request.form["checkbox_amount"])
            except ValueError:
                return foods_page_result(error="Enter a valid amount per check.", status=400)
        try:
            updated = validate_foods({name: updated})[name]
        except ValueError as exc:
            return foods_page_result(error=str(exc), status=400)
        backup_food_library(foods)
        foods[name] = updated
        save_foods(foods)
    return foods_page_result(message=f"Updated advanced settings for {name}. A backup was saved.")



@app.post("/api/health-snapshot")
@serialize_day_write
def api_health_snapshot():
    init_db()
    cfg = load_config()
    token = request.headers.get("X-MELB-Token") or request.args.get("token")
    if token != cfg["health_import_token"]:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    payload = request.get_json(force=True, silent=True) or {}

    def optional_number(key):
        value = payload.get(key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(key)

    try:
        active = optional_number("active_calories")
        resting = optional_number("resting_calories")
        steps = optional_number("steps")
        weight = optional_number("weight")
    except ValueError as exc:
        return jsonify({"ok": False, "error": f"Invalid number: {exc}"}), 400

    day = safe_day(payload.get("day"))
    error = locked_day_error(day)
    if error is not None:
        return error
    captured = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO health_snapshots(
                day, active_calories, resting_calories, steps, weight, captured_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (day, active, resting, steps, weight, captured),
        )
    return jsonify({"ok": True, "day": day, "captured_at": captured})


@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    cfg = load_config()
    message = None
    if request.method == "POST":
        shortcut_name = request.form.get("shortcut_name", "").strip()
        if shortcut_name:
            cfg["shortcut_name"] = shortcut_name
            save_config(cfg)
            message = "Settings saved."

    import_url = request.host_url.rstrip("/") + "/api/health-snapshot"
    return render_template(
        "settings.html",
        cfg=cfg,
        import_url=import_url,
        message=message,
    )


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(app.static_folder, "favicon.ico", mimetype="image/x-icon")


@app.get("/manifest.json")
def manifest():
    return {
        "name": "MELB Nutrition",
        "short_name": "MELB",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#111827",
        "theme_color": "#111827",
        "icons": [
            {"src": url_for("static", filename="android-chrome-192x192.png"),
             "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="android-chrome-512x512.png"),
             "sizes": "512x512", "type": "image/png"},
        ],
    }


if __name__ == "__main__":
    init_db()
    load_config()
    try:
        from waitress import serve

        print("MELB Nutrition is running on port 8501.")
        print("Open http://127.0.0.1:8501 on this PC.")
        serve(app, host="0.0.0.0", port=8501, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=8501, debug=False)
