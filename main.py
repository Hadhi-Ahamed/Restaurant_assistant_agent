import traceback
import uuid
from typing import Literal, TypedDict

import gradio as gr
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
from pathlib import Path

from menu import MENU, menu_to_prompt

load_dotenv()


# ---------- 1. LLM schema + prompt ----------
class ExtractedItem(BaseModel):
    product_id: str | None = None   # best matching menu ID, null if nothing plausible
    exact: bool = True              # False for typos/slang -> needs user confirmation
    raw_name: str = ""              # what the customer actually typed
    quantity: int | None = None     # null if the customer gave no number
    action: Literal["add", "remove", "modify"] = "add"


class Extraction(BaseModel):
    intent: Literal[
        "update_order", "confirm", "cancel",
        "menu_inquiry", "greeting", "out_of_scope",
    ]
    items: list[ExtractedItem] = []
    affirms_unresolved: bool = False


PROMPT = """You are an order extraction engine for a restaurant.

Menu:
{menu}

Cart: {cart}
Waiting for customer clarification: {pending}

Rules:
1. Map every item the customer mentions to a menu ID in `product_id`.
   - Clear match: `exact: true`.
   - Typo or slang (e.g. "booger", "frize"): put the closest menu ID in `product_id` and set `exact: false`.
   - Nothing plausible: `product_id: null`.
   - Always copy the customer's own words into `raw_name`.
   - `quantity` stays null unless the customer gave a number ("2 burgers" -> 2) or "a" or "an" is 1 ("a burger" -> 1).
2. If something is waiting for clarification:
   - "yes" / "correct" -> `affirms_unresolved: true`.
   - A bare number ("2", "make it three") -> emit that item with that quantity.
3. "remove X" -> action "remove". "replace X with Y" -> X as remove, Y as add.
   "make it 3 burgers" -> action "modify".

Intent:
- update_order: add, modify, swap, clarify or remove items.
- confirm: checkout / finalize.
- cancel: abort the whole order.
- greeting: hello etc.
- menu_inquiry: asking about the menu or prices.
- out_of_scope: anything else."""

llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash-lite", temperature=0
).with_structured_output(Extraction)


# ---------- 2. State + small helpers ----------
class AgentState(TypedDict, total=False):
    message: str
    draft: dict[str, int]       # {product_id: quantity}
    unresolved: list[dict]      # items waiting for the customer to clarify
    unknown: list[str]          # names not on the menu
    unavailable: list[str]      # out-of-stock names
    intent: str
    items: list[dict]
    affirms_unresolved: bool
    reply: str
    status: str


def cart_text(draft: dict[str, int]) -> str:
    return ", ".join(f"{qty}x {MENU[pid]['name']}" for pid, qty in draft.items())


def cart_total(draft: dict[str, int]) -> int:
    return sum(MENU[pid]["price"] * qty for pid, qty in draft.items())


def pending_text(pending: list[dict]) -> str:
    if not pending:
        return "None"
    return "; ".join(
        f"'{p['raw_name']}' -> {MENU[p['product_id']]['name']} "
        f"(qty: {p['quantity'] or 'MISSING'}, confirmed: {p['exact']})"
        for p in pending
    )


def clarification_question(p: dict) -> str:
    name = MENU[p["product_id"]]["name"]
    if not p["exact"] and p["quantity"] is None:
        return f"Did you mean '{name}' when you said '{p['raw_name']}'? If so, how many?"
    if not p["exact"]:
        return f"Did you mean {p['quantity']}x '{name}' when you said '{p['raw_name']}'?"
    return f"How many '{name}' would you like?"


