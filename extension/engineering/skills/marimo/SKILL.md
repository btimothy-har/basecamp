---
name: marimo
description: This skill should be used when creating or editing marimo reactive notebooks. Keywords: marimo, reactive notebook, data app, mo.ui.
---

# Marimo Reactive Notebooks

Extends the `python-development` skill. Marimo is a reactive Python notebook—stored as pure `.py` files, git-friendly, executable as scripts, and deployable as apps.

## Principles

**Reactivity**
- **Cells auto-run on change** - Edit a cell, and marimo runs all dependent cells automatically
- **No hidden state** - Delete a cell, and its variables are scrubbed from memory
- **Static analysis determines dependencies** - Based on variable references, not cell order
- **Deterministic execution** - Notebooks always execute in the same order based on the DAG

**Cell Rules**
- **One definition per variable** - Variables cannot be redefined across cells
- **Last expression is output** - The final expression in a cell is automatically displayed
- **Use `_` prefix for private variables** - Variables starting with `_` are cell-local
- **Assign UI elements to globals** - UI elements must be assigned to global variables to be reactive

**Data Flow**
- **UI elements are reactive** - Interact with a slider, and dependent cells re-run
- **Access values via `.value`** - All UI elements have a `.value` attribute
- **No callbacks needed** - Reactivity handles updates automatically

## Installation

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
    "marimo",
]

# For SQL support
[project.optional-dependencies]
sql = ["marimo[sql]"]
```

## CLI Commands

```bash
uv run marimo edit notebook.py      # Open/create notebook in editor
uv run marimo run notebook.py       # Run as app (code hidden)
uv run marimo edit --headless       # Run without opening browser
uv run marimo tutorial intro        # Run interactive tutorial
uv run marimo convert notebook.ipynb > notebook.py  # Convert from Jupyter
```

## Notebook Structure

Marimo notebooks are pure Python files:

```python
import marimo

app = marimo.App()

@app.cell
def _():
    import marimo as mo
    import pandas as pd
    return mo, pd

@app.cell
def _(mo):
    slider = mo.ui.slider(1, 100, value=50, label="Count")
    slider
    return slider,

@app.cell
def _(slider, pd):
    # This cell re-runs when slider changes
    df = pd.DataFrame({"values": range(slider.value)})
    df
    return df,

if __name__ == "__main__":
    app.run()
```

## UI Elements

### Basic Inputs

```python
import marimo as mo

# Slider
slider = mo.ui.slider(start=0, stop=100, value=50, step=1, label="Value")

# Number input
number = mo.ui.number(start=0, stop=100, value=10, label="Count")

# Text input
text = mo.ui.text(value="", label="Name", placeholder="Enter name")

# Text area
textarea = mo.ui.text_area(value="", label="Description")

# Checkbox
checkbox = mo.ui.checkbox(label="Enable feature", value=False)

# Dropdown
dropdown = mo.ui.dropdown(
    options=["Option A", "Option B", "Option C"],
    value="Option A",
    label="Choose one",
)

# Dropdown with key-value pairs
dropdown_kv = mo.ui.dropdown(
    options={"Label 1": "value1", "Label 2": "value2"},
    value="Label 1",
    label="Select",
)

# Radio buttons
radio = mo.ui.radio(
    options=["Small", "Medium", "Large"],
    value="Medium",
    label="Size",
)

# Multiselect
multiselect = mo.ui.multiselect(
    options=["A", "B", "C", "D"],
    label="Select multiple",
)

# Date picker
date = mo.ui.date(label="Select date")

# File upload
file = mo.ui.file(filetypes=[".csv", ".json"], label="Upload file")

# Button
button = mo.ui.button(label="Click me", kind="primary")

# Run button (triggers cell re-run)
run_button = mo.ui.run_button(label="Run analysis")
```

### Accessing Values

```python
@app.cell
def _(slider, dropdown, checkbox):
    # Access current values
    count = slider.value      # int
    choice = dropdown.value   # str
    enabled = checkbox.value  # bool
    
    mo.md(f"Count: {count}, Choice: {choice}, Enabled: {enabled}")
```

### Data Components

```python
# Interactive dataframe viewer
mo.ui.dataframe(df)

# Data explorer with visualizations
mo.ui.data_explorer(df)

# Interactive table with selection
table = mo.ui.table(
    data=df,
    selection="multi",  # or "single"
    pagination=True,
)
# Access selected rows: table.value
```

## Markdown

```python
import marimo as mo

# Basic markdown
mo.md("# Hello World")

# Markdown with Python values
name = "marimo"
mo.md(f"Welcome to **{name}**!")

