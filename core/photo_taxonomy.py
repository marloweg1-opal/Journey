"""Photo slideshow taxonomy for Journey."""

from __future__ import annotations


PHOTO_TAXONOMY = {
    "family_friends": {
        "label": "Family + Friends",
        "children": ["family", "friends", "chosen_family", "groups", "pets", "events"],
    },
    "dance": {
        "label": "Dance",
        "children": ["dance", "dance_team", "recitals", "teachers", "students", "me", "costumes", "rehearsals"],
    },
    "selfies": {
        "label": "Selfies",
        "children": ["selfies", "mirror", "outfits", "progress", "portraits"],
    },
    "vacation": {
        "label": "Vacation",
        "children": ["trips", "places", "hotels", "food", "landmarks", "travel_days"],
    },
    "carebloom": {
        "label": "CareBloom",
        "children": ["carestones", "wallpapers", "interfaces", "asset_sheets", "works_in_progress"],
    },
    "screenshots": {
        "label": "Screenshots",
        "children": ["desktop", "apps", "proofs", "bugs", "references", "receipts"],
    },
    "favorites": {
        "label": "Favorites",
        "children": ["best", "profile", "print", "share", "archive"],
    },
    "needs_review": {
        "label": "Needs Review",
        "children": ["duplicates", "blurry", "unknown_people", "unknown_event", "wrong_date", "private"],
    },
}


def taxonomy_summary() -> dict:
    return {
        "status": "ready",
        "mode": "slideshow_taxonomy",
        "category_count": len(PHOTO_TAXONOMY),
        "categories": [
            {"id": key, "label": value["label"], "children": value["children"]}
            for key, value in PHOTO_TAXONOMY.items()
        ],
        "next_step": "Bind categories to real photo roots and saved queries.",
    }
