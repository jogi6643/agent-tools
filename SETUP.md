# ShopKart AI Agent — Complete Setup and Architecture Guide

> **Kya hai yeh project?**
> Ek production-grade customer support AI agent jo ShopKart ke customers ke orders,
> addresses, support tickets aur policies ke baare mein sawalon ka jawab deta hai.
> Sirf LLM call karna kaafi nahi — is project mein 7-gate validation pipeline,
> grounding checks, permission system aur output guardrails bhi hain.

---

## Project Structure

```
agent-tools/
├── .env                       ← LLM provider config (Ollama ya OpenAI)
├── agent.py                   ← MAIN FILE: guardrails, routing, execute_tool, run()
├── tools.py                   ← Tools definitions + Pydantic models + TOOLS registry
├── llm.py                     ← Sirf LLM se baat karna (transport layer)
├── store_chroma.py            ← ChromaDB vector store (RAG ke liye)
├── chunker.py                 ← Policy documents ko chunks mein todna
├── test_agent.py              ← Unit tests (no LLM, no network needed)
├── docs/
│   └── shopkart_policies.md  ← Policy documents (RAG ka source)
└── chroma_db/                 ← ChromaDB persistent storage (auto-generate hota hai)
```

---

## Step 1: Prerequisites Install Karo

### 1.1 Python Version

```bash
python3 --version   # 3.11 ya usse upar chahiye
```

### 1.2 Virtual Environment Banao

```bash
cd /Users/jogi/Projects/Personal/agent-tools
python3 -m venv venv
source venv/bin/activate
```

### 1.3 Dependencies Install Karo

```bash
pip install openai pydantic python-dotenv chromadb pytest
```

| Package        | Kyun chahiye                                                |
|----------------|-------------------------------------------------------------|
| `openai`       | LLM se baat karne ke liye (Ollama bhi OpenAI-compatible)   |
| `pydantic`     | Tool arguments ki validation ke liye (GATE 3)               |
| `python-dotenv`| `.env` file se config load karne ke liye                    |
| `chromadb`     | Policy documents ka vector database                         |
| `pytest`       | Unit tests run karne ke liye                                |

---

## Step 2: Ollama Setup (Local LLM — FREE)

Yeh project by default **Ollama** use karta hai — LLM locally chalega, koi API key nahi chahiye.

### 2.1 Ollama Install Karo

```bash
brew install ollama
# Ya directly: https://ollama.ai
```

### 2.2 Models Download Karo

```bash
ollama pull qwen2.5:7b           # main chat model (agent ke liye)
ollama pull nomic-embed-text     # embedding model (RAG ke liye)
```

### 2.3 Ollama Server Start Karo

```bash
ollama serve
# Background mein chalega: http://localhost:11434
```

---

## Step 3: .env Configure Karo

`.env` file already exist karti hai — current config:

```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=qwen2.5:7b

OPENAI_API_KEY=       # sirf tab fill karo jab OpenAI use karna ho
GOOGLE_API_KEY=       # abhi use nahi ho raha
```

OpenAI use karna hai to sirf yeh do lines badlo:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...your-key...
```

---

## Step 4: RAG Index Build Karo (Policy Documents)

**Pehli baar zaroor karo.** Jab bhi `docs/shopkart_policies.md` change ho tab bhi.

```bash
python store_chroma.py
```

**Yeh step-by-step kya karta hai:**

1. `docs/shopkart_policies.md` file padhta hai
2. `chunker.py` use karta hai document ko sections mein todne ke liye (section boundary cross nahi karta)
3. `nomic-embed-text` model se har chunk ka vector embedding banata hai (Ollama se)
4. `chroma_db/` folder mein save karta hai (persistent — ek baar hi karna hai)

Expected output:

```
collection: 18 chunks

Q: how do I get my money back?
--- normal search ---
  0.821  [Returns and Refunds]
  0.756  [Warranty]
  0.612  [Cancellations]
```

---

## Step 5: Unit Tests Run Karo

LLM ya network ki zaroorat **NAHI** hai tests ke liye — yeh sirf Python logic test karte hain.

```bash
pytest test_agent.py -v
```

Har test kya check karta hai:

```
INPUT GUARDRAIL
  test_guardrail_blocks_sql_injection         "DROP TABLE" wali query block hoti hai
  test_guardrail_blocks_script_tag            "<script>" wali query block hoti hai
  test_guardrail_allows_normal_question       normal query pass hoti hai