# Embed UI elements in markdown
slider = mo.ui.slider(1, 10, label="Value")
mo.md(f"Choose a value: {slider}")

# LaTeX support
mo.md(r"The formula is $E = mc^2$")

# Multi-line with f-string
mo.md(f"""
# Analysis Results

- **Count**: {slider.value}
- **Status**: {"Active" if slider.value > 5 else "Inactive"}
""")
```

## Layout

```python
import marimo as mo

# Horizontal stack
mo.hstack([element1, element2, element3], justify="center", gap=2)

# Vertical stack
mo.vstack([element1, element2], align="start", gap=1)

# Tabs
mo.ui.tabs({
    "Tab 1": content1,
    "Tab 2": content2,
    "Tab 3": content3,
})

# Accordion
mo.accordion({
    "Section 1": content1,
    "Section 2": content2,
})

# Callout boxes
mo.callout("Important message", kind="info")  # info, warn, danger, success

# Grid layout
mo.ui.batch(
    mo.md("""
    | Setting | Value |
    |---------|-------|
    | Name    | {name} |
    | Count   | {count} |
    """),
    name=mo.ui.text(),
    count=mo.ui.number(start=0, stop=100),
)
```

## Forms

Group UI elements and submit together:

```python
# Create a form that submits on button click
form = mo.md("""
**Configuration**

- Epsilon: {epsilon}
- Delta: {delta}
- Name: {name}
""").batch(
    epsilon=mo.ui.slider(0.1, 1.0, step=0.1, value=0.5),
    delta=mo.ui.number(start=1, stop=10, value=5),
    name=mo.ui.text(value="default"),
).form(submit_button_label="Apply")

# Display the form
form

# Access submitted values (None until submitted)
if form.value:
    epsilon = form.value["epsilon"]
    delta = form.value["delta"]
```

## SQL Integration

```python
import marimo as mo

# SQL cells return dataframes
df = mo.sql(f"""
    SELECT *
    FROM my_table
    WHERE count > {slider.value}
    LIMIT 100
""")

# Use with DuckDB (auto-detected)
import duckdb
conn = duckdb.connect("data.db")

# Query Python dataframes directly
df = mo.sql(f"""
    SELECT * FROM df_source
    WHERE category = '{dropdown.value}'
""")
```

## Plotting

```python
import marimo as mo
import altair as alt

# Altair charts are automatically interactive
chart = alt.Chart(df).mark_point().encode(
    x="x:Q",
    y="y:Q",
    color="category:N",
)
chart

# Make chart selectable
selectable_chart = mo.ui.altair_chart(chart)
# Access selected points: selectable_chart.value
```

## Caching

```python
import marimo as mo

@mo.cache
def expensive_computation(x: int) -> int:
    # Result is cached based on input
    return x ** 2

# Or cache to disk
@mo.cache(pin=True)
def load_large_dataset(path: str):
    return pd.read_parquet(path)
```

## Running as Script/App

```bash
# Run as script (cells execute in topological order)
uv run python notebook.py

# Run as interactive app (code hidden)
uv run marimo run notebook.py

# Run with CLI args
uv run marimo run notebook.py -- --param1 value1
```

## Lazy Execution Mode

For expensive notebooks, mark cells as stale instead of auto-running:

```python
# In notebook settings or via CLI
uv run marimo edit notebook.py --lazy
```

## Common Patterns

### Conditional Display

```python
@app.cell
def _(checkbox, data):
    if checkbox.value:
        result = mo.md(f"Data: {data}")
    else:
        result = mo.md("Enable checkbox to see data")
    result
```

### Dynamic UI Elements

```python
@app.cell
def _(count_slider):
    # Create dynamic number of inputs
    inputs = mo.ui.array([
        mo.ui.text(label=f"Item {i}")
        for i in range(count_slider.value)
    ])
    inputs

@app.cell
def _(inputs):
    # Access all values
    values = inputs.value  # List of strings
    mo.md(f"Values: {values}")
```

### Stop Execution

```python
@app.cell
def _(data):
    # Stop cell execution if condition not met
    mo.stop(data is None, mo.md("**Waiting for data...**"))
    
    # Continue processing
    result = process(data)
    result
```

## Important Notes

- **No variable redefinition** - Each variable can only be defined in one cell
- **Use `_` prefix for cell-local variables** - `_temp = compute()` won't leak
- **Notebooks are DAGs** - Execution order is determined by dependencies, not position
- **Pure Python files** - Version control, import, test with standard tools
- **UI elements must be global** - Assign to variables without `_` prefix for reactivity