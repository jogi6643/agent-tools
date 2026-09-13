# tools.py -- tools + Pydantic argument models (single source of truth)
from pydantic import BaseModel,ConfigDict, Field
from store_chroma import search as _vector_search
# ---------- write-side storage ----------
TICKETS: dict[str, dict] = {}
POLICY_MIN_SCORE = 0.45

PUBLIC_ORDER_FIELDS = ("item", "status", "expected_delivery", "total_inr")

class CreateSupportTicketArgs(BaseModel):
    """Arguments accepted by create_support_ticket."""
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(
        ...,
        description="The order id this ticket is about, for example 4471",
        max_length=12,
        pattern=r"^\d+$",
    )
    issue: str = Field(
        ...,
        description="Short description of the customer's problem",
        min_length=10,
        max_length=300,
    )


def create_support_ticket(order_id: str, issue: str) -> dict:
    """Create a ticket. IDEMPOTENT: same order + same issue reuses the ticket."""
    if order_id not in ORDERS:
        return {"created": False, "reason": "unknown_order",
                "order_id": order_id,
                "message": "Cannot open a ticket for an order that does not exist."}

    key = f"{order_id}:{issue.strip().lower()}"

    for ticket in TICKETS.values():
        if ticket["key"] == key:
            return {"created": False, "reason": "duplicate",
                    "ticket_id": ticket["ticket_id"],
                    "message": "A ticket for this issue already exists."}

    ticket_id = f"TKT-{1001 + len(TICKETS)}"
    TICKETS[ticket_id] = {
        "ticket_id": ticket_id, "key": key,
        "order_id": order_id, "issue": issue, "status": "open",
    }

    return {"created": True, "ticket_id": ticket_id,
            "order_id": order_id, "status": "open"}


class FindOrdersByEmailArgs(BaseModel):
    """Arguments accepted by find_orders_by_email."""
    model_config = ConfigDict(extra="forbid")

    email: str = Field(
        ...,
        description="The customer's email address",
        max_length=120,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )


def find_orders_by_email(email: str) -> dict:
    """List the order ids belonging to a customer."""
    matches = [
        {"order_id": order_id, "item": order["item"]}
        for order_id, order in ORDERS.items()
        if order.get("customer_email", "").lower() == email.strip().lower()
    ]

    if not matches:
        return {"found": False, "email": email,
                "message": "No orders found for this email address."}

    return {"found": True, "email": email,
            "count": len(matches), "orders": matches}
# ---------- fake database ----------
# ORDERS = {
#     "4471": {"item": "Laptop stand", "status": "shipped",
#              "expected_delivery": "2026-09-12", "total_inr": 1299},
#     "5502": {"item": "USB-C cable", "status": "delivered",
#              "expected_delivery": "2026-09-05", "total_inr": 249},
#     "6610": {"item": "Wireless mouse", "status": "processing",
#              "expected_delivery": "2026-09-15", "total_inr": 899},
# }

ORDERS = {
    "4471": {"item": "Laptop stand", "status": "shipped",
             "expected_delivery": "2026-09-12", "total_inr": 1299,
             "customer_email": "jogi@example.com"},
    "5502": {"item": "USB-C cable", "status": "delivered",
             "expected_delivery": "2026-09-05", "total_inr": 249,
             "customer_email": "jogi@example.com"},
    "6610": {"item": "Wireless mouse", "status": "processing",
             "expected_delivery": "2026-09-15", "total_inr": 899,
             "customer_email": "priya@example.com"},
}

ADDRESSES = {
    "123": "12 MG Road, Bengaluru 560001",
    "456": "7 Nehru Place, New Delhi 110019",
    "789": "301 Marine Drive, Mumbai 400020",
}


# ---------- argument models ----------
class GetOrderStatusArgs(BaseModel):
    """Arguments accepted by get_order_status."""
    order_id: str = Field(
        ...,
        description="The order id, digits only, for example 4471",
        min_length=1,
        max_length=12,
        pattern=r"^\d+$",
    )


class GetAddressArgs(BaseModel):
    """Arguments accepted by get_address."""
    address_id: str = Field(
        ...,
        description="The address id, digits only, for example 123",
        min_length=1,
        max_length=12,
        pattern=r"^\d+$",
    )