# ---------- 3. Nodes ----------
def extract(state: AgentState):
    draft = state.get("draft", {})
    system_prompt = PROMPT.format(
        menu=menu_to_prompt(),
        cart=cart_text(draft) if draft else "Empty",
        pending=pending_text(state.get("unresolved", [])),
    )
    try:
        ex = llm.invoke([("system", system_prompt), ("human", state["message"])])
        return {
            "intent": ex.intent,
            "items": [i.model_dump() for i in ex.items],
            "affirms_unresolved": ex.affirms_unresolved,
        }
    except Exception:
        traceback.print_exc()
        return {"intent": "error", "items": [], "affirms_unresolved": False}


def route(state: AgentState) -> str:
    intent = state["intent"]
    if intent in ("confirm", "cancel"):
        return intent
    if intent == "update_order":
        return "apply"
    return "reply"  # greeting, menu_inquiry, out_of_scope, error


def apply(state: AgentState):
    draft = dict(state.get("draft", {}))
    pending = list(state.get("unresolved", []))
    items = list(state.get("items", []))
    unknown, unavailable = [], []

    # "yes" -> treat the pending guesses as confirmed and run them
    # through the same pipeline as brand-new items.
    if state.get("affirms_unresolved"):
        items = [{**p, "exact": True} for p in pending] + items
        pending = []

    for item in items:
        pid, qty = item["product_id"], item["quantity"]
        raw, action = item["raw_name"], item["action"]

        # Not on the menu (also guards against made-up IDs)
        if pid not in MENU:
            if raw:
                unknown.append(raw)
            continue

        # Whatever happens next, this product no longer needs an older question
        pending = [p for p in pending if p["product_id"] != pid]

        if action == "remove" or (qty is not None and qty <= 0):
            draft.pop(pid, None)
        elif not MENU[pid].get("available", True):
            unavailable.append(MENU[pid]["name"])
        elif not item["exact"] or qty is None:
            pending.append(item)            # ask the customer to clarify
        elif action == "modify":
            draft[pid] = qty
        else:
            draft[pid] = draft.get(pid, 0) + qty

    return {
        "draft": draft,
        "unresolved": pending,
        "unknown": unknown,
        "unavailable": unavailable,
        "status": "draft",
    }


def confirm(state: AgentState):
    draft = state.get("draft", {})
    pending = state.get("unresolved", [])

    if not draft:
        return {"reply": "Cannot confirm an empty order. Please add items first.", "status": "draft"}
    if pending:
        questions = " ".join(clarification_question(p) for p in pending)
        return {"reply": f"Before we confirm, I need to clear something up. {questions}", "status": "draft"}

    return {
        "reply": (
            f"Order confirmed! Details: {cart_text(draft)} (Total: LKR {cart_total(draft):,}). "
            "Thank you for choosing CLS Restaurant Service! Have a wonderful meal."
        ),
        "status": "confirmed",
    }


def cancel(state: AgentState):
    return {
        "draft": {},
        "unresolved": [],
        "reply": "Your order has been cancelled. Thank you for visiting CLS Restaurant Service. Have a great day!",
        "status": "cancelled",
    }


CANNED_REPLIES = {
    "greeting": "Welcome to CLS Restaurant Service! Please let us know what you would like to order.",
    "out_of_scope": "I can only help with food orders from our menu.",
    "error": "Sorry, something went wrong on our side. Please try again.",
}


def reply(state: AgentState):
    intent = state.get("intent")

    if intent in CANNED_REPLIES:
        return {"reply": CANNED_REPLIES[intent]}

    if intent == "menu_inquiry":
        offered = [f"{m['name']} (LKR {m['price']:,})" for m in MENU.values() if m.get("available", True)]
        return {"reply": f"We currently offer: {', '.join(offered)}. What would you like to have?"}

    # intent == "update_order": build the reply piece by piece
    parts = []
    draft = state.get("draft", {})
    pending = state.get("unresolved", [])

    if state.get("unavailable"):
        parts.append(f"Sorry, {', '.join(state['unavailable'])} is currently out of stock.")
    if state.get("unknown"):
        names = ", ".join(f"'{n}'" for n in state["unknown"])
        parts.append(f"Sorry, we don't have {names} on our menu.")
    if draft:
        parts.append(f"Current Order: {cart_text(draft)} (Total: LKR {cart_total(draft):,}).")

    if pending:
        parts.extend(clarification_question(p) for p in pending)
    elif draft:
        parts.append("Would you like to add more, change something, or confirm?")
    else:
        parts.append("What would you like to order?")

    return {"reply": " ".join(parts)}


