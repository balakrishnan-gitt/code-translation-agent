# Code Translation Agent (JavaScript to Python)

An agent that reads a local JavaScript file and rewrites its logic in Python, **keeping the same variable and function names** (camelCase is not converted to snake_case).

No API key and no extra packages needed. Python 3.8+ only.

## How it works
1. **Read** the `.js` file.
2. **Extract names**: every variable, function, class and parameter name is collected.
3. **Translate**: a rule-based translator rewrites each construct as Python and leaves names untouched.
4. **Verify**: Python's `ast` module parses the output, then every JS name must appear in the Python code.
5. **Repair or save**: on a syntax error, the agent uses the error line to fix or flag that line (marked `TODO`), then verifies again (up to 3 checks). On success, `output.py` is written.

Only allowed rename: a name that is a Python keyword gets a trailing underscore (`from` becomes `from_`).

## Usage
```
python agent.py input.js
python agent.py input.js -o result.py --retries 5
```

## Example
`input.js`
```js
const taxRate = 0.18;
function calcTotal(cartItems) {
  let totalPrice = 0;
  for (const item of cartItems) {
    totalPrice += item.price * item.qty;
  }
  return totalPrice * (1 + taxRate);
}
```
`output.py`
```python
taxRate = 0.18

def calcTotal(cartItems):
    totalPrice = 0
    for item in cartItems:
        totalPrice += item["price"] * item["qty"]
    return totalPrice * (1 + taxRate)
```

## Supported
Variables, functions, arrow functions, `if/else if/else`, `for` (of, in, counting loops), `while`, classes, `try/catch`, objects and arrays, template strings, ternaries, `console.log`, common `Math` functions.

## Limitations
- Constructs like `switch`, `async/await` and DOM APIs are not translated; those lines are marked `TODO`.
- Name extraction is regex-based, so destructuring (`const {a, b} = obj`) is not tracked.
- Output is checked for syntax and names, not behavior. Review it before use.

## Files
| File | Purpose |
|---|---|
| `agent.py` | The agent |
| `input.js` | Sample input |
| `index.html` | Project website (GitHub Pages) |

Agentic AI course project, Sathyabama University. Submitted by Balakrishnan G (44110099) and Balamurugan (44110100).
