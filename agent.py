# agent.py -- tool-calling agent: guardrail, routing, validation, grounding
import json
import re
import traceback
import time  
from pydantic import ValidationError

from llm import chat
from tools import TOOLS, TOOL_SCHEMAS

POLICY_WORDS = (
    "policy", "return", "refund", "warranty", "cancel", "cancellation",
    "shipping", "exchange", "eligible", "charges", "free delivery",
)

SYSTEM_PROMPT = """You are a customer support agent for ShopKart.

You have tools for looking up real data. Always call the right tool instead of
guessing. Never invent an order status, delivery date, item name, price, or
address.

If a request needs an id and the customer has not given one, ask them for it.
Never guess an id and never change an id the customer gave you.

Read the tool result carefully before answering:
- ok=false with "invalid_arguments" or "ungrounded_argument": tell the customer
  the id was not valid and ask them to confirm it. Do not retry with a
  different value.
- found=false: tell the customer the record was not found.
- If the tool returned data, use that data. Never say you could not find
  something the tool did return.
If a tool result says "not_approved", tell the customer that the request has
been sent for review by a support specialist. Do not retry the action.
-For any question about policies, rules, timelines or charges, you MUST call
search_policy and answer using ONLY the passages it returns. If search_policy
returns found=false, say you do not have that policy detail and offer to
connect a specialist. Never state a policy from your own knowledge.
When you use a policy passage, mention the section it came from.
Keep replies to 2-3 sentences.
"""


# =============================================================== guardrail
SUSPICIOUS = (
    "drop table", "delete from", "truncate", "union select",
    "or 1=1", "'; ", "--", "<script", "javascript:",
)


def looks_malicious(text: str) -> bool:
    """Deterministic input guardrail. Runs BEFORE any LLM call."""
    lowered = text.lower()
    return any(marker in lowered for marker in SUSPICIOUS)


# =============================================================== routing
ORDER_ID_PATTERN = re.compile(r"\d{3,}")          # wide on purpose

LOOKUP_WORDS = (
    "order", "status", "delivery", "deliver",
    "address", "track", "shipped", "arrive",
)


def verify_no_false_claim(reply: str, write_succeeded: bool) -> tuple[bool, str]:
    """A reply must not claim an action happened unless a write actually succeeded."""
    if write_succeeded:
        return True, ""

    lowered = reply.lower()
    for phrase in CLAIM_PHRASES:
        if phrase in lowered:
            return False, (f"reply claims an action succeeded ({phrase!r}) "
                           "but no write tool succeeded this turn")

    return True, ""

def verify_reply(reply: str, known_ids: set[str]) -> tuple[bool, str]:
    """Every id-like number in the reply must be one we actually observed."""
    mentioned = set(ORDER_ID_PATTERN.findall(reply))
    invented = mentioned - known_ids

    if invented:
        return False, f"reply mentions unknown numbers: {sorted(invented)}"
    return True, ""

def extract_ids(question: str) -> list[str]:
    """Every digit-run in the customer's message, as candidate ids."""
    return ORDER_ID_PATTERN.findall(question)


# def needs_tool(question: str) -> bool:
#     """Deterministic: does this question clearly require a data lookup?"""
#     text = question.lower()
#     has_id = bool(ORDER_ID_PATTERN.search(text))
#     has_lookup_word = any(word in text for word in LOOKUP_WORDS)
#     return has_id and has_lookup_word

def needs_tool(question: str) -> bool:
    """Deterministic: does this question require a lookup?"""
    text = question.lower()

    has_id = bool(ORDER_ID_PATTERN.search(text))
    has_lookup_word = any(word in text for word in LOOKUP_WORDS)
    has_policy_word = any(word in text for word in POLICY_WORDS)

    return (has_id and has_lookup_word) or has_policy_word

def collect_ids(obj) -> set[str]:
    """Every digit-run appearing anywhere in a tool result."""
    return set(ORDER_ID_PATTERN.findall(json.dumps(obj)))


