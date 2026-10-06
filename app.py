from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, url_for

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


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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

    totals = totals_for(foods, amounts)
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
        grouped=grouped,
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
        amount = max(0.0, float(payload.get("amount", 0)))
    except (TypeError, ValueError):
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
    return jsonify({"ok": True, "totals": totals_for(foods, load_amounts(day))})


@app.post("/reset")
def reset_day():
    day = safe_day(request.form.get("day"))
    with db() as conn:
        conn.execute("DELETE FROM daily_entries WHERE day = ?", (day,))
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
        except (TypeError, ValueError):
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


@app.get("/manifest.json")
def manifest():
    return {
        "name": "MELB Nutrition",
        "short_name": "MELB",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#111827",
        "theme_color": "#111827",
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
