"""User-facing JSON CLI for the fnOS store client."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import typer

from fnos_store_client import StoreClient
from fnos_store_errors import StoreError
from fnos_store_protocol import DEFAULT_BASE_URL, DEFAULT_LIVEUPDATE_URL, MACHINE_ID

app = typer.Typer(
    name="fnos-store",
    help="Query the official fnOS store, or save available app packages.",
    no_args_is_help=True,
    add_completion=False,
)


def _print(value: Any) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def _run(
    action: Callable[[StoreClient], Any],
    *,
    base_url: str,
    liveupdate_url: str,
    timeout: float,
    retries: int,
    machine_id: str,
    proxy: str | None,
) -> None:
    try:
        with StoreClient(
            base_url=base_url,
            liveupdate_url=liveupdate_url,
            timeout=timeout,
            retries=retries,
            machine_id=machine_id,
            proxy=proxy,
        ) as client:
            _print(action(client))
    except StoreError as error:
        _print(error.to_dict())
        raise typer.Exit(code=error.exit_code)


def _common_options(
    *,
    base_url: str,
    liveupdate_url: str,
    timeout: float,
    retries: int,
    machine_id: str,
    proxy: str | None,
) -> dict[str, Any]:
    return {
        "base_url": base_url,
        "liveupdate_url": liveupdate_url,
        "timeout": timeout,
        "retries": retries,
        "machine_id": machine_id,
        "proxy": proxy,
    }


@app.command()
def query(
    app_name: str = typer.Argument(..., help="Exact appName to match."),
    platform: str = typer.Option("x86", help="Platform: x86 or arm."),
    os_version: str | None = typer.Option(None, "--os-version", help="fnOS version; when omitted, read the official update index."),
    language: str = typer.Option("zh-CN", help="Language used for store responses."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="Store service address."),
    liveupdate_url: str = typer.Option(DEFAULT_LIVEUPDATE_URL, help="System update index address."),
    timeout: float = typer.Option(20.0, min=0.1, help="Request timeout in seconds."),
    retries: int = typer.Option(2, min=0, help="Number of retries for transient errors."),
    machine_id: str = typer.Option(MACHINE_ID, help="40-character hexadecimal trim-machine-id."),
    proxy: str | None = typer.Option(None, help="Explicit proxy; when omitted, read system proxy variables."),
) -> None:
    _run(
        lambda client: client.query(app_name, platform=platform, os_version=os_version, language=language),
        **_common_options(
            base_url=base_url,
            liveupdate_url=liveupdate_url,
            timeout=timeout,
            retries=retries,
            machine_id=machine_id,
            proxy=proxy,
        ),
    )


@app.command()
def download(
    app_name: str = typer.Argument(..., help="Exact appName to match."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Save path; defaults to a name generated from the app name and version."),
    force: bool = typer.Option(False, "--force", help="Allow overwriting an existing file."),
    platform: str = typer.Option("x86", help="Platform: x86 or arm."),
    os_version: str | None = typer.Option(None, "--os-version", help="fnOS version; when omitted, read the official update index."),
    language: str = typer.Option("zh-CN", help="Language used for store responses."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="Store service address."),
    liveupdate_url: str = typer.Option(DEFAULT_LIVEUPDATE_URL, help="System update index address."),
    timeout: float = typer.Option(20.0, min=0.1, help="Request timeout in seconds."),
    retries: int = typer.Option(2, min=0, help="Number of retries for transient errors."),
    machine_id: str = typer.Option(MACHINE_ID, help="40-character hexadecimal trim-machine-id."),
    proxy: str | None = typer.Option(None, help="Explicit proxy; when omitted, read system proxy variables."),
) -> None:
    _run(
        lambda client: client.download(
            app_name,
            output,
            platform=platform,
            os_version=os_version,
            language=language,
            force=force,
        ),
        **_common_options(
            base_url=base_url,
            liveupdate_url=liveupdate_url,
            timeout=timeout,
            retries=retries,
            machine_id=machine_id,
            proxy=proxy,
        ),
    )


def _catalog_options(
    *,
    platform: str,
    os_version: str | None,
    language: str,
    source: str | None,
    tag: str | None,
    latest: bool,
    limit: int | None,
    base_url: str,
    liveupdate_url: str,
    timeout: float,
    retries: int,
    machine_id: str,
    proxy: str | None,
) -> dict[str, Any]:
    return {
        "platform": platform,
        "os_version": os_version,
        "language": language,
        "source": source,
        "tag": tag,
        "latest": latest,
        "limit": limit,
        "base_url": base_url,
        "liveupdate_url": liveupdate_url,
        "timeout": timeout,
        "retries": retries,
        "machine_id": machine_id,
        "proxy": proxy,
    }


def _catalog_client_kwargs(options: dict[str, Any]) -> dict[str, Any]:
    return {key: options[key] for key in ("base_url", "liveupdate_url", "timeout", "retries", "machine_id", "proxy")}


def _run_catalog(options: dict[str, Any], *, search_text: str | None = None) -> None:
    names = ("platform", "os_version", "language", "source", "tag", "latest", "limit")
    arguments = {key: options[key] for key in names if key != "latest" or search_text is None}
    if search_text is None:
        action = lambda client: client.list_apps(**arguments)
    else:
        arguments.pop("latest", None)
        action = lambda client: client.search_apps(search_text, **arguments)
    _run(action, **_catalog_client_kwargs(options))


@app.command(name="list")
def list_command(
    platform: str = typer.Option("x86", help="Platform: x86 or arm."),
    os_version: str | None = typer.Option(None, "--os-version", help="fnOS version; when omitted, read the official update index."),
    language: str = typer.Option("zh-CN", help="Language used for store responses."),
    source: str | None = typer.Option(None, help="Show only one channel, e.g. official or thirdparty."),
    tag: str | None = typer.Option(None, help="Show only apps containing this tag."),
    latest: bool = typer.Option(False, help="Show only newly listed apps."),
    limit: int | None = typer.Option(None, min=0, help="Maximum number of items to output."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="Store service address."),
    liveupdate_url: str = typer.Option(DEFAULT_LIVEUPDATE_URL, help="System update index address."),
    timeout: float = typer.Option(20.0, min=0.1, help="Request timeout in seconds."),
    retries: int = typer.Option(2, min=0, help="Number of retries for transient errors."),
    machine_id: str = typer.Option(MACHINE_ID, help="40-character hexadecimal trim-machine-id."),
    proxy: str | None = typer.Option(None, help="Explicit proxy; when omitted, read system proxy variables."),
) -> None:
    options = _catalog_options(
        platform=platform, os_version=os_version, language=language, source=source, tag=tag,
        latest=latest, limit=limit, base_url=base_url, liveupdate_url=liveupdate_url,
        timeout=timeout, retries=retries, machine_id=machine_id, proxy=proxy,
    )
    _run_catalog(options)


@app.command()
def search(
    text: str = typer.Argument(..., help="Text to search for in the package name, name, channel, and tags."),
    platform: str = typer.Option("x86", help="Platform: x86 or arm."),
    os_version: str | None = typer.Option(None, "--os-version", help="fnOS version; when omitted, read the official update index."),
    language: str = typer.Option("zh-CN", help="Language used for store responses."),
    source: str | None = typer.Option(None, help="Show only one channel, e.g. official or thirdparty."),
    tag: str | None = typer.Option(None, help="Show only apps containing this tag."),
    limit: int | None = typer.Option(None, min=0, help="Maximum number of items to output."),
    base_url: str = typer.Option(DEFAULT_BASE_URL, help="Store service address."),
    liveupdate_url: str = typer.Option(DEFAULT_LIVEUPDATE_URL, help="System update index address."),
    timeout: float = typer.Option(20.0, min=0.1, help="Request timeout in seconds."),
    retries: int = typer.Option(2, min=0, help="Number of retries for transient errors."),
    machine_id: str = typer.Option(MACHINE_ID, help="40-character hexadecimal trim-machine-id."),
    proxy: str | None = typer.Option(None, help="Explicit proxy; when omitted, read system proxy variables."),
) -> None:
    options = _catalog_options(
        platform=platform, os_version=os_version, language=language, source=source, tag=tag,
        latest=False, limit=limit, base_url=base_url, liveupdate_url=liveupdate_url,
        timeout=timeout, retries=retries, machine_id=machine_id, proxy=proxy,
    )
    _run_catalog(options, search_text=text)


def main(argv: list[str] | None = None) -> int:
    result = app(args=argv, prog_name="fnos-store", standalone_mode=False)
    return int(result or 0)
