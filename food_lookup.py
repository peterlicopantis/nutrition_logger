"""Find plain foods offline and packaged-food labels without an API key.

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
import unicodedata
from collections import OrderedDict, deque
from pathlib import Path
from http.client import HTTPException, IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "MELBNutrition/1.0 (local personal food diary)"
REQUEST_TIMEOUT = 8
REQUEST_BUDGET = 20
RETRY_DELAY = 0.35
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
_inflight: dict[str, _PendingLookup] = {}

# A small verified subset of USDA SR Legacy, not a network dependency.
with Path(__file__).with_name("generic_foods.json").open(encoding="utf-8") as catalog_file:
    _generic_catalog = json.load(catalog_file)["foods"]


class FoodLookupError(Exception):
    """A food lookup could not be completed; the message is safe to display."""


class _PendingLookup:
    def __init__(self):
        self.done = threading.Event()
        self.products: list[dict] | None = None
        self.error: str | None = None


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
    # Keep the unrounded density separate from the displayed portion macros.
    per_100g = copy.deepcopy(macros) if basis == "100g" else (
        {key: value * 100 / serving_g if value is not None else None
         for key, value in macros.items()} if serving_g else None
    )
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
        "nutrition_per_100g": per_100g, "requires_weight": basis == "100g",
        "portion_estimated": False, "portion_countable": False,
        "portions": ([{"id": "label", "label": serving_label[:120],
                       "grams": serving_g, "countable": False}]
                     if serving_g else []),
        "default_portion_id": "label" if serving_g else None,
        **{key: round(value, 4) if value is not None else None for key, value in macros.items()},
        "source_url": f"https://world.openfoodfacts.org/product/{barcode}",
        "source_name": "Open Food Facts", "kind": "packaged",
    }


def _generic_foods(query: str) -> list[dict]:
    """Plain aliases and explicit sizes retain the food's preparation."""
    key = query.casefold()
    requested_size = None
    size_match = re.match(r"^(extra small|extra large|small|medium|large|jumbo)\s+(.+)$", key)
    if size_match:
        requested_size, key = size_match.groups()
    products = []
    for food in _generic_catalog:
        if key not in food["aliases"]:
            continue
        portions = copy.deepcopy(food["portions"])
        default = next(portion for portion in portions if portion["id"] == food["default_portion_id"])
        if requested_size:
            # Do not substitute a raw item's size for a cooked preparation.
            matching = next((portion for portion in portions if portion.get("size") == requested_size), None)
            if matching is None:
                continue
            default = matching
        grams = default["grams"]
        per_100g = {nutrient: float(food[nutrient]) for nutrient in
                    ("calories", "protein", "carbs", "fat", "fiber")}
        products.append({
            "name": food["name"], "brand": "", "barcode": "",
            "serving_label": f"{default['label']} (~{grams:g} g)",
            "serving_g": grams, "basis": "serving",
            **{key: round(value * grams / 100, 4) for key, value in per_100g.items()},
            "nutrition_per_100g": per_100g, "requires_weight": False,
            "portions": portions, "default_portion_id": default["id"],
            "portion_estimated": True, "portion_countable": default["countable"],
            "source_url": f"https://fdc.nal.usda.gov/food-details/{food['fdc_id']}/nutrients",
            "source_name": "USDA FoodData Central", "kind": "generic",
        })
    return products


def _name_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(character for character in text if not unicodedata.combining(character))
    tokens = []
    aliases = {"kelloggs": "kellogg", "krispy": "krispie"}
    for token in re.findall(r"[a-z0-9]+", text):
        if token in {"a", "an", "the", "and", "of", "with", "for", "s"}:
            continue
        token = aliases.get(token, token)
        if token.endswith("ies") and token not in {"cookies", "brownies", "pies", "krispies"}:
            token = token[:-3] + "y"
        elif len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us")):
            token = token[:-1]
        tokens.append(token)
    return tokens


def _match_score(query: str, product: dict, original: dict) -> tuple | None:
    """Use the food's title and brand; ingredients do not establish a match."""
    wanted = set(_name_tokens(query))
    title_tokens = _name_tokens(product["name"])
    title = set(title_tokens)
    combined = title | set(_name_tokens(product["brand"]))
    if not wanted or not wanted.issubset(combined):
        return None
    query_phrase = " ".join(_name_tokens(query))
    title_phrase = " ".join(title_tokens)
    return (
        -len(wanted & title) / len(wanted),
        -(query_phrase in title_phrase),
        -bool(_text(original.get("product_name_en"))),
        len(title - wanted),
    )


def _reserve_request(*, barcode: bool) -> None:
    # Network calls and waits happen outside this lock. A slow, cancelled
    # search cannot hold up a new query or an offline plain-food lookup.
    with _lock:
        now = time.monotonic()
        timestamps = _product_requests if barcode else _search_requests
        limit = 15 if barcode else 10
        while timestamps and timestamps[0] <= now - 60:
            timestamps.popleft()
        if len(timestamps) >= limit:
            seconds = max(1, math.ceil(60 - (now - timestamps[0])))
            raise FoodLookupError(f"Food lookup is busy. Try again in {seconds} seconds, or enter the label manually.")
        timestamps.append(now)


