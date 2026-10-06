"""Search packaged-food labels from Open Food Facts without an API key.

Official schema and usage notes:
https://openfoodfacts.github.io/documentation/docs/Product-Opener/api/
https://openfoodfacts.github.io/documentation/docs/Product-Opener/schemas/schemas/product_nutrition/
https://openfoodfacts.github.io/documentation/docs/Product-Opener/schemas/schemas/product_nutrition_v3.5/

Full-text search still uses the documented legacy CGI endpoint; barcode reads
use API v3.6. Results are candidates for the user to check against their package.
Set MELB_FOOD_LOOKUP_STAGING=1 for live development requests to the OFF staging
server. Automated tests should mock urlopen instead of contacting either server.
"""
from __future__ import annotations

import base64
import copy
import json
import math
import os
import re
import threading
import time
from collections import OrderedDict, deque
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "MELBNutrition/1.0 (local personal food diary)"
REQUEST_TIMEOUT = 8
MAX_RESPONSE_BYTES = 2_000_000
CACHE_SECONDS = 3600
CACHE_SIZE = 128
PRODUCT_FIELDS = ",".join((
    "code", "product_name", "product_name_en", "generic_name", "brands",
    "serving_size", "serving_quantity", "serving_quantity_unit",
    "product_quantity_unit", "nutrition_data_per", "nutriments", "nutrition",
))

_lock = threading.RLock()
_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
_search_requests: deque[float] = deque()
_product_requests: deque[float] = deque()


class FoodLookupError(Exception):
    """A food lookup could not be completed; the message is safe to display."""


def normalize_query(raw: str) -> tuple[str, float]:
    """Remove a diary sentence prefix, keeping product variants and units."""
    if not isinstance(raw, str):
        raise FoodLookupError("Enter a food name, a short description, or a barcode.")
    query = re.sub(r"\s+", " ", raw).strip()
    if not query or len(query) > 250:
        raise FoodLookupError("Enter a food name or description up to 250 characters.")

    prefix = re.match(
        r"^(?:oh[\s,!]+)?i\s+(?:(?:just|also)\s+)?(?:had|ate|have eaten|have had)\s+",
        query, re.IGNORECASE,
    )
    servings = 1.0
    if prefix:
        query = query[prefix.end():].strip()
        quantity = re.match(r"^(\d+(?:\.\d+)?)\s+(.+)$", query)
        if quantity:
            rest = quantity.group(2)
            # These describe size, time, or a product variant, not item count.
            units = r"^(?:g|grams?|kg|mg|ml|l|liters?|litres?|oz|ounces?|lbs?|pounds?|percent|%|calories?|kcal|hours?|minutes?)\b"
            if not re.match(units, rest, re.IGNORECASE) and not re.match(r"^(?:3 musketeers|100 grand)\b", query, re.IGNORECASE):
                value = float(quantity.group(1))
                if 0 < value <= 100:
                    servings = value
                    query = rest
        query = re.sub(r"^(?:a|an)\s+", "", query, flags=re.IGNORECASE)

    query = query.strip(" \t\r\n\"'.!?")
    query = re.sub(
        r"\brice\s+(?:krispy|krispie|krispies|crispy|crispies)\s+treats?\b",
        "Rice Krispies Treats", query, flags=re.IGNORECASE,
    )
    if not query:
        raise FoodLookupError("Include the food name after your description.")
    return query, servings


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _serving_grams(product: dict) -> float | None:
    quantity = _number(product.get("serving_quantity"))
    unit = _text(product.get("serving_quantity_unit")).lower()
    if unit == "g" and quantity:
        return quantity
    # Older records can lack serving_quantity_unit. Require a written gram
    # measurement rather than assuming that their numeric quantity is grams.
    label = _text(product.get("serving_size"))
    matches = re.findall(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:g|grams?)\b", label, re.I)
    if unit not in ("", "g") or len(matches) != 1:
        return None
    grams = _number(matches[0].replace(",", "."))
    return grams if grams else None


