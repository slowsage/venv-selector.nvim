#!/usr/bin/env -S uv run
# /// script
# dependencies = [
#   "httpx",
#   "cyclopts",
#   "questionary",
#   "invoke",
#   "rich",
# ]
# ///

import httpx
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import questionary
from cyclopts import App
from invoke import run
from rich.console import Console

app = App()
console = Console()


@dataclass(frozen=True)
class ChromeApp:
    """Chrome web application configuration."""
    url: str
    name: str
    wm_class: str
    icon_path: Path
    desktop_path: Path


def normalize_url(url: str) -> str:
    """Ensure URL has https:// prefix."""
    return url if url.startswith("http") else f"https://{url}"


def extract_domain(url: str) -> str:
    """Extract domain name from URL (e.g., 'lichess' from 'lichess.org')."""
    parsed = urlparse(normalize_url(url))
    # Get first part of domain (before first dot)
    domain = (parsed.hostname or "").split(".")[0]
    return domain


def generate_name_variants(domain: str) -> list[str]:
    """Generate capitalization variants for app name."""
    if not domain:
        return []

    return [
        domain.capitalize(),  # Lichess
        domain.lower(),       # lichess
        domain.upper(),       # LICHESS
        domain.title(),       # Lichess (same as capitalize for single word)
    ]


def get_wm_class(url: str) -> str:
    """Generate WM_CLASS for Chrome app (e.g., 'chrome-lichess.org__-Default')."""
    parsed_url = urlparse(normalize_url(url))
    netloc = parsed_url.hostname or ""
    path = parsed_url.path.strip("/").replace("/", "_")
    return f"chrome-{netloc}__{path}-Default"


def download_icon(url: str, icon_path: Path) -> bool:
    """Download favicon for the app. Returns True on success."""
    icon_url = f"https://www.google.com/s2/favicons?domain={url}&sz=256"
    icon_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        response = httpx.get(icon_url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        with open(icon_path, "wb") as f:
            f.write(response.content)
        return True
    except Exception as e:
        console.print(f"[red]✗ Error downloading icon:[/red] {e}")
        return False


def create_desktop_file(app_config: ChromeApp) -> None:
    """Create .desktop file for the Chrome app."""
    desktop_content = (
        f"[Desktop Entry]\n"
        f"Type=Application\n"
        f"Name={app_config.name}\n"
        f"Exec=google-chrome-stable --app={app_config.url}\n"
        f"Icon={app_config.icon_path}\n"
        f"Comment={app_config.name} on Chrome\n"
        f"StartupWMClass={app_config.wm_class}"
    )

    app_config.desktop_path.parent.mkdir(parents=True, exist_ok=True)
    with open(app_config.desktop_path, "w") as f:
        f.write(desktop_content)


def create_chrome_app(url: str, name: str) -> ChromeApp | None:
    """Create a Chrome web app. Returns ChromeApp config on success, None on failure."""
    normalized_url = normalize_url(url)
    wm_class = get_wm_class(normalized_url)
    icon_path = Path.home() / f".local/share/icons/{name}.png"
    desktop_path = Path.home() / f".local/share/applications/{name}.desktop"

    console.print(f"[green]✓[/green] Creating [bold]{name}[/bold] app from [cyan]{normalized_url}[/cyan]")

    # Download icon
    if not download_icon(normalized_url, icon_path):
        return None

    # Create app config
    app_config = ChromeApp(
        url=normalized_url,
        name=name,
        wm_class=wm_class,
        icon_path=icon_path,
        desktop_path=desktop_path,
    )

    # Create desktop file
    create_desktop_file(app_config)

    console.print(f"[green]✓[/green] Created desktop file: [dim]{desktop_path}[/dim]")
    return app_config


def add_to_yadm(paths: list[Path]) -> None:
    """Add files to yadm using invoke."""
    try:
        # Convert Paths to strings and join for command
        path_strs = " ".join(f'"{p}"' for p in paths)
        run(f"yadm add {path_strs}", hide=True)
        console.print("[green]✓[/green] Added to yadm")
    except Exception as e:
        console.print(f"[red]✗[/red] Failed to add to yadm: {e}")


@app.default
def main() -> None:
    """Create a Chrome web app interactively."""
    console.print("[bold cyan]Chrome Web App Creator[/bold cyan]\n")

    # Interactive prompts using questionary
    url = questionary.text("App URL:").ask()
    if not url:
        console.print("[red]✗[/red] URL is required")
        return

    # Generate name variants and let user select
    domain = extract_domain(url)
    variants = generate_name_variants(domain)

    name = questionary.autocomplete(
        "App name:",
        choices=variants,
        default=domain.capitalize(),
    ).ask()

    if not name:
        console.print("[red]✗[/red] Name is required")
        return

    add_yadm = questionary.confirm("Add to yadm?", default=True).ask()

    # Create the Chrome app
    app_config = create_chrome_app(url, name)

    if not app_config:
        console.print("[red]✗[/red] Failed to create app")
        return

    # Add to yadm if confirmed
    if add_yadm:
        add_to_yadm([app_config.desktop_path, app_config.icon_path])
    else:
        console.print()
        console.print("[bold cyan]Manual yadm commands:[/bold cyan]")
        console.print(f'  yadm add "{app_config.desktop_path}" "{app_config.icon_path}"', style="dim")

    console.print()
    console.print("[bold yellow]Undo:[/bold yellow]")
    console.print(f'  rm "{app_config.desktop_path}" "{app_config.icon_path}"', style="dim")


if __name__ == "__main__":
    app()
