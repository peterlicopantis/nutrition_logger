from __future__ import annotations

import json
import math
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

from food_lookup import FoodLookupError, lookup_foods

BASE_DIR = Path(__file__).resolve().parent
FOODS_PATH = BASE_DIR / "foods.json"
DB_PATH = BASE_DIR / "melb.db"
CONFIG_PATH = BASE_DIR / "config.json"
CATEGORIES = ["Meal", "Cream", "Calories", "Test"]

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def load_foods() -> dict:
    with FOODS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_foods(foods: dict) -> None:
    tmp = FOODS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(foods, indent=2), encoding="utf-8")
    tmp.replace(FOODS_PATH)


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


def safe_day(raw: str | None) -> str:
    if not raw:
        return date.today().isoformat()
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        return date.today().isoformat()


def load_amounts(day: str) -> dict[str, float]:
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
    return combined_totals(
        foods if foods is not None else load_foods(),
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

def salt_spins_for(foods: dict, amounts: dict, entries: list[dict]) -> dict:
    grams = 0.0
    rice_bonus = 0.0
    for name, meta in foods.items():
        if meta.get("category") != "Meal" or name.startswith("Cal"):
            continue
        amount = float(amounts.get(name, 0))
        grams += amount
        if is_rice_for_spins(name):
            rice_bonus += amount * 1.5
    for entry in entries:
        if not entry.get("include_in_spins") or entry.get("serving_g") is None:
            continue
        mass = float(entry["serving_g"]) * float(entry["servings"])
        grams += mass
        if is_rice_for_spins(entry.get("name", "")):
            rice_bonus += mass * 1.5
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

    init_db()
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO day_foods(
                day, name, serving_label, servings, calories, protein, carbs, fat,
                fiber, source_url, created_at, serving_g
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day, name.strip(), serving_label.strip(), servings,
                nutrition["calories"], nutrition["protein"], nutrition["carbs"],
                nutrition["fat"], nutrition["fiber"], source_url,
                datetime.now().isoformat(timespec="seconds"), serving_g,
            ),
        )
        entry = dict(conn.execute("SELECT * FROM day_foods WHERE id = ?", (cursor.lastrowid,)).fetchone())
    return day_food_response(day, entry=entry)


@app.patch("/api/day-food/<int:entry_id>/salt")
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
def api_remove_day_food(entry_id: int):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(ok=False, error="Send the selected date as JSON."), 400
    try:
        day = required_day(payload)
    except ValueError as exc:
        return jsonify(ok=False, error=str(exc)), 400
    init_db()
    with db() as conn:
        cursor = conn.execute(
            "DELETE FROM day_foods WHERE id = ? AND day = ?", (entry_id, day)
        )
    if not cursor.rowcount:
        return jsonify(ok=False, error="That food was not found on this date."), 404
    return day_food_response(day)


def latest_health_snapshot(day: str):
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
    foods = load_foods()
    cfg = load_config()
    day = safe_day(request.args.get("day"))
    amounts = load_amounts(day)

    grouped = {cat: [] for cat in CATEGORIES}
    for name, meta in foods.items():
        cat = meta.get("category", "Test")
        grouped.setdefault(cat, []).append(
            {
                "name": name,
                "amount": amounts.get(name, 0.0),
                **meta,
            }
        )

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
        salt_spins=salt_spins_for(foods, amounts, day_foods),
        grouped=grouped,
        day_foods=day_foods,
        day_food_totals=day_food_totals_for(day_foods),
        totals=totals,
        shortcut_name=cfg["shortcut_name"],
        health_snapshot=snapshot,
        energy_balance=balance,
    )


@app.post("/api/entry")
def api_entry():
    init_db()
    payload = request.get_json(force=True)
    day = safe_day(payload.get("day"))
    food_name = str(payload.get("food_name", ""))
    try:
        amount = float(payload.get("amount", 0))
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("Invalid amount")
    except (TypeError, ValueError, OverflowError):
        return jsonify({"ok": False, "error": "Invalid amount"}), 400

    foods = load_foods()
    if food_name not in foods:
        return jsonify({"ok": False, "error": "Unknown food"}), 404

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
def reset_day():
    init_db()
    day = safe_day(request.form.get("day"))
    with db() as conn:
        conn.execute("DELETE FROM daily_entries WHERE day = ?", (day,))
        conn.execute("DELETE FROM day_foods WHERE day = ?", (day,))
    return redirect(url_for("dashboard", day=day))


@app.route("/foods", methods=["GET", "POST"])
def foods_page():
    foods = load_foods()
    message = None
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        category = request.form.get("category", "Meal")
        try:
            serving_g = float(request.form.get("serving_g", "0"))
            calories = float(request.form.get("calories", "0"))
            protein = float(request.form.get("protein", "0"))
            carbs = float(request.form.get("carbs", "0"))
            fat = float(request.form.get("fat", "0"))
            fiber = float(request.form.get("fiber", "0"))
        except ValueError:
            error = "All nutrition values must be numbers."
        else:
            if not name:
                error = "Food name is required."
            elif name in foods:
                error = "That food already exists."
            elif serving_g <= 0:
                error = "Serving size must be greater than 0 g."
            elif category not in CATEGORIES:
                error = "Invalid category."
            elif min(calories, protein, carbs, fat, fiber) < 0:
                error = "Nutrition values cannot be negative."
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
                }
                save_foods(foods)
                message = f"Added {name}."

    grouped = {cat: [] for cat in CATEGORIES}
    for name, meta in load_foods().items():
        grouped.setdefault(meta.get("category", "Test"), []).append((name, meta))

    return render_template(
        "foods.html",
        grouped=grouped,
        categories=CATEGORIES,
        message=message,
        error=error,
    )


@app.post("/api/health-snapshot")
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
