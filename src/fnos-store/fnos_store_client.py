"""Client for the public fnOS application catalog."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx2
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from fnos_store_errors import RetryableResponse, StoreError
from fnos_store_package import decrypt_stream, derive_key, ensure_tar_end, is_ustar, write_fpk
from fnos_store_protocol import (
    DEFAULT_BASE_URL,
    DEFAULT_LIVEUPDATE_URL,
    MACHINE_ID,
    PLATFORMS,
    compact,
    endpoint,
    liveupdate_endpoint,
    parse_trim_version,
    request_headers,
    safe_output_name,
    user_app,
)


class StoreClient:
    """Access the public store while keeping package mechanics internal."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        liveupdate_url: str = DEFAULT_LIVEUPDATE_URL,
        timeout: float = 20.0,
        retries: int = 2,
        machine_id: str = MACHINE_ID,
        proxy: str | None = None,
    ) -> None:
        if timeout <= 0:
            raise StoreError("invalid_params", "timeout must be greater than zero.")
        if retries < 0:
            raise StoreError("invalid_params", "retries must not be negative.")
        if not machine_id or len(machine_id) != 40 or any(char not in "0123456789abcdef" for char in machine_id.lower()):
            raise StoreError("invalid_params", "machine-id must be 40 hexadecimal characters.")
        self.base_url = base_url.rstrip("/")
        self.liveupdate_url = liveupdate_url.rstrip("/") + "/"
        self.timeout = timeout
        self.retries = retries
        self.machine_id = machine_id.lower()
        self.http = httpx2.Client(
            timeout=httpx2.Timeout(timeout),
            verify=True,
            trust_env=True,
            proxy=proxy,
            follow_redirects=False,
            headers={"User-Agent": "fnos-store/1.0"},
        )

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> "StoreClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def query(
        self,
        app_name: str,
        *,
        platform: str = "x86",
        os_version: str | None = None,
        language: str = "zh-CN",
    ) -> dict[str, Any]:
        found = self._lookup(app_name, platform=platform, os_version=os_version, language=language)
        selected = found["selected"]
        return compact({
            "appName": selected.get("appName"),
            "name": selected.get("displayName"),
            "description": selected.get("description"),
            "maintainer": selected.get("maintainer"),
            "maintainerUrl": selected.get("maintainerUrl"),
            "distributor": selected.get("distributor"),
            "icon": selected.get("icon"),
            "version": selected.get("version"),
            "versionId": selected.get("versionID"),
            "source": selected.get("channel"),
            "platform": selected.get("platform"),
            "osMinVersion": selected.get("osMinVersion"),
            "osMaxVersion": selected.get("osMaxVersion"),
        })

    def download(
        self,
        app_name: str,
        destination: str | Path | None = None,
        *,
        platform: str = "x86",
        os_version: str | None = None,
        language: str = "zh-CN",
        force: bool = False,
    ) -> dict[str, Any]:
        found = self._lookup(app_name, platform=platform, os_version=os_version, language=language, include_package=True)
        selected = found["selected"]
        link = found.get("link")
        encrypt_block = found.get("encrypt_block")
        if not link or not encrypt_block or not selected.get("version"):
            raise StoreError("no_download", "No downloadable package is available for this app.")

        target = Path(destination or safe_output_name(selected["appName"], selected.get("version")))
        target_existed = target.exists()
        if target.is_dir():
            raise StoreError("invalid_params", "output is a directory.")
        if target_existed and not force:
            raise StoreError("invalid_params", "output already exists; pass --force to replace it.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StoreError("invalid_params", f"cannot create output directory: {exc}") from exc

        decrypted_path: Path | None = None
        key = derive_key(selected["appName"], selected["version"], encrypt_block)
        digest = hashlib.md5()
        encrypted_size = 0

        try:
            try:
                descriptor, name = tempfile.mkstemp(
                    prefix=f".{target.name}.",
                    suffix=".tar.part",
                    dir=target.parent,
                )
                os.close(descriptor)
                decrypted_path = Path(name)
                with self.http.stream("GET", link, follow_redirects=False) as response:
                    self._check_download_response(response)
                    content_length = response.headers.get("Content-Length")
                    if content_length and content_length.isdigit() and found.get("file_size") is not None:
                        if int(content_length) != int(found["file_size"]):
                            raise StoreError("decrypt_failed", "The downloaded package is incomplete.")

                    def encrypted_chunks():
                        nonlocal encrypted_size
                        for chunk in response.iter_bytes(65536):
                            digest.update(chunk)
                            encrypted_size += len(chunk)
                            yield chunk

                    decrypt_stream(encrypted_chunks(), decrypted_path, key)
            except StoreError:
                raise
            except httpx2.TimeoutException as exc:
                raise StoreError("timeout", "The package download timed out.", retryable=True) from exc
            except httpx2.ConnectError as exc:
                if any(word in str(exc).lower() for word in ("certificate", "tls", "ssl")):
                    raise StoreError("tls_error", "TLS certificate verification failed.") from exc
                raise StoreError("http_error", "The package download could not connect.", retryable=True) from exc
            except httpx2.RequestError as exc:
                raise StoreError("http_error", "The package download failed.", retryable=True) from exc
            except OSError as exc:
                raise StoreError("invalid_params", f"cannot write temporary package: {exc}") from exc

            try:
                expected_size = found.get("file_size")
                if expected_size is not None and encrypted_size != int(expected_size):
                    raise StoreError("decrypt_failed", "The downloaded package is incomplete.")
                expected_checksum = found.get("checksum")
                if expected_checksum and digest.hexdigest().lower() != str(expected_checksum).lower():
                    raise StoreError("decrypt_failed", "The downloaded package changed during transfer.")
                with decrypted_path.open("rb") as source:
                    prefix = source.read(512)
                if not is_ustar(prefix):
                    raise StoreError("decrypt_failed", "The downloaded package could not be opened.")
                ensure_tar_end(decrypted_path)
                write_fpk(decrypted_path, target)
            except StoreError:
                raise
            except OSError as exc:
                raise StoreError("invalid_params", f"cannot finalize output: {exc}") from exc
        finally:
            if decrypted_path is not None:
                decrypted_path.unlink(missing_ok=True)

        return compact({
            "appName": selected.get("appName"),
            "name": selected.get("displayName"),
            "version": selected.get("version"),
            "versionId": selected.get("versionID"),
            "platform": selected.get("platform"),
            "file": str(target),
        })

    def list_apps(
        self,
        *,
        platform: str = "x86",
        os_version: str | None = None,
        language: str = "zh-CN",
        source: str | None = None,
        tag: str | None = None,
        latest: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._validate_platform(platform)
        if limit is not None and limit < 0:
            raise StoreError("invalid_params", "limit must not be negative.")
        version = self._resolve_os_version(platform, os_version)
        path = "/app/latest-release" if latest else "/app/list"
        method = "GET" if latest else "POST"
        envelope = self._catalog_request(method, path, {"language": language}, platform=platform, os_version=version)
        self._raise_for_envelope(envelope)
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        apps = [user_app(item, platform=platform) for item in data.get("list", []) if isinstance(item, dict)]
        filtered = [item for item in apps if self._source_matches(item, source) and self._tag_matches(item, tag)]
        return filtered if limit is None else filtered[:limit]

    def search_apps(self, text: str, **kwargs: Any) -> list[dict[str, Any]]:
        query = str(text or "").strip()
        if not query:
            raise StoreError("invalid_params", "query must not be empty.")
        limit = kwargs.pop("limit", None)
        apps = self.list_apps(limit=None, **kwargs)
        words = query.casefold().split()
        matches = [item for item in apps if all(word in self._search_text(item) for word in words)]
        return matches if limit is None else matches[:limit]

    def _lookup(
        self,
        app_name: str,
        *,
        platform: str,
        os_version: str | None,
        language: str,
        include_package: bool = False,
    ) -> dict[str, Any]:
        app_name = str(app_name or "").strip()
        if not app_name or any(char.isspace() for char in app_name):
            raise StoreError("invalid_params", "appName must be a non-empty exact package name.")
        self._validate_platform(platform)
        if not language:
            raise StoreError("invalid_params", "language must not be empty.")

        version = self._resolve_os_version(platform, os_version)
        envelope = self._catalog_request(
            "GET",
            "/app/detail",
            {"appName": app_name, "language": language},
            platform=platform,
            os_version=version,
        )
        code = envelope.get("code")
        if code == -6:
            raise StoreError("not_found", f"No app matches appName {app_name!r}.", upstream_code=code)
        if code == -7:
            raise StoreError("not_available", "No package matches the selected platform and fnOS version.", upstream_code=code)
        if code == -1:
            raise StoreError("invalid_params", envelope.get("msg") or "The store rejected the request parameters.", upstream_code=code)
        if code != 0:
            raise StoreError("http_error", envelope.get("msg") or "The store returned an unknown response code.", upstream_code=code)

        selected = self._candidate(app_name, platform, envelope)
        if not selected["exactMatch"]:
            raise StoreError("not_found", f"The store did not return an exact appName match for {app_name!r}.")

        apply = None
        link = None
        encrypt_block = None
        checksum = None
        file_size = None
        package_name = None
        if include_package and selected.get("appId") is not None and selected.get("version"):
            apply = self._catalog_request(
                "POST",
                "/app/apply",
                {
                    "appName": selected["appName"],
                    "version": selected["version"],
                    "appId": selected["appId"],
                    "language": language,
                },
                platform=platform,
                os_version=version,
            )
            data = apply.get("data") if isinstance(apply.get("data"), dict) else {}
            if apply.get("code") == 0:
                raw_link = data.get("downloadLink")
                if isinstance(raw_link, str) and raw_link.startswith("https://"):
                    link = raw_link
                encrypt_block = data.get("encryptBlock") or None
                checksum = data.get("checkSum") or None
                file_size = data.get("fileSize")
                package_name = data.get("package")

        return {
            "selected": selected,
            "platform": platform,
            "os_version": version,
            "language": language,
            "apply": apply,
            "link": link,
            "encrypt_block": encrypt_block,
            "checksum": checksum,
            "file_size": file_size,
            "package": package_name,
        }

    def _candidate(self, requested: str, platform: str, envelope: dict[str, Any]) -> dict[str, Any]:
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        app_id = data.get("appId")
        actual_name = data.get("appName")
        return {
            "platform": platform,
            "exactMatch": actual_name == requested,
            "appName": actual_name,
            "displayName": data.get("displayName"),
            "description": data.get("desc"),
            "maintainer": data.get("maintainer"),
            "maintainerUrl": data.get("maintainerUrl"),
            "distributor": data.get("distributor"),
            "icon": data.get("icon"),
            "version": data.get("lastVersion"),
            "versionID": data.get("lastVersionId"),
            "appId": app_id,
            "channel": data.get("source"),
            "osMinVersion": data.get("osMinVersion"),
            "osMaxVersion": data.get("osMaxVersion"),
        }

    def _catalog_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        *,
        platform: str,
        os_version: str,
    ) -> dict[str, Any]:
        headers = request_headers(platform=platform, os_version=os_version, machine_id=self.machine_id)
        response = self._request(method, endpoint(self.base_url, path), json_body=body, headers=headers)
        status = response.status_code
        try:
            try:
                envelope = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise StoreError("http_error", "The store did not return JSON.", http_status=status) from exc
            if not isinstance(envelope, dict) or "code" not in envelope:
                raise StoreError("http_error", "The store JSON has no response code.", http_status=status)
            return envelope
        finally:
            response.close()

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx2.Response:
        retry = retry_if_exception_type((RetryableResponse, httpx2.RequestError))
        attempts = Retrying(
            stop=stop_after_attempt(self.retries + 1),
            wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
            retry=retry,
            reraise=True,
        )

        def send() -> httpx2.Response:
            response = self.http.request(method, url, json=json_body, headers=headers)
            if response.status_code == 429 or response.status_code >= 500:
                response.close()
                raise RetryableResponse(response)
            return response

        try:
            response = attempts(send)
        except RetryableResponse as exc:
            status = exc.response.status_code
            if status == 429:
                raise StoreError("rate_limited", "The store rate limit was reached.", http_status=status, retryable=True) from exc
            raise StoreError("http_error", f"The store returned HTTP {status}.", http_status=status, retryable=True) from exc
        except httpx2.TimeoutException as exc:
            raise StoreError("timeout", "The store request timed out.", retryable=True) from exc
        except httpx2.ConnectError as exc:
            text = str(exc).lower()
            if any(word in text for word in ("certificate", "tls", "ssl")):
                raise StoreError("tls_error", "TLS certificate verification failed.") from exc
            raise StoreError("http_error", "The store request could not connect.", retryable=True) from exc
        except httpx2.RequestError as exc:
            raise StoreError("http_error", "The store request failed.", retryable=True) from exc

        if response.status_code in (401, 403):
            response.close()
            raise StoreError("auth_failed", "The store rejected the request.", http_status=response.status_code)
        if response.status_code >= 400:
            status = response.status_code
            response.close()
            raise StoreError("http_error", f"The store returned HTTP {status}.", http_status=status)
        return response

    def _resolve_os_version(self, platform: str, explicit: str | None) -> str:
        if explicit:
            return str(explicit)
        response = self._request(
            "GET",
            liveupdate_endpoint(self.liveupdate_url, platform),
            headers={"Accept": "application/json", "User-Agent": "fnos-store/1.0"},
        )
        try:
            version = parse_trim_version(response.content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise StoreError("http_error", "The update index has no trim package version.", http_status=response.status_code) from exc
        finally:
            response.close()
        return version

    @staticmethod
    def _raise_for_envelope(envelope: dict[str, Any]) -> None:
        code = envelope.get("code")
        if code != 0:
            if code in (-1, -6, -7):
                names = {-1: ("invalid_params", "The store rejected the request parameters."), -6: ("not_found", "No app matches this appName."), -7: ("not_available", "No package matches the selected platform and fnOS version.")}
                error_code, message = names[code]
            else:
                error_code, message = "http_error", "The store returned an unknown response code."
            raise StoreError(error_code, envelope.get("msg") or message, upstream_code=code)

    @staticmethod
    def _validate_platform(platform: str) -> None:
        if platform not in PLATFORMS:
            raise StoreError("invalid_params", "platform must be x86 or arm.")

    @staticmethod
    def _source_matches(item: dict[str, Any], wanted: str | None) -> bool:
        return not wanted or str(item.get("source") or "").casefold() == wanted.strip().casefold()

    @staticmethod
    def _tag_matches(item: dict[str, Any], wanted: str | None) -> bool:
        if not wanted:
            return True
        return wanted.strip().casefold() in {str(tag).casefold() for tag in item.get("tags", [])}

    @staticmethod
    def _search_text(item: dict[str, Any]) -> str:
        return " ".join(
            [str(item.get("appName") or ""), str(item.get("name") or ""), str(item.get("source") or ""), *map(str, item.get("tags") or [])]
        ).casefold()

    @staticmethod
    def _check_download_response(response: httpx2.Response) -> None:
        if 300 <= response.status_code < 400:
            raise StoreError("http_error", "The package source redirected unexpectedly.", http_status=response.status_code)
        if response.status_code >= 400:
            raise StoreError("http_error", f"The package source returned HTTP {response.status_code}.", http_status=response.status_code)