def _macros(get_value) -> dict | None:
    calories = get_value("energy-kcal")
    if calories is None:
        kilojoules = get_value("energy-kj")
        if kilojoules is None:
            kilojoules = get_value("energy")
        if kilojoules is not None:
            calories = kilojoules / 4.184
    protein = get_value("proteins")
    # Prefer total carbohydrates when supplied by a US/Canadian label.
    carbs = get_value("carbohydrates-total")
    if carbs is None:
        carbs = get_value("carbohydrates")
    fat = get_value("fat")
    if any(value is None for value in (calories, protein, carbs, fat)):
        return None
    return {
        "calories": calories, "protein": protein, "carbs": carbs,
        "fat": fat, "fiber": get_value("fiber"),
    }


def _legacy_macros(nutriments: dict, suffix: str) -> dict | None:
    def get_value(nutrient: str) -> float | None:
        # _serving and _100g are normalized units; *_value is ambiguous.
        if nutriments.get(nutrient + "_modifier"):
            return None
        return _number(nutriments.get(f"{nutrient}_{suffix}"))
    return _macros(get_value)


def _current_macros(nutrient_set: dict) -> dict | None:
    nutrients = nutrient_set.get("nutrients")
    if not isinstance(nutrients, dict):
        return None

    def get_value(nutrient: str) -> float | None:
        record = nutrients.get(nutrient)
        if not isinstance(record, dict):
            return None
        if record.get("modifier") or record.get("source") == "estimate":
            return None
        # The aggregate is normalized to grams/kcal/kJ. Do not substitute
        # value_computed (e.g. energy inferred from other macros) for a label.
        return _number(record.get("value"))
    return _macros(get_value)


def normalize_product(product: dict) -> dict | None:
    """Return usable as-sold label data, with an explicit nutrition basis."""
    if not isinstance(product, dict):
        return None
    barcode = str(product.get("code", ""))
    if not re.fullmatch(r"[0-9]{8,14}", barcode):
        return None
    name = _text(product.get("product_name_en")) or _text(product.get("product_name"))
    name = name or _text(product.get("generic_name"))
    if not name:
        return None
    serving_g = _serving_grams(product)
    serving_label = _text(product.get("serving_size"))
    if not serving_label:
        serving_label = f"1 serving ({serving_g:g} g)" if serving_g else "1 label serving (size not listed)"

    macros = None
    basis = "100g"
    nutrition = product.get("nutrition")
    aggregate = nutrition.get("aggregated_set") if isinstance(nutrition, dict) else None
    if isinstance(aggregate, dict):
        if aggregate.get("preparation") != "as_sold":
            return None
        per = aggregate.get("per")
        if per in ("100g", "serving"):
            macros = _current_macros(aggregate)
            basis = per
        elif per == "100ml":
            # A liquid can be shown per its written volume serving, but never
            # as grams without a measured mass/density.
            quantity = _number(product.get("serving_quantity"))
            if product.get("serving_quantity_unit") == "ml" and quantity:
                per_100ml = _current_macros(aggregate)
                if per_100ml:
                    macros = {key: value * quantity / 100 if value is not None else None
                              for key, value in per_100ml.items()}
                    basis = "serving"
                    serving_label = _text(product.get("serving_size")) or f"1 serving ({quantity:g} ml)"

    # The legacy search endpoint returns normalized *_serving / *_100g data.
    if not isinstance(aggregate, dict):
        nutriments = product.get("nutriments")
        if isinstance(nutriments, dict):
            macros = _legacy_macros(nutriments, "serving")
            if macros:
                basis = "serving"
            elif product.get("product_quantity_unit") != "ml" and product.get("serving_quantity_unit") != "ml":
                macros = _legacy_macros(nutriments, "100g")
                basis = "100g"
    if macros is None:
        return None
    if basis == "100g" and serving_g:
        macros = {key: value * serving_g / 100 if value is not None else None
                  for key, value in macros.items()}
        basis = "serving"
    if basis == "100g":
        serving_label = "100 g"

    return {
        "name": name[:160], "brand": _text(product.get("brands"))[:200],
        "barcode": barcode, "serving_label": serving_label[:120],
        "serving_g": serving_g, "basis": basis,
        **{key: round(value, 4) if value is not None else None for key, value in macros.items()},
        "source_url": f"https://world.openfoodfacts.org/product/{barcode}",
    }


