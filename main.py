from typing import Literal, TypedDict
from dotenv import load_dotenv
from fastapi import FastAPI
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel
#import traceback
import uvicorn
import gradio as gr
import uuid
from pathlib import Path


from menu import MENU, menu_to_prompt
from dotenv import load_dotenv

load_dotenv()

# ---------- 1. LLM Schema ----------
class Item(BaseModel):
    product_id: str | None = None
    raw_name: str | None = None
    quantity: int | None = None
    action: Literal["add", "remove", "modify"] = "add"

class Extraction(BaseModel):
    intent: Literal["update_order", "confirm", "cancel", "menu_inquiry", "greeting", "out_of_scope"]
    items: list[Item] = []

PROMPT = """Extract the customer's food order intent and items using this menu:
{menu}

Current Draft in Cart:
{current_draft}

Pending question: the customer was just asked how many of: {pending}.
If their message is only a quantity (e.g. "3"), return that pending item with its product_id, that quantity and action "add".

Message Intent must be one of:
- update_order: customer wants to add, modify, swap, or remove items.
- confirm: customer wants to finalize, finish, or checkout.
- cancel: customer wants to abort the order entirely.
- greeting: general greetings (hi, hello).
- menu_inquiry: asking what food is available or asking for the menu.
- out_of_scope: unrelated questions.

For each item:
- product_id: matched menu ID, or null if NOT on menu.
- raw_name: item name as spoken by user.
- quantity: the number requested, or null if no explicit number was given (words like "a", "an", "some" count as unspecified).
- action: "add" (to add to cart), "remove" (to delete from cart), or "modify" (to set exact quantity).
  NOTE: If customer says "replace/swap X with Y", mark X with action="remove" and Y with action="add"."""

llm = ChatGoogleGenerativeAI(model="gemini-3.5-flash", temperature=0).with_structured_output(Extraction)

# ---------- 2. Graph State ----------
class AgentState(TypedDict, total=False):
    message: str
    draft: dict[str, int]   # {product_id: quantity}
    pending: list[str]      # product_ids waiting for quantity clarification
    unknown: list[str]       # items not found on the menu at all
    unavailable: list[str]   # valid menu items that are out of stock
    intent: str
    items: list[dict]
    reply: str
    status: str             # "confirmed", "cancelled", or "draft"

# ---------- 3. Nodes ----------
import traceback

def extract(state: AgentState):
    draft = state.get("draft", {})
    draft_summary = (
        ", ".join(f"{qty}x {MENU[pid]['name']}" for pid, qty in draft.items())
        if draft else "Empty"
    )

    pending = ", ".join(MENU[pid]["name"] for pid in state.get("pending", [])) or "None"

    try:
        ex = llm.invoke([
            ("system", PROMPT.format(menu=menu_to_prompt(), current_draft=draft_summary, pending=pending)),
            ("human", state.get("message", ""))
        ])
        return {"intent": ex.intent, "items": [i.model_dump() for i in ex.items]}

    except Exception as e:
        print("\n" + "=" * 50)
        print("[CRITICAL EXTRACTION FAILURE]")
        traceback.print_exc()
        print("=" * 50 + "\n")
        return {"intent": "out_of_scope"}

def route(state: AgentState):
    if state.get("intent") in ("confirm", "cancel", "out_of_scope"):
        return state["intent"] if state["intent"] in ("confirm", "cancel") else "reply"
    return "apply"

def apply(state: AgentState):
    draft = dict(state.get("draft", {}))
    pending = []
    unknown = []
    unavailable = []

    for item in state.get("items", []):
        pid = item.get("product_id")
        qty = item.get("quantity")
        raw = item.get("raw_name")
        action = item.get("action", "add")

        # 1. Unknown item check
        if not pid or pid not in MENU:
            if raw:
                unknown.append(raw)
            continue

        # 2. If removing, we don't care if it's currently out of stock
        if action == "remove":
            draft.pop(pid, None)
            continue

        # 3. For adding/modifying, check stock availability
        if not MENU[pid].get("available", True):
            unavailable.append(MENU[pid]["name"])
            continue

        # 4. Check for missing quantity
        if qty is None:
            pending.append(pid)
            continue

        # 5. Apply the item-level change
        if action == "modify":
            draft[pid] = qty
        elif action == "add":
            draft[pid] = draft.get(pid, 0) + qty

    return {
        "draft": draft,
        "pending": pending,
        "unknown": unknown,
        "unavailable": unavailable,
        "status": "draft"
    }

def confirm(state: AgentState):
    draft = state.get("draft", {})
    if not draft:
        return {"reply": "Cannot confirm an empty order. Please add items first.", "status": "draft"}

    order_str = ", ".join(f"{qty}x {MENU[pid]['name']}" for pid, qty in draft.items())
    total = sum(MENU[pid]["price"] * qty for pid, qty in draft.items())

    return {
        "draft": draft,
        "reply": (
            f"Order confirmed! Details: {order_str} (Total: LKR {total:,}). "
            "Thank you for choosing CLS Restaurant Service! Have a wonderful meal."
        ),
        "status": "confirmed"
    }

def cancel(state: AgentState):
    return {
        "draft": {},
        "pending": [],
        "reply": "Your order has been cancelled. Thank you for visiting CLS Restaurant Service. Have a great day!",
        "status": "cancelled"
    }