# ---------- 4. Graph ----------
graph = StateGraph(AgentState)
for name, fn in [("extract", extract), ("apply", apply), ("confirm", confirm),
                 ("cancel", cancel), ("reply", reply)]:
    graph.add_node(name, fn)

graph.add_edge(START, "extract")
graph.add_conditional_edges("extract", route, ["apply", "confirm", "cancel", "reply"])
graph.add_edge("apply", "reply")
for end_node in ("confirm", "cancel", "reply"):
    graph.add_edge(end_node, END)

agent = graph.compile()


# ---------- 5. Session runner ----------
SESSIONS: dict[str, dict] = {}  # in-memory: fine for practice, use Redis/DB in real apps


def chat_turn(session_id: str, message: str) -> dict:
    saved = SESSIONS.get(session_id, {"draft": {}, "unresolved": []})
    out = agent.invoke({"message": message, **saved})

    status = out.get("status", "draft")
    draft = out.get("draft", {})

    if status in ("confirmed", "cancelled"):
        SESSIONS.pop(session_id, None)
    else:
        SESSIONS[session_id] = {"draft": draft, "unresolved": out.get("unresolved", [])}

    return {
        "reply": out.get("reply", ""),
        "status": status,
        "intent": out.get("intent", ""),
        "cart": {
            "items": [
                {"product_id": pid, "name": MENU[pid]["name"], "quantity": qty,
                 "subtotal": MENU[pid]["price"] * qty}
                for pid, qty in draft.items()
            ],
            "total_lkr": cart_total(draft),
        },
        "unresolved": out.get("unresolved", []),
        "unknown": out.get("unknown", []),
        "unavailable": out.get("unavailable", []),
    }


# ---------- 6. Gradio UI ----------
def gradio_chat(message, history, session_id):
    if not message or not message.strip():
        return "", history, None

    response = chat_turn(session_id, message)
    history = (history or []) + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response["reply"]},
    ]
    return "", history, response


with gr.Blocks(title="CLS Restaurant Service") as gradio_app:
    session_id = gr.State(lambda: str(uuid.uuid4()))  # fresh id per browser session

    gr.Image(
        value=str(Path(__file__).parent / "image.png"),
        show_label=False,
        container=False,
        height=220
    )

    gr.Markdown("# CLS Restaurant Service\n*Ask about the menu, edit your cart, or confirm your order.*")

    with gr.Row():
        with gr.Column(scale=6):
            chatbot = gr.Chatbot(height=500)
            with gr.Row():
                txt_input = gr.Textbox(
                    show_label=False,
                    placeholder="Type your message (e.g. 'Can I have 3 CHicken Burger please')...",
                    scale=8,
                )
                send_btn = gr.Button("Send", variant="primary", scale=2)
        with gr.Column(scale=4):
            gr.Markdown("### Debug payload")
            json_display = gr.JSON(label="State")

    gr.on(
        triggers=[txt_input.submit, send_btn.click],
        fn=gradio_chat,
        inputs=[txt_input, chatbot, session_id],
        outputs=[txt_input, chatbot, json_display],
    )


# ---------- 7. FastAPI ----------
app = FastAPI(title="CLS Restaurant Order API")


class ChatIn(BaseModel):
    message: str
    session_id: str = "default"


@app.post("/api/chat")
def chat_endpoint(body: ChatIn):
    return chat_turn(body.session_id, body.message)


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


app = gr.mount_gradio_app(app, gradio_app, path="/")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)