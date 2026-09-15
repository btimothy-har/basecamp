# Common Patterns

## CLI Script

```python
# /// script
# dependencies = ["typer"]
# requires-python = ">=3.12"
# ///
import typer

def main(name: str, count: int = 1) -> None:
    """Greet someone COUNT times."""
    for _ in range(count):
        typer.echo(f"Hello, {name}!")

if __name__ == "__main__":
    typer.run(main)
```

## Data Processing

```python
# /// script
# dependencies = ["pandas", "httpx"]
# requires-python = ">=3.12"
# ///
import pandas as pd
import httpx

def fetch_and_process(url: str) -> pd.DataFrame:
    """Fetch JSON data and return as DataFrame."""
    response = httpx.get(url)
    response.raise_for_status()
    return pd.DataFrame(response.json())
```

## Async Operations

```python
# /// script
# dependencies = ["httpx"]
# requires-python = ">=3.12"
# ///
import asyncio
import httpx

async def fetch_all(urls: list[str]) -> list[dict]:
    """Fetch multiple URLs concurrently."""
    async with httpx.AsyncClient() as client:
        tasks = [client.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return [r.json() for r in responses]

if __name__ == "__main__":
    results = asyncio.run(fetch_all(["https://api.example.com/1"]))
```

## Library Preferences

| Use Case | Preferred Library |
|----------|------------------|
| HTTP client | httpx |
| Data manipulation | pandas, polars |
| Data validation | pydantic |
| CLI tools | typer, click |
| File paths | pathlib (stdlib) |
| Date/time | datetime, zoneinfo (stdlib) |
| JSON/config | tomllib, json (stdlib) |

## Debugging

When scripts fail:

1. Check dependency spelling and version constraints
2. Run with `uv run --verbose` for detailed output
3. Verify Python version compatibility
4. Test imports interactively: `uv run python -c "import package"`
