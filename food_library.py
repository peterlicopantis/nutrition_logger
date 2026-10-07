"""Validate portable food-library backups and per-food salt settings."""
import copy
import math

FORMAT = "melb-food-library"
VERSION = 1
PERMANENT_CATEGORY = "Dawg Bowl"
NUTRIENTS = ("cal_per_g", "protein_per_g", "carbs_per_g", "fat_per_g", "fiber_per_g")


def rice_name(name):
    key = name.strip().casefold()
    return key in {"enriched rice", "rice", "white rice", "brown rice", "cooked rice",
                   "cooked white rice", "cooked brown rice"} or key.startswith("rice,")


def extra_factor(name, meta):
    return meta.get("salt_extra_weight_factor", 1.5 if rice_name(name) else 0.0)


def checked_number(value, label, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number.")
    try:
        valid = math.isfinite(value) and 0 <= value <= maximum
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be finite and between 0 and {maximum:g}.")
    return value


def category_name(value):
    if not isinstance(value, str):
        raise ValueError("Category names must be text.")
    name = value.strip()
    if not name or len(name) > 50 or any(ord(char) < 32 for char in name):
        raise ValueError("Category names must contain 1 to 50 visible characters.")
    return PERMANENT_CATEGORY if name.casefold() == PERMANENT_CATEGORY.casefold() else name


def category_list(foods, categories=()):
    result = [PERMANENT_CATEGORY]
    for value in list(categories) + [meta.get("category") for meta in foods.values()]:
        name = category_name(value)
        if name not in result:
            result.append(name)
    if len(result) > 200:
        raise ValueError("The food library supports at most 200 categories.")
    return result


def validate_foods(data):
    if not isinstance(data, dict):
        raise ValueError("The food library must contain an object of food names.")
    if "format" in data:
        if data.get("format") != FORMAT or type(data.get("version")) is not int or data["version"] != VERSION:
            raise ValueError("This food backup format or version is not supported.")
        if "categories" in data:
            if not isinstance(data["categories"], list):
                raise ValueError("Backup categories must be a list.")
            category_list({}, data["categories"])
        data = data.get("foods")
    if not isinstance(data, dict) or len(data) > 2000:
        raise ValueError("The backup must contain a food library with at most 2,000 foods.")
    result = {}
    for name, meta in data.items():
        if not isinstance(name, str) or not name.strip() or name != name.strip() or len(name) > 160:
            raise ValueError("Food names must contain 1 to 160 characters without leading or trailing spaces.")
        if not isinstance(meta, dict):
            raise ValueError(f"{name}: choose a valid food definition.")
        item = copy.deepcopy(meta)
        item["category"] = category_name(item.get("category"))
        for key in NUTRIENTS:
            item[key] = checked_number(item.get(key), f"{name}: {key}", 1_000_000)
        for key in ("soluble_frac", "insoluble_frac"):
            value = item.get(key)
            item[key] = None if value is None else checked_number(value, f"{name}: {key}", 1)
        item["salt_extra_weight_factor"] = checked_number(extra_factor(name, item), f"{name}: extra salt weight", 100)
        mode = item.get("input_mode", "slider")
        if mode not in ("slider", "checkbox"):
            raise ValueError(f"{name}: display must be slider or checkbox.")
        if mode == "checkbox" or "checkbox_amount" in item:
            amount = checked_number(item.get("checkbox_amount"), f"{name}: amount per check", 1_000_000)
            if amount <= 0:
                raise ValueError(f"{name}: amount per check must be greater than zero.")
            item["checkbox_amount"] = amount
        result[name] = item
    return result
