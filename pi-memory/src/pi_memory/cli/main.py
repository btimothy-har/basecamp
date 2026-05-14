"""Command-line entry point for pi-memory."""

import click
import uvicorn

from pi_memory.constants import DEFAULT_HOST, DEFAULT_PORT, SERVICE_NAME
from pi_memory.server import ServerAlreadyRunningError, ServerState, create_app


@click.group()
def main() -> None:
    """Pi memory service."""


@main.command()
@click.option(
    "--host",
    default=DEFAULT_HOST,
    show_default=True,
    help="Host interface to bind. Defaults to localhost for local Pi sessions.",
)
@click.option(
    "--port",
    default=DEFAULT_PORT,
    show_default=True,
    type=click.IntRange(1024, 65535),
    help="TCP port to bind.",
)
def serve(host: str, port: int) -> None:
    """Run the local Pi memory service."""
    state = ServerState()

    try:
        with state.register(host=host, port=port) as metadata:
            app = create_app(
                host=host,
                port=port,
                memory_dir=state.memory_dir,
                started_at=metadata.started_at_datetime,
            )
            uvicorn.run(app, host=host, port=port)
    except ServerAlreadyRunningError as error:
        raise click.ClickException(str(error)) from error

    click.echo(f"{SERVICE_NAME} stopped")
