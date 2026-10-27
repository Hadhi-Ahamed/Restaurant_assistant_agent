# MENU = {
#     "P001": {"name": "Chicken Burger", "price": 850,  "available": True,  "aliases": ["burger"]},
#     "P002": {"name": "Fried Rice",     "price": 1200, "available": True,  "aliases": ["rice"]},
#     "P003": {"name": "Coke",           "price": 250,  "available": True,  "aliases": ["cola"]},
#     "P004": {"name": "Pizza",          "price": 2000, "available": False, "aliases": []},
# }


# def menu_to_prompt() -> str:
#     """IDs, names and aliases only. No prices, so the LLM never sees them."""
#     return "\n".join(f"{k}: {v['name']} (also: {', '.join(v['aliases']) or '-'})" for k, v in MENU.items())

MENU = {
    "P001": {"name": "Chicken Burger", "price": 850, "available": True},
    "P002": {"name": "Fried Rice", "price": 1200, "available": True},
    "P003": {"name": "Coke", "price": 250, "available": True},
    "P004": {"name": "Pizza", "price": 2000, "available": False},
}


def menu_to_prompt() -> str:
    """IDs and names only. No prices, so the LLM never sees them."""
    return "\n".join(f"{k}: {v['name']}" for k, v in MENU.items())