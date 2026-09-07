from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


_DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_SESSION_FILE = Path(__file__).resolve().parent.parent / ".mm-session"


def _parse_session_file(value: str | None) -> Path | None:
    if value is None:
        return DEFAULT_SESSION_FILE
    stripped = value.strip()
    if not stripped:
        return None
    path = Path(stripped).expanduser()
    if not path.is_absolute():
        return DEFAULT_SESSION_FILE.parent / path
    return path


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or _DOTENV_PATH
    if not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Environment variable {name} is required")
    return value


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_auth_mode(value: str | None) -> str:
    if value is None or not value.strip():
        return "auto"

    normalized = value.strip().lower()
    if normalized in {"auto", "token", "browser", "login", "playwright"}:
        return normalized
    raise ValueError("MATTERMOST_AUTH_MODE must be one of: auto, token, browser, login, playwright")


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value.strip())


@dataclass(frozen=True)
class AuthSettings:
    mode: str
    token: str | None = None
    session_token: str | None = None
    csrf_token: str | None = None
    user_id: str | None = None
    login_id: str | None = None
    password: str | None = None
    mfa_token: str | None = None
    sso_auth_url: str | None = None
    playwright_headless: bool = True
    playwright_interactive: bool = False
    playwright_browser: str = "chromium"
    playwright_timeout_ms: int = 300000
    playwright_username_selector: str = 'input[name="username"]'
    playwright_password_selector: str = 'input[name="password"]'
    playwright_submit_selector: str = 'input[name="login"], button[type="submit"], #kc-login'
    playwright_post_login_url_prefix: str | None = None
    playwright_success_selector: str | None = None