# ---------- implementations ----------
# def get_order_status(order_id: str) -> dict:
#     order = ORDERS.get(order_id)

#     if order is None:
#         return {"found": False, "order_id": order_id,
#                 "message": "No order exists with this id."}

#     return {"found": True, "order_id": order_id, **order}

def get_order_status(order_id: str) -> dict:
    """Look up one order. Returns only customer-safe fields."""
    order = ORDERS.get(order_id)

    if order is None:
        return {"found": False, "order_id": order_id,
                "message": "No order exists with this id."}

    return {
        "found": True,
        "order_id": order_id,
        **{key: order[key] for key in PUBLIC_ORDER_FIELDS},
    }


def get_address(address_id: str) -> dict:
    address = ADDRESSES.get(address_id)

    if address is None:
        return {"found": False, "address_id": address_id,
                "message": "No address exists with this id."}

    return {"found": True, "address_id": address_id, "address": address}

def can_create_support_ticket(order_id: str, issue: str) -> tuple[bool, str]:
    """Business precondition check. Read-only, no side effects."""
    if order_id not in ORDERS:
        return False, f"Order {order_id} does not exist, so no ticket can be opened."
    return True, ""




class SearchPolicyArgs(BaseModel):
    """Arguments accepted by search_policy."""
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ...,
        description="The customer's policy question, in English",
        min_length=3,
        max_length=200,
    )


def search_policy(query: str) -> dict:
    """Search ShopKart's policy documents. Returns exact policy text."""
    hits = _vector_search(query, k=3)

    if not hits or hits[0]["score"] < POLICY_MIN_SCORE:
        return {"found": False, "query": query,
                "message": "No matching policy text was found in the documents."}

    return {
        "found": True,
        "query": query,
        "passages": [
            {"section": hit["section"],
             "text": hit["text"],
             "score": round(hit["score"], 3)}
            for hit in hits
        ],
    }



# ---------- registry: one entry per tool ----------
TOOLS = {
    "get_order_status": {
        "function": get_order_status,
        "args": GetOrderStatusArgs,
        "risk": "read",
        "description": (
            "Look up the current status, item, expected delivery date and "
            "total amount of a customer's order. Use this whenever the "
            "customer asks about a specific order and provides an order id. "
            "Returns found=false if no such order exists."
        ),
    },
    "get_address": {
        "function": get_address,
        "args": GetAddressArgs,
        "risk": "read",
        "description": (
            "Look up the full delivery address saved for an address id. Use "
            "this when the customer asks which address something will be "
            "delivered to, or asks to confirm a saved address, and provides "
            "an address id. Returns found=false if no such address exists."
        ),
    },
    "create_support_ticket": {
        "function": create_support_ticket,
        "args": CreateSupportTicketArgs,
        "precheck": can_create_support_ticket, 
        "risk": "write",
        "description": (
            "Open a support ticket for an order when the customer reports a "
            "problem that you cannot solve yourself, such as a damaged item, "
            "a missing delivery, or a wrong product. Requires the order id "
            "and a short description of the problem."
        ),
    },
        "find_orders_by_email": {
        "function": find_orders_by_email,
        "args": FindOrdersByEmailArgs,
        "risk": "read",
        "description": (
            "Find all order ids belonging to a customer, given their email "
            "address. Use this FIRST when the customer asks about their order "
            "but gives an email address instead of an order id. Then use "
            "get_order_status with the order id you get back."
        ),
    },
    "search_policy": {
        "function": search_policy,
        "args": SearchPolicyArgs,
        "risk": "read",
        "description": (
            "Search ShopKart's official policy documents -- returns, refunds, "
            "shipping charges, order cancellation and warranty -- and get back "
            "the exact policy text. Use this for ANY question about rules, "
            "timelines, charges or eligibility. NEVER answer a policy question "
            "from your own knowledge; always call this tool first."
        ),
    },
}


def _schema(name: str, spec: dict) -> dict:
    """Build the OpenAI tool schema from the Pydantic model."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": spec["description"],
            "parameters": spec["args"].model_json_schema(),
        },
    }


# Schemas are GENERATED, never hand-written -- they cannot drift.
TOOL_SCHEMAS = [_schema(name, spec) for name, spec in TOOLS.items()]


if __name__ == "__main__":
    import json
    print(json.dumps(TOOL_SCHEMAS, indent=2))