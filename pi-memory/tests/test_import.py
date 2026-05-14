from click.testing import CliRunner
from pi_memory import __version__
from pi_memory.cli.main import main


def test_package_imports() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_resolves() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "Pi memory service placeholder." in result.output