ROUTING
  test_routing_detects_lookup                 order id + lookup word = forced tool call
  test_routing_ignores_question_without_id    "return policy" = forced=False
  test_routing_detects_very_long_id           giant id bhi detect hoti hai

ID EXTRACTION
  test_extract_ids_finds_all                  "4471 and 123" → ["4471", "123"]
  test_extract_ids_empty_when_no_digits       digit nahi → []
  test_collect_ids_reads_tool_results         tool result se bhi ids milti hain

GROUNDING (GATE 4)
  test_grounding_accepts_exact_id             sahi id = ok
  test_grounding_rejects_model_corrected_id   "44712" → "4471" attempt = BLOCK
  test_grounding_rejects_invented_id          koi id nahi di = BLOCK
  test_grounding_ignores_non_id_fields        "issue" text field check nahi hoti

OUTPUT GUARDRAIL
  test_verify_reply_accepts_known_numbers     known numbers ok hain reply mein
  test_verify_reply_rejects_invented_number   unknown number in reply = BLOCK
  test_verify_reply_ignores_small_numbers     "12 MG Road" ignore hota hai (2 digits)

EXECUTE_TOOL GATES
  test_gate1_unknown_tool                     unknown tool = error
  test_gate2_invalid_json                     bad JSON = error
  test_gate3_rejects_non_digit_id             "abc" order id = error
  test_gate3_rejects_too_long_id              23-digit id = error
  test_gate4_rejects_ungrounded_id            model ka "fixed" id = BLOCK
  test_gate4_accepts_id_from_tool_result      previous tool se aaya id = OK
  test_happy_path_returns_data                sahi request = data milta hai
  test_read_tool_leaks_no_email               customer_email LLM tak nahi pahunchta

PERMISSIONS
  test_write_tool_denied_by_default           write tool auto-deny hoti hai
  test_write_tool_runs_when_approved          approve karne par chalti hai
  test_write_tool_is_idempotent               same ticket dobara nahi banta
  test_precondition_blocks_ticket_for_unknown_order  unknown order pe ticket nahi
```

---

## Step 6: Agent Run Karo

Ollama server running hona chahiye (Step 2.3 se).

```bash
python agent.py
```

Yeh automatically 5 categories ke questions run karta hai:

- **NORMAL QUESTIONS** — Regular order/delivery queries
- **ADVERSARIAL** — SQL injection, XSS, invalid ids
- **WRITE ACTIONS** — Support ticket banana (terminal approval maanga jaayega)
- **MULTI-STEP** — Email se orders dhundhna, phir status check
- **POLICY (RAG)** — Return policy, warranty, shipping jaise sawal

---

## Architecture: Ek Request Kaise Chalti Hai

```
Customer ka sawal
       |
       v
+-------------------------------+
|  STEP 0: Input Guardrail      |  looks_malicious()
|  SQL injection, XSS check     |  "DROP TABLE" ---> BLOCK (0 LLM calls)
+---------------+---------------+
                | Safe hai
                v
+-------------------------------+
|  STEP 1: Routing              |  needs_tool()
|  Kya tool call zaroor hai?    |  order id + lookup word = forced=True
|                               |  policy word = forced=True
+---------------+---------------+
                |
                v
+-------------------------------+
|  STEP 2: LLM Decision         |  ask_with_tools()
|  Model decide karta hai       |  tool_choice="required" if forced
|  kaunsa tool call karna hai   |  Agar model ne skip kiya + 1 candidate id
|                               |  = nudge with that id, retry
+---------------+---------------+
                | Tool call aaya
                v
+-----------------------------------------------------------+
|  execute_tool() — 7 Gates                                 |
|                                                           |
|  GATE 1  Tool whitelist mein hai?      → unknown_tool     |
|  GATE 2  Arguments valid JSON hain?    → invalid_json     |
|  GATE 3  Pydantic validation pass?     → invalid_args     |
|  GATE 4  Id grounded hai?              → ungrounded_arg   |
|          (customer ya previous tool result se aaya?)      |
|  GATE 5  Business precondition OK?     → precond_failed   |
|          (ticket ke liye: order exist karta hai?)         |
|  GATE 6  Permission OK?                → not_approved     |
|          read=auto  write=confirm  destructive=human      |
|  GATE 7  Tool actually execute karo    → tool_failed      |
+---------------+-------------------------------------------+
                |
                v