def _request_json(url: str, *, barcode: bool) -> dict:
    deadline = time.monotonic() + REQUEST_BUDGET
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if os.environ.get("MELB_FOOD_LOOKUP_STAGING", "").lower() in ("1", "true", "yes"):
        headers["Authorization"] = "Basic " + base64.b64encode(b"off:off").decode("ascii")
    last_error = None
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _reserve_request(barcode=barcode)
        transient = False
        try:
            with urlopen(Request(url, headers=headers), timeout=min(REQUEST_TIMEOUT, remaining)) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if time.monotonic() > deadline:
                raise TimeoutError("Food lookup exceeded its time budget")
            if len(raw) > MAX_RESPONSE_BYTES:
                raise FoodLookupError("The food database returned too much data. Try a more specific name.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise FoodLookupError("The food database returned an unexpected result. Try again later.")
            return data
        except HTTPError as error:
            if error.code == 404 and barcode:
                return {"products": []}
            if error.code == 429:
                raise FoodLookupError("The food database is busy. Wait a minute or enter the label manually.") from error
            transient = error.code in (502, 503, 504)
            last_error = error
            error.close()
        except (URLError, OSError, HTTPException) as error:
            last_error = error
            transient = isinstance(error, (TimeoutError, ConnectionError, IncompleteRead, RemoteDisconnected)) or (
                isinstance(error, URLError) and isinstance(error.reason, (TimeoutError, ConnectionError, IncompleteRead, RemoteDisconnected))
            )
        except (ValueError, UnicodeDecodeError) as error:
            raise FoodLookupError("The food database returned an unreadable result. Enter the label manually or try later.") from error
        if not transient or attempt == 1 or deadline - time.monotonic() <= RETRY_DELAY:
            break
        time.sleep(RETRY_DELAY)
    raise FoodLookupError("Couldn't reach the packaged-food database after trying automatically. You can still enter the label manually or search a plain food such as carrot.") from last_error


def _fetch_products(query: str, *, barcode: bool, staging: bool) -> list[dict]:
    base_url = "https://world.openfoodfacts.net" if staging else "https://world.openfoodfacts.org"
    if barcode:
        url = f"{base_url}/api/v3.6/product/{query}?" + urlencode({
            "fields": PRODUCT_FIELDS, "lc": "en", "cc": "us",
        })
    else:
        url = f"{base_url}/cgi/search.pl?" + urlencode({
            "search_terms": query, "search_simple": 1, "action": "process",
            "json": 1, "page_size": 24, "fields": PRODUCT_FIELDS,
            "lc": "en", "cc": "us",
        })
    data = _request_json(url, barcode=barcode)
    raw_products = [data["product"]] if barcode and isinstance(data.get("product"), dict) else data.get("products", [])
    if not isinstance(raw_products, list):
        raise FoodLookupError("The food database returned an unexpected result. Try again later.")
    matches = []
    seen = set()
    for index, item in enumerate(raw_products):
        product = normalize_product(item)
        if not product or product["barcode"] in seen:
            continue
        score = () if barcode else _match_score(query, product, item)
        if score is None:
            continue
        matches.append((score, index, product))
        seen.add(product["barcode"])
    matches.sort(key=lambda match: (match[0], match[1]))
    return [match[2] for match in matches[:15]]


def _packaged_result(query: str, servings: float, products: list[dict]) -> dict:
    result = {"query": query, "suggested_servings": servings, "products": products}
    if not products:
        result["message"] = "No matching product name with complete nutrition was found. Add the brand, use a barcode, or enter the label manually."
    return result


def lookup_foods(raw: str) -> dict:
    """Return plain-food reference values or matching packaged-food labels.

    A count hint from 'I had 2 ...' never changes a food's macros or turns
    100 g into one item. The user confirms preparation/package and quantity.
    """
    query, servings = normalize_query(raw)
    generic = _generic_foods(query)
    if generic:
        return {
            "query": query, "suggested_servings": servings, "products": generic,
            "message": "Choose the preparation and portion you ate. USDA portion weights are typical edible-weight estimates; you can change the size or grams.",
        }
    barcode = re.fullmatch(r"[0-9]{8,14}", query) is not None
    staging = os.environ.get("MELB_FOOD_LOOKUP_STAGING", "").lower() in ("1", "true", "yes")
    cache_key = ("staging:" if staging else "production:") + ("barcode:" if barcode else "search:") + query.casefold()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            _cache.move_to_end(cache_key)
            return _packaged_result(query, servings, copy.deepcopy(cached[1]))
        pending = _inflight.get(cache_key)
        owner = pending is None
        if owner:
            pending = _PendingLookup()
            _inflight[cache_key] = pending

    if not owner:
        # Only identical queries share a wait; different queries are independent.
        if not pending.done.wait(REQUEST_BUDGET):
            raise FoodLookupError("The food database is taking too long. Enter the label manually or try a plain food.")
        if pending.error:
            raise FoodLookupError(pending.error)
        return _packaged_result(query, servings, copy.deepcopy(pending.products or []))

    try:
        products = _fetch_products(query, barcode=barcode, staging=staging)
        with _lock:
            _cache[cache_key] = (time.monotonic() + CACHE_SECONDS, copy.deepcopy(products))
            _cache.move_to_end(cache_key)
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
            pending.products = copy.deepcopy(products)
        return _packaged_result(query, servings, products)
    except Exception as error:
        pending.error = str(error) if isinstance(error, FoodLookupError) else "The food lookup couldn't finish. Enter the label manually or try later."
        raise
    finally:
        with _lock:
            _inflight.pop(cache_key, None)
            pending.done.set()
