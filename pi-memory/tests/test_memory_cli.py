import socket
from collections.abc import Iterator
from contextlib import contextmanager

import pi_memory.cli.main as cli_module
from click.testing import CliRunner
from pi_memory.server import ServerState


@contextmanager
def occupied_tcp_port(host: str) -> Iterator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        listener.listen()
        yield listener.getsockname()[1]


def test_serve_reports_occupied_port_and_cleans_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "ServerState", lambda: ServerState(memory_dir=tmp_path))
    runner = CliRunner()

    with occupied_tcp_port("127.0.0.1") as port:
        result = runner.invoke(
            cli_module.main,
            ["serve", "--host", "127.0.0.1", "--port", str(port)],
        )

    state = ServerState(memory_dir=tmp_path)
    assert result.exit_code == 1
    assert "Error: pi-memory cannot start at http://127.0.0.1:" in result.output
    assert "the port is already in use by another process" in result.output
    assert not state.lock_path.exists()
    assert not state.metadata_path.exists()
