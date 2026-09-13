# tools.py -- tool implementations + the schemas the LLM sees

# Fake database. Real system mein ye SQL query ya REST call hoti.
ORDERS = {
    "4471": {"item": "Laptop stand", "status": "shipped",
             "expected_delivery": "2026-09-12", "total_inr": 1299},
    "5502": {"item": "USB-C cable", "status": "delivered",
             "expected_delivery": "2026-09-05", "total_inr": 249},
    "6610": {"item": "Wireless mouse", "status": "processing",
             "expected_delivery": "2026-09-15", "total_inr": 899},
}

ADDRESS = {
    "123": "123 Main St, Anytown, USA",
    "456": "456 Elm St, Anytown, USA",
    "789": "789 Oak St, Anytown, USA",
}


def get_order_status(order_id: str) -> dict:
    """Look up one order. Plain Python -- no AI anywhere in here."""
    order = ORDERS.get(str(order_id).strip())

    if order is None:
        return {
            "found": False,
            "order_id": order_id,
            "message": "No order exists with this id.",
        }

    return {"found": True, "order_id": order_id, **order}


def get_address(address_id: str) -> dict:
    """Look up one address. Plain Python -- no AI anywhere in here."""
    address = ADDRESS.get(str(address).strip())

    if address is None:
        return {
            "found": False,
            "address": address,
            "message": "No address exists with this id.",
        }

    return {"found": True, "address": address}


# ---- What the LLM is allowed to know about our tools ----
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Look up the current status, item and expected delivery date "
                "of a customer's order. Use this whenever the customer asks "
                "about a specific order AND provides an order id."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order id, for example 4471",
                    },
                },
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_address",
            "description": (
                "Look up one address. Plain Python -- no AI anywhere in here."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "address_id": {
                        "type": "string",
                        "description": "The address id, for example 123",
                    },
                },
                "required": ["address_id"],
            },
        },
    },
]

# name -> function.  Ye aapka router hai.
TOOL_REGISTRY = {
    "get_order_status": get_order_status,
    "get_address": get_address,
}