@dataclass(frozen=True)
class Settings:
    base_url: str
    auth: AuthSettings
    timeout_seconds: float = 15.0
    verify_ssl: bool = True
    auth_test_only: bool = False
    session_file: Path | None = DEFAULT_SESSION_FILE

    @classmethod
    def from_env(cls) -> "Settings":
        timeout_raw = os.getenv("MATTERMOST_TIMEOUT_SECONDS", "15").strip() or "15"
        auth_mode = _parse_auth_mode(os.getenv("MATTERMOST_AUTH_MODE"))
        token = _optional_env("MATTERMOST_TOKEN")
        session_token = _optional_env("MATTERMOST_MMAUTHTOKEN")
        csrf_token = _optional_env("MATTERMOST_MMCSRF")
        user_id = _optional_env("MATTERMOST_MMUSERID")
        login_id = _optional_env("MATTERMOST_LOGIN_ID")
        password = _optional_env("MATTERMOST_PASSWORD")
        mfa_token = _optional_env("MATTERMOST_MFA_TOKEN")
        sso_auth_url = _optional_env("MATTERMOST_SSO_AUTH_URL")
        playwright_headless = _parse_bool(os.getenv("MATTERMOST_PLAYWRIGHT_HEADLESS"), True)
        playwright_interactive = _parse_bool(os.getenv("MATTERMOST_PLAYWRIGHT_INTERACTIVE"), False)
        playwright_browser = _optional_env("MATTERMOST_PLAYWRIGHT_BROWSER") or "chromium"
        playwright_timeout_ms = _parse_int(os.getenv("MATTERMOST_PLAYWRIGHT_TIMEOUT_MS"), 300000)
        playwright_username_selector = (
            _optional_env("MATTERMOST_PLAYWRIGHT_USERNAME_SELECTOR")
            or 'input[name="username"]'
        )
        playwright_password_selector = (
            _optional_env("MATTERMOST_PLAYWRIGHT_PASSWORD_SELECTOR")
            or 'input[name="password"]'
        )
        playwright_submit_selector = (
            _optional_env("MATTERMOST_PLAYWRIGHT_SUBMIT_SELECTOR")
            or 'input[name="login"], button[type="submit"], #kc-login'
        )
        playwright_post_login_url_prefix = _optional_env("MATTERMOST_PLAYWRIGHT_POST_LOGIN_URL_PREFIX")
        playwright_success_selector = _optional_env("MATTERMOST_PLAYWRIGHT_SUCCESS_SELECTOR")

        if auth_mode == "token":
            if not token:
                raise ValueError("Environment variable MATTERMOST_TOKEN is required for token auth")
            auth = AuthSettings(mode="token", token=token)
        elif auth_mode == "browser":
            if not session_token or not csrf_token:
                raise ValueError(
                    "Environment variables MATTERMOST_MMAUTHTOKEN and MATTERMOST_MMCSRF are required for browser auth"
                )
            auth = AuthSettings(
                mode="browser",
                session_token=session_token,
                csrf_token=csrf_token,
                user_id=user_id,
            )
        elif auth_mode == "login":
            if not login_id or not password:
                raise ValueError(
                    "Environment variables MATTERMOST_LOGIN_ID and MATTERMOST_PASSWORD are required for login auth"
                )
            auth = AuthSettings(
                mode="login",
                login_id=login_id,
                password=password,
                mfa_token=mfa_token,
            )
        elif auth_mode == "playwright":
            if not sso_auth_url:
                raise ValueError("Environment variable MATTERMOST_SSO_AUTH_URL is required for playwright auth")
            if not playwright_interactive and (not login_id or not password):
                raise ValueError(
                    "Environment variables MATTERMOST_LOGIN_ID and MATTERMOST_PASSWORD are required for non-interactive playwright auth"
                )
            auth = AuthSettings(
                mode="playwright",
                sso_auth_url=sso_auth_url,
                login_id=login_id,
                password=password,
                playwright_headless=playwright_headless,
                playwright_interactive=playwright_interactive,
                playwright_browser=playwright_browser,
                playwright_timeout_ms=playwright_timeout_ms,
                playwright_username_selector=playwright_username_selector,
                playwright_password_selector=playwright_password_selector,
                playwright_submit_selector=playwright_submit_selector,
                playwright_post_login_url_prefix=playwright_post_login_url_prefix,
                playwright_success_selector=playwright_success_selector,
            )
        else:
            if token:
                auth = AuthSettings(mode="token", token=token)
            elif session_token and csrf_token:
                auth = AuthSettings(
                    mode="browser",
                    session_token=session_token,
                    csrf_token=csrf_token,
                    user_id=user_id,
                )
            elif login_id and password:
                auth = AuthSettings(
                    mode="login",
                    login_id=login_id,
                    password=password,
                    mfa_token=mfa_token,
                )
            elif sso_auth_url and (playwright_interactive or (login_id and password)):
                auth = AuthSettings(
                    mode="playwright",
                    sso_auth_url=sso_auth_url,
                    login_id=login_id,
                    password=password,
                    playwright_headless=playwright_headless,
                    playwright_interactive=playwright_interactive,
                    playwright_browser=playwright_browser,
                    playwright_timeout_ms=playwright_timeout_ms,
                    playwright_username_selector=playwright_username_selector,
                    playwright_password_selector=playwright_password_selector,
                    playwright_submit_selector=playwright_submit_selector,
                    playwright_post_login_url_prefix=playwright_post_login_url_prefix,
                    playwright_success_selector=playwright_success_selector,
                )
            else:
                raise ValueError(
                    "Provide MATTERMOST_TOKEN, MATTERMOST_MMAUTHTOKEN + MATTERMOST_MMCSRF, MATTERMOST_LOGIN_ID + MATTERMOST_PASSWORD, or MATTERMOST_SSO_AUTH_URL with interactive Playwright or login credentials"
                )

        return cls(
            base_url=_require_env("MATTERMOST_BASE_URL"),
            auth=auth,
            timeout_seconds=float(timeout_raw),
            verify_ssl=_parse_bool(os.getenv("MATTERMOST_VERIFY_SSL"), True),
            auth_test_only=_parse_bool(os.getenv("MATTERMOST_AUTH_TEST_ONLY"), False),
            session_file=_parse_session_file(os.getenv("MATTERMOST_SESSION_FILE")),
        )