def _request_json(url: str, *, barcode: bool) -> dict:
    now = time.monotonic()
    timestamps = _product_requests if barcode else _search_requests
    limit = 15 if barcode else 10
    while timestamps and timestamps[0] <= now - 60:
        timestamps.popleft()
    if len(timestamps) >= limit:
        seconds = max(1, math.ceil(60 - (now - timestamps[0])))
        raise FoodLookupError(f"Food lookup is busy. Try again in {seconds} seconds.")
    timestamps.append(now)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if os.environ.get("MELB_FOOD_LOOKUP_STAGING", "").lower() in ("1", "true", "yes"):
        headers["Authorization"] = "Basic " + base64.b64encode(b"off:off").decode("ascii")
    try:
        with urlopen(Request(url, headers=headers), timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise FoodLookupError("The food database returned too much data. Try a more specific name.")
        data = json.loads(raw)
    except HTTPError as error:
        if error.code == 404 and barcode:
            return {"products": []}
        if error.code == 429:
            raise FoodLookupError("The food database is busy. Wait a minute and try again.") from error
        raise FoodLookupError("The food database is unavailable. Try again or enter the label manually.") from error
    except (URLError, OSError, TimeoutError) as error:
        raise FoodLookupError("Couldn't reach the food database. Try again or enter the label manually.") from error
    except (ValueError, UnicodeDecodeError) as error:
        raise FoodLookupError("The food database returned an unreadable result. Try again later.") from error
    if not isinstance(data, dict):
        raise FoodLookupError("The food database returned an unexpected result. Try again later.")
    return data


def lookup_foods(raw: str) -> dict:
    """Find packaged foods for a short description or an 8-14 digit barcode.

    suggested_servings is only a count hint from 'I had 2 ...'; it never changes
    a product's macros or turns 100 g into one item. Missing fiber stays None.
    The app must let the user choose the matching package and confirm quantity.
    """
    query, servings = normalize_query(raw)
    barcode = re.fullmatch(r"[0-9]{8,14}", query) is not None
    cache_key = ("barcode:" if barcode else "search:") + query.casefold()
    # Serialize lookup requests, including cache checks, so concurrent callers
    # cannot duplicate a query or exceed the per-process request budget.
    with _lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(cache_key)
            products = copy.deepcopy(cached[1])
        else:
            staging = os.environ.get("MELB_FOOD_LOOKUP_STAGING", "").lower() in ("1", "true", "yes")
            base_url = "https://world.openfoodfacts.net" if staging else "https://world.openfoodfacts.org"
            if barcode:
                url = f"{base_url}/api/v3.6/product/{query}?" + urlencode({"fields": PRODUCT_FIELDS, "lc": "en"})
            else:
                url = f"{base_url}/cgi/search.pl?" + urlencode({
                    "search_terms": query, "search_simple": 1, "action": "process",
                    "json": 1, "page_size": 24, "fields": PRODUCT_FIELDS,
                })
            data = _request_json(url, barcode=barcode)
            raw_products = [data["product"]] if barcode and isinstance(data.get("product"), dict) else data.get("products", [])
            if not isinstance(raw_products, list):
                raise FoodLookupError("The food database returned an unexpected result. Try again later.")
            products = []
            seen = set()
            for item in raw_products:
                product = normalize_product(item)
                if product and product["barcode"] not in seen:
                    products.append(product)
                    seen.add(product["barcode"])
                if len(products) >= 15:
                    break
            _cache[cache_key] = (time.monotonic() + CACHE_SECONDS, copy.deepcopy(products))
            _cache.move_to_end(cache_key)
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
    return {"query": query, "suggested_servings": servings, "products": products}