+-------------------------------+
|  STEP 3: Observe + Loop       |  Tool result ke ids ko known_ids mein add karo
|  MAX_STEPS = 4                |  Yahi ids agle step mein grounding ke liye valid
+---------------+---------------+
                | Jab model ne tool call nahi kiya (final answer)
                v
+-------------------------------+
|  Output Guardrails            |
|  verify_reply()               |  Invented numbers in reply = regenerate
|  verify_no_false_claim()      |  "Ticket created" without write success = BLOCK
+---------------+---------------+
                | Dono pass
                v
        Customer ko Final Reply milta hai
```

---

## Har File Ka Role

### `llm.py` — Transport Layer

Sirf ek kaam: LLM se baat karna. Zero business logic.

```
chat(messages, temperature, tools, tool_choice) -> dict

Returns:
  reply       -- text response (None agar tool call hai)
  message     -- raw message object (tool_calls isme hote hain)
  tool_calls  -- list of tool calls (None agar plain reply)
  input_tokens, output_tokens, latency_ms, model
```

### `tools.py` — Tools Registry

Sab tools ek hi jagah define hain. `TOOL_SCHEMAS` automatically generate hota hai.

```
TOOLS = {
  "get_order_status": {
    "function": get_order_status,   # actual Python function
    "args": GetOrderStatusArgs,     # Pydantic validation model
    "risk": "read",                 # permission level
    "description": "...",          # LLM ke liye natural language description
  },
  "create_support_ticket": {
    "function": create_support_ticket,
    "args": CreateSupportTicketArgs,
    "risk": "write",
    "precheck": can_create_support_ticket,  # optional business check
    "description": "...",
  }
}

5 available tools:
  1. get_order_status       order info (PII-safe: email filter hoti hai)
  2. get_address            delivery address lookup
  3. create_support_ticket  WRITE tool, human approval chahiye
  4. find_orders_by_email   email se orders dhundho (multi-step ke liye)
  5. search_policy          RAG se exact policy text
```

### `store_chroma.py` — RAG Layer

```
build_index():
  document padhna
  → chunker.py se sections mein todna
  → nomic-embed-text se embeddings banana
  → ChromaDB mein upsert

search(query, k=3):
  query embed karo
  → cosine similarity search ChromaDB mein
  → top-k passages return karo (section naam ke saath)
  → score = 1 - cosine_distance (higher = better)
```

### `chunker.py` — Document Processor

```
3 chunking strategies (educational progression):
  1. chunk_fixed(300 chars)    naive — section boundary cross karta hai
  2. chunk_by_paragraph()      better — paragraphs intact rakhta hai
  3. chunk_document()          BEST — kabhi section boundary cross nahi karta
                                format: "[source > section]\nbody text"
                                yahi production mein use hota hai
```

### `agent.py` — Main Orchestrator

```
looks_malicious(text)         → bool         input guardrail
needs_tool(question)          → bool         routing decision
extract_ids(text)             → list[str]    digit-runs from customer message
collect_ids(obj)              → set[str]     digit-runs from tool result (grounding)
is_grounded(known_ids, args)  → (bool, str)  id arguments validate karo
verify_reply(reply, known_ids)→ (bool, str)  output mein invented numbers
verify_no_false_claim(reply, write_succeeded) → (bool, str)  false action claims
execute_tool(name, args, known_ids, approver) → dict  7-gate pipeline
ask_with_tools(messages, question, forced)    → dict  LLM call + retry logic
run(question, approver)       → dict         complete pipeline

Approval functions:
  approve_none()      → default, har write deny karo (safe by default)
  approve_all()       → tests ke liye
  approve_by_asking() → terminal par human se poochho (HITL)