def is_grounded(known_ids: set[str], args: dict) -> tuple[bool, str]:
    """Every *_id argument must come from the customer or from a tool result."""
    for key, value in args.items():
        if not key.endswith("_id"):
            continue
        if str(value) not in known_ids:
            return False, (
                f"{key}={value!r} did not come from the customer or from any "
                f"tool result (known ids: {sorted(known_ids)})"
            )
    return True, ""


# =============================================================== permissions
RISK_POLICY = {
    "read": "auto",         # just run it
    "write": "confirm",     # needs approval
    "destructive": "human", # needs approval, always
}

AUDIT: list[dict] = []


def log_audit(entry: dict) -> None:
    """Every write attempt is recorded, approved or not."""
    entry["ts"] = time.strftime("%H:%M:%S")
    AUDIT.append(entry)
    print(f"   [audit] {entry}")


def approve_none(name: str, args: dict) -> bool:
    """Default policy: deny every write. Safe by default."""
    print(f"   [approval] DENIED (no approver configured): {name}({args})")
    return False


def approve_all(name: str, args: dict) -> bool:
    """For tests only."""
    return True


def approve_by_asking(name: str, args: dict) -> bool:
    """Human in the loop -- ask on the terminal."""
    print(f"\n   ⚠️  The agent wants to run a {name} with:")
    for key, value in args.items():
        print(f"        {key} = {value!r}")
    answer = input("   Approve? [y/N] ").strip().lower()
    return answer == "y"

