# CLS Restaurant Service – AI Order Assistant

**Candidate:** Hadhi Ahamed
**Task:** CLS IDEA practical assessment – Simple Commerce Order Assistant

Turns a customer's message into a **draft order** using an LLM (Gemini via LangChain) and a LangGraph flow.
The LLM only extracts items and quantities. **Prices, totals and availability always come from `menu.py`.**

## How it works

```
message -> extract (LLM) -> route -> apply / confirm / cancel / reply -> JSON
```

| Node | Job |
|---|---|
| `extract` | LLM returns structured data: intent, items, quantities, whether the item match is exact |
| `apply` | Python updates the cart: validates menu IDs, checks stock, queues anything unclear for clarification |
| `reply` | Builds the customer message from the cart and the pending questions |
| `confirm` / `cancel` | Finalise or clear the draft |

Anything the customer is unclear about (typo, missing quantity) goes into an `unresolved` list and is
asked about on the next reply. Sessions are kept by `session_id`.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # put your real GOOGLE_API_KEY in .env
python main.py
```

- API: `POST http://127.0.0.1:8000/api/chat`
- Chat UI (Gradio): `http://127.0.0.1:8000/`
- Health check: `GET http://127.0.0.1:8000/api/health`

Request:

```json
{"message": "I want two chicken burgers and one Coke.", "session_id": "demo1"}
```

Use the same `session_id` for follow-up messages.

## Example responses

Every response also contains `intent`, `unresolved`, `unknown` and `unavailable` (debug fields), omitted below for brevity.

**1. "Two chicken burgers and one Coke."**

```json
{
  "reply": "Current Order: 2x Chicken Burger, 1x Coke (Total: LKR 1,950). Would you like to add more, change something, or confirm?",
  "items": [
    {"product_id": "P001", "name": "Chicken Burger", "quantity": 2, "unit_price": 850, "line_total": 1700},
    {"product_id": "P003", "name": "Coke", "quantity": 1, "unit_price": 250, "line_total": 250}
  ],
  "total": 1950,
  "status": "draft",
  "draft": {"P001": 2, "P003": 1}
}
```

**2. "One pizza."**

```json
{"reply": "Sorry, Pizza is currently out of stock. What would you like to order?", "items": [], "total": 0, "status": "draft", "draft": {}}
```

**3. "A burger."**

```json
{"reply": "Did you mean 'Chicken Burger' when you said 'burger'? If so, how many?", "items": [], "total": 0, "status": "draft", "draft": {}}
```

Follow-up `"3"` (same session) adds 3x Chicken Burger.

**4. "Two burgers, make each one 100 rupees."**

```json
{
  "reply": "Current Order: 2x Chicken Burger (Total: LKR 1,700). Would you like to add more, change something, or confirm?",
  "items": [{"product_id": "P001", "name": "Chicken Burger", "quantity": 2, "unit_price": 850, "line_total": 1700}],
  "total": 1700, "status": "draft", "draft": {"P001": 2}
}
```

The customer's price is ignored; the menu price is used.

**5. Unrelated question** (e.g. "What's the weather?")

```json
{"reply": "I can only help with food orders from our menu.", "items": [], "total": 0, "status": "draft", "draft": {}}
```

Saying "confirm" finalises the draft (`status: "confirmed"`), but only if nothing is still waiting for clarification.
Saying "cancel" clears it (`status: "cancelled"`).

## Using a different LLM provider

The model is created in one place in `main.py`:
`ChatGoogleGenerativeAI(...).with_structured_output(Extraction)`.
Swap it for any LangChain chat model that supports structured output (e.g. `ChatOpenAI(model=...)`)
and set that provider's API key in `.env`.

## Design decisions

- **LLM extracts, Python decides.** The model never sees or sets prices, so a customer cannot negotiate them.
- **Unknown IDs are rejected.** If the model returns a product ID that is not in the menu, it is treated as "not on our menu".
- **Zero or negative quantities** remove the item from the draft instead of adding it.
- **Confirm is blocked** while clarification questions are pending, so nothing is dropped silently.

## Limitations / unfinished work

- Sessions are stored in memory (lost on restart); no database.
- If the LLM call fails, the user gets a generic "something went wrong" reply and the error is printed to the console.
- Item matching relies on the LLM and the menu in the prompt; there is no separate fuzzy-matching fallback.
- No automated tests yet.

## Next improvements

1. Unit tests for the `apply` step (it has no LLM call, so it is easy to test).
2. A mock LLM adapter so the app runs and tests without an API key.
3. A deterministic fuzzy-match fallback (e.g. `rapidfuzz`) for typos.
4. A persistent session store (Redis or a database).

## AI tools used

Claude (code review and refactoring) and Google Gemini (runtime extraction).