```

---

## Key Engineering Decisions

### 1. Grounding (GATE 4)

**Problem:** Model silently "44712" ko "4471" se replace kar sakta hai (ID hallucination).

**Solution:** `known_ids` set throughout the loop track karo.
- Start: customer ke message ke sab digit-runs
- Expand: har successful tool result ke saath
- Check: har tool call ke *_id argument yahan se aana chahiye

### 2. PII Protection

**Problem:** `customer_email` kabhi LLM context mein nahi jaani chahiye.

**Solution:** `PUBLIC_ORDER_FIELDS = ("item", "status", "expected_delivery", "total_inr")`
Database mein `customer_email` hai, lekin tool response mein sirf yahi 4 fields jaati hain.
Test `test_read_tool_leaks_no_email` yeh guarantee karta hai.

### 3. Write Permission (GATE 6)

**Problem:** Agent autonomous write operations nahi kar sakta — yeh unsafe hai.

**Solution:** Risk-based permission:
- `"risk": "read"` → auto execute
- `"risk": "write"` → `approver` function required
- `"risk": "destructive"` → human approval, always

Default `approve_none` — har write deny. Production mein `approve_by_asking` use karo.

### 4. Idempotency

**Problem:** Network retry pe duplicate support ticket ban sakta hai.

**Solution:** `key = f"{order_id}:{issue.strip().lower()}"` — same key milti hai to existing ticket return karo naya banaye bina.

### 5. Precondition Before Approval (GATE 5)

**Problem:** Unknown order ke liye human ka dhyan waste karna theek nahi.

**Solution:** `precheck` PEHLE run hota hai (GATE 5), approval BAAD mein (GATE 6).
Order exist nahi → `precondition_failed` immediately, human se poochha hi nahi.

### 6. Output Guardrails

**Problem:** Model reply mein invented order numbers ya false success claims dal sakta hai.

**Two checks:**
- `verify_reply()` — koi bhi 3+ digit number jo `known_ids` mein nahi = regenerate
- `verify_no_false_claim()` — "ticket created" type phrases without actual write success = regenerate
- Agar regenerated reply bhi fail = specialist ko escalate

### 7. Forced Tool Call + Retry

**Problem:** Model tool_choice="required" ke bawajood kabhi kabhi tool skip karta hai.

**Solution:** Agar model ne skip kiya aur exactly 1 candidate ID hai → nudge with that exact id aur retry.
Agar multiple IDs hain → ambiguous hai, nudge nahi karte.

---

## Common Issues aur Fix

### `ModuleNotFoundError: No module named 'chromadb'`

```bash
pip install chromadb
```

### `Connection refused` (Ollama nahi chal raha)

```bash
ollama serve   # alag terminal mein start karo
```

### `nomic-embed-text model not found`

```bash
ollama pull nomic-embed-text
```

### `chroma_db` empty ya search galat results de raha hai

```bash
python store_chroma.py   # index rebuild karo
```

### `NameError: name 'CLAIM_PHRASES' is not defined`

`CLAIM_PHRASES` constant `agent.py` mein `MAX_STEPS` ke neeche (~line 568) define hai.
`verify_no_false_claim()` function isse use karta hai — dono ek hi scope mein hain.

---

## Individual File Testing

```bash
# 1. LLM connection test karo (Ollama running hona chahiye)
python llm.py

# 2. Chunker test karo (koi dependency nahi)
python chunker.py

# 3. RAG index build karo aur search test karo
python store_chroma.py

# 4. Tool schemas verify karo (structure check)
python tools.py

# 5. Unit tests (no LLM, no Ollama needed)
pytest test_agent.py -v

# 6. Full agent run karo (Ollama required)
python agent.py
```

---

## Naya Tool Add Karna

1. **`tools.py` mein Pydantic model banao:**

   ```python
   class MyToolArgs(BaseModel):
       model_config = ConfigDict(extra="forbid")
       order_id: str = Field(..., pattern=r"^\d+$", max_length=12)
   ```

2. **Function implement karo:**

   ```python
   def my_tool(order_id: str) -> dict:
       # ...
       return {"found": True, "data": ...}
   ```

3. **TOOLS registry mein add karo:**

   ```python
   TOOLS = {
       ...,
       "my_tool": {
           "function": my_tool,
           "args": MyToolArgs,
           "risk": "read",        # ya "write" agar side effects hain
           "description": "...",  # LLM ke liye clear explanation
           # "precheck": my_check,  # optional business validation
       }
   }
   ```

4. **Tests likho** — minimum: happy path + GATE 1 (unknown tool) + GATE 4 (grounding).

`TOOL_SCHEMAS` auto-generate hota hai. LLM ko apne aap pata chal jaata hai naya tool.

---

## Token aur Cost Estimate

| Scenario                     | LLM Calls | Approx Tokens |
|------------------------------|-----------|---------------|
| Simple order query           | 2         | ~800          |
| Policy question (RAG)        | 2         | ~1200         |
| Multi-step (email to order)  | 3         | ~1500         |
| Write with approval          | 2         | ~900          |
| Blocked by guardrail         | 0         | 0             |

Ollama use karne par cost = Rs 0.
OpenAI gpt-4o-mini use karne par approximately Rs 0.001 per query.