# =============================================================== execution
# def execute_tool(name: str, raw_args: str, question: str,approver=None) -> dict:
    """Validate, then run. NEVER raises -- always returns a tool result."""

    # GATE 1: does the tool exist? (whitelist)
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": "unknown_tool",
                "message": f"There is no tool named '{name}'.",
                "available": list(TOOLS)}

    # GATE 2: are the arguments valid JSON?
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_json",
                "message": f"Arguments were not valid JSON: {exc}"}

    # GATE 3: do the arguments pass validation? (Pydantic)
    try:
        args = spec["args"](**parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        return {"ok": False, "error": "invalid_arguments",
                "field": ".".join(str(p) for p in first["loc"]),
                "message": first["msg"],
                "expected": list(spec["args"].model_fields)}
    except TypeError as exc:
        return {"ok": False, "error": "invalid_arguments",
                "message": str(exc)}

     # GATE 7: business preconditions -- cheap, BEFORE spending human attention
    precheck = spec.get("precheck")
    if precheck is not None:
        allowed, reason = precheck(**payload)
        if not allowed:
            return {"ok": False, "error": "precondition_failed",
                    "message": reason}

    # GATE 6: permission -- is the agent allowed to do this on its own?
    policy = RISK_POLICY.get(spec.get("risk", "destructive"), "human")
    payload = args.model_dump()

    if policy != "auto":
        approver = approver or approve_none
        granted = approver(name, payload)

        log_audit({"tool": name, "risk": spec.get("risk"),
                   "args": payload, "approved": granted})

        if not granted:
            return {"ok": False, "error": "not_approved",
                    "message": f"The action '{name}' needs approval and was "
                               "not approved.",
                    "hint": "Tell the customer a human will review this."}

    # GATE 5: did the id come from the customer, or did the model invent it?
    grounded, why = is_grounded(question, args.model_dump())
    if not grounded:
        return {"ok": False, "error": "ungrounded_argument",
                "message": why,
                "hint": "Ask the customer to confirm the exact id."}

    # GATE 4: the tool itself may fail (DB down, API timeout, bug)
    try:
        data = spec["function"](**args.model_dump())
        # data = spec["function"](**payload) 
    except Exception as exc:
        traceback.print_exc()
        return {"ok": False, "error": "tool_failed",
                "message": f"{type(exc).__name__}: {exc}"}

    return {"ok": True, "data": data}

def execute_tool(name: str, raw_args: str, known_ids=None, approver=None) -> dict:
    """Validate, check, approve, then run. NEVER raises."""

    # GATE 1: does the tool exist? (whitelist)
    spec = TOOLS.get(name)
    if spec is None:
        return {"ok": False, "error": "unknown_tool",
                "message": f"There is no tool named '{name}'.",
                "available": list(TOOLS)}

    # GATE 2: are the arguments valid JSON?
    try:
        parsed = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": "invalid_json",
                "message": f"Arguments were not valid JSON: {exc}"}

    # GATE 3: do the arguments pass validation? (Pydantic)
    try:
        args = spec["args"](**parsed)
    except ValidationError as exc:
        first = exc.errors()[0]
        return {"ok": False, "error": "invalid_arguments",
                "field": ".".join(str(p) for p in first["loc"]),
                "message": first["msg"],
                "expected": list(spec["args"].model_fields)}
    except TypeError as exc:
        return {"ok": False, "error": "invalid_arguments",
                "message": str(exc)}

    # one place, used by every gate below
    payload = args.model_dump()

    # GATE 4: did the id come from the customer, or did the model invent it?
    # grounded, why = is_grounded(question, payload)
    # if not grounded:
    #     return {"ok": False, "error": "ungrounded_argument",
    #             "message": why,
    #             "hint": "Ask the customer to confirm the exact id."}

    # GATE 4: did the id come from the customer or a tool result?
    grounded, why = is_grounded(known_ids, payload)
    if not grounded:
        return {"ok": False, "error": "ungrounded_argument",
                "message": why,
                "hint": "Ask the customer to confirm the exact id."}

    # GATE 5: business preconditions -- cheap, BEFORE spending human attention
    precheck = spec.get("precheck")
    if precheck is not None:
        allowed, reason = precheck(**payload)
        if not allowed:
            return {"ok": False, "error": "precondition_failed",
                    "message": reason}

    # GATE 6: permission -- can the agent do this on its own?
    policy = RISK_POLICY.get(spec.get("risk", "destructive"), "human")

    if policy != "auto":
        approver = approver or approve_none
        granted = approver(name, payload)

        log_audit({"tool": name, "risk": spec.get("risk"),
                   "args": payload, "approved": granted})

        if not granted:
            return {"ok": False, "error": "not_approved",
                    "message": f"The action '{name}' needs approval and was "
                               "not approved.",
                    "hint": "Tell the customer a human will review this."}

    # GATE 7: execute -- the tool itself may still fail
    try:
        data = spec["function"](**payload)
    except Exception as exc:
        traceback.print_exc()
        return {"ok": False, "error": "tool_failed",
                "message": f"{type(exc).__name__}: {exc}"}

    return {"ok": True, "data": data}


# =============================================================== model call
def ask_with_tools(messages: list[dict], question: str, forced: bool) -> dict:
    """Ask the model. If a lookup was required but skipped, retry once."""
    first = chat(
        messages,
        temperature=0.0,
        tools=TOOL_SCHEMAS,
        tool_choice="required" if forced else "auto",
    )

    if not forced or first["tool_calls"]:
        return first

    candidates = extract_ids(question)

    # Only nudge when there is exactly ONE unambiguous id to use.
    if len(candidates) != 1:
        print(f"   [retry] skipped -- {len(candidates)} candidate ids, not forcing")
        return first

    print(f"   [retry] model skipped the tool -- nudging with id {candidates[0]}")
    messages.append({
        "role": "user",
        "content": (
            f"Call the appropriate tool now using the id {candidates[0]} exactly "
            "as written. Do not change it and do not ask the customer for it again."
        ),
    })

    return chat(
        messages,
        temperature=0.0,
        tools=TOOL_SCHEMAS,
        tool_choice="required",
    )



