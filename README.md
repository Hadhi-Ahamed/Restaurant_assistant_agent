# CLS Restaurant Service – AI Order Assistant

Turns a customer's message into a **draft order** using an LLM (Gemini via LangChain) and a LangGraph flow.
The LLM only extracts items and quantities. Prices, totals and availability always come from `menu.py`.

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env        # then put your real GOOGLE_API_KEY in .env
python demo3.py
```
- API: `POST http://127.0.0.1:8000/api/chat`
- Chat UI (Gradio): `http://127.0.0.1:8000/`
- Health check: `GET http://127.0.0.1:8000/api/health`

## Request
```json
{"message": "I want two chicken burgers and one Coke.", "session_id": "demo1"}
```
`session_id` keeps the draft between messages (use the same id for follow-ups).

## Example responses
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
{"reply": "Did you mean Chicken Burger? How many would you like?", "items": [], "total": 0, "status": "draft", "draft": {}}
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
Saying "confirm" finalises the draft (`status: "confirmed"`); "cancel" clears it (`status: "cancelled"`).

## Using a different LLM provider
The model is created in one line in `demo3.py` (`ChatGoogleGenerativeAI(...).with_structured_output(Extraction)`).
Swap it for another LangChain chat model that supports structured output, e.g. `ChatOpenAI(model=...)`, and set that provider's API key in `.env`.

## Limitations / unfinished work
- Sessions are stored in memory (lost on restart); no database.
- If the LLM call fails, the message is treated as out of scope (the error is printed to the console).
- Item matching relies on the LLM using the menu IDs/aliases in the prompt; no separate fuzzy matching.
- Not tested at scale; no automated tests.

## AI tools used
Claude (code review and editing) and Google Gemini (runtime extraction).
