"""CLI entry point for polar-flow-server."""

import typer
import uvicorn

from polar_flow_server import __version__
from polar_flow_server.core.config import settings

app = typer.Typer(
    name="polar-flow-server",
    help="Self-hosted health analytics server for Polar devices",
    no_args_is_help=True,
)


@app.command()
def serve(
    host: str = typer.Option(None, help="Host to bind to (overrides config)"),
    port: int = typer.Option(None, help="Port to bind to (overrides config)"),
    reload: bool = typer.Option(False, help="Enable auto-reload for development"),
) -> None:
    """Start the API server.

    Example:
        polar-flow-server serve
        polar-flow-server serve --host 0.0.0.0 --port 8080 --reload
    """
    uvicorn.run(
        "polar_flow_server.app:app",
        host=host or settings.api_host,
        port=port or settings.api_port,
        reload=reload,
        log_level=settings.log_level.lower(),
    )


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo(f"polar-flow-server v{__version__}")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