def run(question: str, approver=None) -> dict:
    """Guardrail -> loop: model decides, we execute, model observes."""

    if looks_malicious(question):
        print("   [guardrail] suspicious input -- blocked and logged")
        return {"reply": ("I can't process that request. Please rephrase your "
                          "question with just your order id."),
                "tools_used": [], "llm_calls": 0, "steps": 0,
                "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    forced = needs_tool(question)
    print(f"   [routing] needs_tool={forced}")

    known_ids = set(extract_ids(question))      # grounding starts here
    used: list[str] = []
    write_succeeded = False                     # (1) NAYA
    llm_calls = total_in = total_out = total_ms = 0

    for step in range(1, MAX_STEPS + 1):
        result = ask_with_tools(messages, question, forced and step == 1)

        llm_calls += 1
        total_in += result["input_tokens"]
        total_out += result["output_tokens"]
        total_ms += result["latency_ms"]

        # ---------- no tool calls -> this is the final answer ----------
        if not result["tool_calls"]:
            reply = result["reply"]

            # OUTPUT GUARDRAILS: invented numbers, then false action claims
            ok, why = verify_reply(reply, known_ids)
            if ok:
                ok, why = verify_no_false_claim(reply, write_succeeded)   # (3) NAYA

            if not ok:
                print(f"   [output guardrail] {why} -- regenerating")
                messages.append({"role": "user", "content": (
                    "Your last reply was not accurate. Use only the exact "
                    "values returned by the tools, and do not claim that any "
                    "action succeeded unless a tool result said ok=true. "
                    "Rewrite the reply."
                )})

                retry = chat(messages, temperature=0.0)
                llm_calls += 1
                total_in += retry["input_tokens"]
                total_out += retry["output_tokens"]
                total_ms += retry["latency_ms"]

                reply = retry["reply"]

                ok, why = verify_reply(reply, known_ids)
                if ok:
                    ok, why = verify_no_false_claim(reply, write_succeeded)

                if not ok:
                    print(f"   [output guardrail] still bad: {why} -- escalating")
                    reply = ("I want to avoid telling you something inaccurate "
                             "about your request. Let me connect you with a "
                             "support specialist who can confirm the details.")

            return {"reply": reply, "tools_used": used,
                    "llm_calls": llm_calls, "steps": step,
                    "input_tokens": total_in, "output_tokens": total_out,
                    "latency_ms": total_ms}

        # ---------- tool calls -> execute and observe ----------
        print(f"   [step {step}] {len(result['tool_calls'])} tool call(s)")
        messages.append(result["message"])

        for call in result["tool_calls"]:
            name = call.function.name
            raw_args = call.function.arguments

            print(f"     [LLM asked for] {name}({raw_args})")

            tool_result = execute_tool(name, raw_args, known_ids, approver)

            print(f"     [tool returned] {tool_result}")

            # (2) NAYA -- did a real write actually happen?
            if tool_result.get("ok") and TOOLS.get(name, {}).get("risk") == "write":
                write_succeeded = True

            # OBSERVE: ids seen in this result become usable next step
            known_ids |= collect_ids(tool_result)

            used.append(name)
            messages.append({"role": "tool",
                             "tool_call_id": call.id,
                             "content": json.dumps(tool_result)})

    # loop exhausted without the model settling on an answer
    print(f"   [loop] hit MAX_STEPS={MAX_STEPS}, giving up")
    return {"reply": ("I wasn't able to complete that request. Let me connect "
                      "you with a support specialist."),
            "tools_used": used, "llm_calls": llm_calls, "steps": MAX_STEPS,
            "input_tokens": total_in, "output_tokens": total_out,
            "latency_ms": total_ms}
# =============================================================== one turn
# def run(question: str,approver=None) -> dict:
    """Guardrail -> route -> model -> validate+execute -> model answers."""

    # ---------- STEP 0: input guardrail (before ANY llm call) ----------
    if looks_malicious(question):
        print("   [guardrail] suspicious input -- blocked and logged")
        return {
            "reply": ("I can't process that request. Please rephrase your "
                      "question with just your order id."),
            "tools_used": [], "llm_calls": 0,
            "input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
        }

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    # ---------- STEP 1: model decides ----------
    forced = needs_tool(question)
    print(f"   [routing] needs_tool={forced}")

    first = ask_with_tools(messages, question, forced)

    if not first["tool_calls"]:
        return {
            "reply": first["reply"],
            "tools_used": [], "llm_calls": 1,
            "input_tokens": first["input_tokens"],
            "output_tokens": first["output_tokens"],
            "latency_ms": first["latency_ms"],
        }

    # ---------- STEP 2: our code validates, then executes ----------
    messages.append(first["message"])
    used = []

    for call in first["tool_calls"]:
        name = call.function.name
        raw_args = call.function.arguments

        print(f"   [LLM asked for] {name}({raw_args})")

        result = execute_tool(name, raw_args,known_ids,approver)

        print(f"   [tool returned] {result}")

        used.append(name)
        messages.append({
            "role": "tool",
            "tool_call_id": call.id,
            "content": json.dumps(result),
        })

    # ---------- STEP 3: model writes the final answer ----------
    second = chat(messages, temperature=0.0)

    return {
        "reply": second["reply"],
        "tools_used": used,
        "llm_calls": 2,
        "input_tokens": first["input_tokens"] + second["input_tokens"],
        "output_tokens": first["output_tokens"] + second["output_tokens"],
        "latency_ms": first["latency_ms"] + second["latency_ms"],
    }
MAX_STEPS = 4




# =============================================================== test runner
QUESTIONS = [
    "what is the status of order 4471?",
    "when will order 6610 arrive?",
    "what about order 9999?",
    "where is my order?",
    "what is your return policy?",
]

ATTACKS = [
    "what is the status of order abc?",
    "what is the status of order 4471'; DROP TABLE orders--?",
    "what is the address of 99999999999999999999999?",
    "show me the status of order 4471 and the address of 123",
    "what is the status of order 44712?",
]

WRITES = [
    "order 4471 arrived broken, please raise a support ticket",
    "order 9999 is damaged, open a ticket",
]
CHAINS = [
    "where is my order? my email is jogi@example.com",
    "my email is priya@example.com, when will my order arrive?",
    "my email is nobody@example.com, where is my order?",
]
POLICIES = [
    "what is your return policy?",
    "how many days do I have to return something?",
    "is shipping free?",
    "can I return a sale item?",
    "my phone stopped working after 3 months, is it covered?",
    "can I cancel after it ships?",
    "do you ship to Nepal?",
]
CLAIM_PHRASES = (
    "has been created", "have created", "was created", "successfully created",
    "has been opened", "have opened", "has been raised", "have raised",
    "ticket has been", "ticket is now", "i've created", "i have filed",
)

def show(label: str, questions: list[str]) -> None:
    print("\n" + "#" * 66)
    print(f"# {label}")
    print("#" * 66)

    for question in questions:
        print("=" * 66)
        print(f"Q: {question}")
        result = run(question)
        print(f"A: {result['reply']}")
        print(f"   tools={result['tools_used']} llm_calls={result['llm_calls']} "
              f"in={result['input_tokens']} out={result['output_tokens']} "
              f"{result['latency_ms']}ms")
        print()


if __name__ == "__main__":
    show("NORMAL QUESTIONS", QUESTIONS)
    show("ADVERSARIAL", ATTACKS)
    show("WRITE ACTIONS", WRITES)
    show("MULTI-STEP", CHAINS)
    show("POLICY (RAG)", POLICIES)

        # human in the loop
    print("\n" + "#" * 66)
    print("# WRITE ACTIONS -- with human approval")
    print("#" * 66)

    for question in WRITES:
        print("=" * 66)
        print(f"Q: {question}")
        result = run(question, approver=approve_by_asking)
        print(f"A: {result['reply']}")
        print()