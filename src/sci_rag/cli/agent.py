"""Existing CLI tools provide the Agent adapter; no new Agent atomic tools."""

import json
import sys

import typer

app = typer.Typer(help="Invoke the local Agent memory adapter.", no_args_is_help=True)


@app.command("call")
def call(operation: str) -> None:
    """Read a JSON payload on stdin and return the local operation result."""
    from sci_rag.agent_backend import agent_operation
    from sci_rag.cli.main import run_async

    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            raise ValueError("object_required")
        result = run_async(agent_operation(operation, payload))
    except ValueError:
        typer.echo(json.dumps({"status": "failed", "error_code": "invalid_agent_request"}))
        raise typer.Exit(1) from None
    typer.echo(json.dumps(result, ensure_ascii=False))
    raise typer.Exit(int(result.get("exit_code", 0)))