def reply(state: AgentState):
    if "reply" in state:
        return {"reply": state["reply"]}

    intent = state.get("intent")

    if intent == "greeting":
        return {"reply": "Welcome to CLS Restaurant Service! Please let us know what you would like to order."}

    if intent == "menu_inquiry":
        available_items = [f"{m['name']} (LKR {m['price']:,})" for m in MENU.values() if m.get("available", True)]
        return {"reply": f"We currently offer: {', '.join(available_items)}. What would you like to have?"}

    if intent == "out_of_scope":
        return {"reply": "I can only help with food orders from our menu."}

    parts = []

    # 1. Report out-of-stock items
    unavailable = state.get("unavailable", [])
    if unavailable:
        parts.append(f"Sorry, {', '.join(unavailable)} is currently out of stock.")

    # 2. Report non-existent items
    unknown = state.get("unknown", [])
    if unknown:
        parts.append(f"Sorry, we don't have {', '.join(unknown)} on our menu.")

        
    draft = state.get("draft", {})
    if draft:
        order_str = ", ".join(f"{qty}x {MENU[pid]['name']}" for pid, qty in draft.items())
        total = sum(MENU[pid]["price"] * qty for pid, qty in draft.items())
        parts.append(f"Current Order: {order_str} (Total: LKR {total:,}).")

    if state.get("pending"):
        items = ", ".join(MENU[pid]["name"] for pid in state["pending"])
        parts.append(f"Did you mean {items}? How many would you like?")
    elif draft:
        parts.append("Would you like to add more, change something, or confirm?")
    else:
        parts.append("What would you like to order?")

    return {"reply": " ".join(parts)}

# ---------- 4. Graph Construction ----------
graph = StateGraph(AgentState)
for name, fn in [("extract", extract), ("apply", apply), ("confirm", confirm), ("cancel", cancel), ("reply", reply)]:
    graph.add_node(name, fn)

graph.add_edge(START, "extract")
graph.add_conditional_edges("extract", route, {
    "reply": "reply",
    "cancel": "cancel",
    "confirm": "confirm",
    "apply": "apply"
})
for name in ("apply", "confirm", "cancel"):
    graph.add_edge(name, "reply")
graph.add_edge("reply", END)

agent = graph.compile()

# ---------- 5. Session Runner ----------
SESSIONS: dict[str, dict] = {}

def chat_turn(session_id: str, message: str) -> dict:
    saved = SESSIONS.get(session_id, {"draft": {}, "pending": []})
    out = agent.invoke({"message": message, **saved})

    if out.get("status") in ("confirmed", "cancelled"):
        SESSIONS.pop(session_id, None)
    else:
        SESSIONS[session_id] = {
            "draft": out.get("draft", {}),
            "pending": out.get("pending", [])
        }

    draft = out.get("draft", {})
    items = [
        {
            "product_id": pid,
            "name": MENU[pid]["name"],
            "quantity": qty,
            "unit_price": MENU[pid]["price"],
            "line_total": MENU[pid]["price"] * qty,
        }
        for pid, qty in draft.items()
    ]
    return {
        "reply": out["reply"],
        "items": items,
        "total": sum(i["line_total"] for i in items),
        "status": out.get("status", "draft"),
        "draft": draft,
    }


# ---------- 6. Gradio UI Definition ----------
import json

def gradio_chat(user_message, history, session_state):
    if not user_message or not str(user_message).strip():
        return "", history, session_state

    # Initialize or retrieve session ID
    if not session_state or "id" not in session_state:
        session_state = {"id": str(uuid.uuid4())}

    session_id = session_state["id"]
    response = chat_turn(session_id, user_message)

    # Build the order payload
    order_data = {
        "items": response["items"],
        "total": response["total"],
        "status": response["status"]
    }

    # Append JSON block cleanly to the bot's reply
    json_block = f"```json\n{json.dumps(order_data, indent=2)}\n```"
    bot_reply = f"{response['reply']}\n\n{json_block}"

    # In Gradio 5+, history must be a list of dictionaries with 'role' and 'content'
    history = list(history) if history else []
    history.append({"role": "user", "content": user_message})
    history.append({"role": "assistant", "content": bot_reply})

    return "", history, session_state

with gr.Blocks(title="CLS Restaurant Service") as gradio_app:
    session_state = gr.State({})

    gr.Image(
        value=str(Path(__file__).parent / "image.png"),
        show_label=False,
        container=False,
        height=220
    )
    gr.Markdown(
        """
        # CLS Restaurant Service
        *Inquire about our menu, modify your cart, or confirm your checkout.*
        """
    )

    chatbot = gr.Chatbot(height=350)

    with gr.Row():
        txt_input = gr.Textbox(
            show_label=False,
            placeholder="Type your message (e.g., 'What is on the menu?', '2 Chicken Burgers', 'confirm')...",
            scale=8
        )
        send_btn = gr.Button("Send", variant="primary", scale=1)

    txt_input.submit(gradio_chat, [txt_input, chatbot, session_state], [txt_input, chatbot, session_state])
    send_btn.click(gradio_chat, [txt_input, chatbot, session_state], [txt_input, chatbot, session_state])

# ---------- 7. FastAPI App & Mount ----------
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

# Mount Gradio at root (or change path to "/ui" to keep "/" open)
app = gr.mount_gradio_app(app, gradio_app, path="/")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)

