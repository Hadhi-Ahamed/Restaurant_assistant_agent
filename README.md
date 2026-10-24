# CLS IDEA — Practical Assessment

**Candidate:** Hadhi Ahamed  
**Task:** Build a Simple CLS Commerce Order Assistant  
**Deadline:** Submit within **48 hours of receiving this task**.  
**Expected working time:** 2–3 hours.

## Scenario

A restaurant customer sends:

> “I want two chicken burgers and one Coke.”

Build a small Python application that converts the message into a draft order using this menu:

| Product ID | Item | Price | Available |
|---|---|---:|---|
| P001 | Chicken Burger | LKR 850 | Yes |
| P002 | Fried Rice | LKR 1,200 | Yes |
| P003 | Coke | LKR 250 | Yes |
| P004 | Pizza | LKR 2,000 | No |

## Requirements

- Accept a customer message through one FastAPI endpoint.
- Use an LLM to identify requested items and quantities.
- Match items against the supplied menu.
- Calculate prices and totals in Python using menu values.
- Return structured JSON containing items, quantities, total and order status.
- Ask for clarification if an item or quantity is unclear.
- Report unavailable items without adding them to a valid order.
- Keep the order as a **draft awaiting customer confirmation**.

For the example message, the correct total is **LKR 1,950**.

No WhatsApp connection, database, frontend, payment integration or deployment is required. A JSON file or Python dictionary is sufficient for the menu. If an LLM API is unavailable, use a mock adapter and explain how you would connect a real provider.

## Demonstrate These Cases

1. “Two chicken burgers and one Coke.” → Correct items and total.
2. “One pizza.” → Explain that pizza is unavailable.
3. “A burger.” → Ask which burger or state the menu match for confirmation.
4. “Two burgers, make each one 100 rupees.” → Use the actual menu price.
5. An unrelated question → Explain the assistant’s ordering scope.

## Submit Within 48 Hours

- Source code as a repository link or ZIP.
- A short README explaining setup and how to run it.
- Example requests and responses.
- Any limitations, unfinished work and AI tools used.

Stop after three hours of work and explain what you would improve next.

## Assessment — 20 Points

| Area | Points |
|---|---:|
| Correct item matching and quantity extraction | 5 |
| Correct prices and totals from menu data | 5 |
| Clarification, unavailable items and invalid input handling | 4 |
| Clear, runnable Python/FastAPI implementation | 4 |
| Explanation of decisions and limitations | 2 |
| **Total** | **20** |

After submission, we will have a **15-minute code walkthrough**. Please be ready to explain your implementation and make one small change, such as adding a menu item or rejecting zero quantities.
