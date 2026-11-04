"""SportLens UI smoke test in a real browser (Playwright, headless Chromium).

  padel/.venv/bin/python scripts/platform_ui_smoke.py --base http://localhost:8080 --shots /tmp/sportlens-shots

Signs up a new user, creates a facility and walks every section of the shell (Overview, Futsal, Padel,
Players), failing on any uncaught page error or failed same-origin request. Saves a screenshot per section.
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--shots", default="")
    ap.add_argument("--dark", action="store_true")
    args = ap.parse_args()
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 860}, color_scheme="dark" if args.dark else "light")
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
        page.on("response", lambda r: r.url.startswith(args.base) and r.status >= 500 and errors.append(f"{r.status} {r.url}"))

        def snap(name: str) -> None:
            if shots:
                page.screenshot(path=str(shots / f"{name}.png"), full_page=True)
            print(f"ok    {name}")

        page.goto(args.base + "/")
        expect(page.get_by_role("button", name="Sign in")).to_be_visible()
        snap("01-login")
        page.get_by_role("button", name="New here? Create an account").click()
        page.get_by_label("Email").fill(f"ui-{secrets.token_hex(4)}@example.com")
        page.get_by_label("Full name").fill("UI Smoke")
        page.get_by_label("Password").fill(secrets.token_urlsafe(12))
        page.get_by_role("button", name="Create account").click()
        expect(page.get_by_role("heading", name="Your facilities")).to_be_visible()
        page.get_by_placeholder("New facility name").fill("Riverside Sports Club")
        page.get_by_role("button", name="Create").click()
        # one facility -> straight into it
        expect(page.get_by_role("heading", name="Overview")).to_be_visible(timeout=15000)
        expect(page.get_by_text("Padel", exact=True).first).to_be_visible()
        snap("02-overview")

        page.get_by_role("link", name="Futsal", exact=True).click()
        expect(page.locator(".sl-futsal")).to_be_visible()
        page.wait_for_load_state("networkidle")
        snap("03-futsal")
        page.get_by_placeholder("Match title").fill("Friday league — Lions v Hawks")
        page.get_by_role("button", name="Create match").click()
        page.get_by_role("link", name="Friday league", exact=False).click()
        page.wait_for_url("**/matches/**")
        expect(page.locator(".sl-futsal")).to_be_visible()
        page.wait_for_load_state("networkidle")
        snap("03b-futsal-match")
        page.goto(page.url.split("/matches/")[0])  # deep link straight into a facility
        expect(page.get_by_role("link", name="Friday league", exact=False)).to_be_visible(timeout=15000)
        snap("03c-overview-with-match")

        page.get_by_role("link", name="Padel", exact=True).click()
        expect(page.locator(".sl-padel")).to_be_visible(timeout=15000)
        page.wait_for_load_state("networkidle")
        snap("04-padel")

        page.get_by_role("link", name="Players", exact=True).click()
        expect(page.get_by_role("heading", name="Players")).to_be_visible()
        page.wait_for_load_state("networkidle")
        snap("05-players")

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("link", name="Overview", exact=True).click()
        expect(page.get_by_role("heading", name="Overview")).to_be_visible()
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        snap("06-overview-mobile")
        if overflow:
            errors.append("horizontal page scroll at 390 px")
        browser.close()

    if errors:
        print("FAIL\n  " + "\n  ".join(errors))
        sys.exit(1)
    print("UI SMOKE PASSED")


if __name__ == "__main__":
    main()
