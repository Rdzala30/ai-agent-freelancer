"""Business-type -> OpenStreetMap tag mapping.

The user-facing category names ("cafe", "salon", "dentist") map to OSM
key=value tags. Every alias yields the same lead.category stored in the DB
(the canonical category passed in by the user).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# canonical category -> list of (osm_key, osm_value)
CATEGORY_MAP: Dict[str, List[Tuple[str, str]]] = {
    "cafe": [("amenity", "cafe"), ("shop", "coffee")],
    "coffee": [("amenity", "cafe"), ("shop", "coffee")],
    "restaurant": [("amenity", "restaurant"), ("amenity", "fast_food"), ("amenity", "food_court")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "beauty": [("shop", "beauty"), ("shop", "hairdresser")],
    "barber": [("shop", "hairdresser"), ("shop", "barber")],
    "gym": [("leisure", "fitness_centre"), ("sport", "gym"), ("leisure", "sports_centre")],
    "fitness": [("leisure", "fitness_centre"), ("sport", "gym")],
    "dentist": [("amenity", "dentist")],
    "doctor": [("amenity", "doctors"), ("amenity", "clinic")],
    "clinic": [("amenity", "clinic"), ("amenity", "doctors")],
    "pharmacy": [("amenity", "pharmacy")],
    "bakery": [("shop", "bakery")],
    "sweets": [("shop", "confectionery")],
    "mithai": [("shop", "confectionery")],
    "electronics": [("shop", "electronics"), ("shop", "mobile_phone")],
    "mobile": [("shop", "mobile_phone"), ("shop", "electronics")],
    "furniture": [("shop", "furniture")],
    "jewellery": [("shop", "jewellery")],
    "jewelry": [("shop", "jewellery")],
    "tailor": [("shop", "tailor")],
    "hotel": [("tourism", "hotel"), ("tourism", "guest_house")],
    "guesthouse": [("tourism", "guest_house")],
    "garage": [("shop", "car_repair"), ("shop", "car_parts")],
    "car_repair": [("shop", "car_repair")],
    "real_estate": [("office", "estate_agent"), ("shop", "estate_agent")],
    "travel": [("shop", "travel_agency")],
    "florist": [("shop", "florist")],
    "bookstore": [("shop", "books")],
    "stationery": [("shop", "stationery")],
    "grocery": [("shop", "supermarket"), ("shop", "convenience")],
    "supermarket": [("shop", "supermarket")],
    "pet": [("shop", "pet"), ("shop", "pet_grooming")],
    "laundry": [("shop", "laundry"), ("shop", "dry_cleaning")],
    "optometrist": [("shop", "optician")],
    "plumber": [("craft", "plumber")],
    "electrician": [("craft", "electrician")],
    "carpenter": [("craft", "carpenter")],
}


def resolve(category: str) -> List[Tuple[str, str]]:
    """Map a user category to OSM tags. Falls back to direct tag guess."""
    key = category.strip().lower()
    if key in CATEGORY_MAP:
        return CATEGORY_MAP[key]
    # Best-effort: treat the category as an amenity or shop value directly.
    return [("amenity", key), ("shop", key)]


def known_category(category: str) -> bool:
    return category.strip().lower() in CATEGORY_MAP
