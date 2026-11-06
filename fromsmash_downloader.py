"""
FromSmash downloader using Selenium WebDriver (Chrome, Windows-friendly).

Usage:
    python fromsmash_downloader.py "https://fromsmash.com/XXXXXXXX"
    python fromsmash_downloader.py "https://fromsmash.com/XXXXXXXX" -o "C:\\Users\\you\\Downloads\\Smash"
    python fromsmash_downloader.py "https://fromsmash.com/XXXXXXXX" --headless

Install:
    pip install selenium webdriver-manager
"""

import argparse
import os
import sys

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

PAGE_TIMEOUT = 40       # seconds to wait for the page / JS to render
BUTTON_TIMEOUT = 40     # seconds to wait for the download button to appear
DOWNLOAD_TIMEOUT = 3600  # seconds to wait for the download to finish (large files)

UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = "abcdefghijklmnopqrstuvwxyz"


def _text_contains(tag, word):
    """XPath: case-insensitive 'contains' match on the visible text of a tag."""
    return (
        f"//{tag}[contains(translate(normalize-space(.), '{UPPER}', '{LOWER}'), '{word}')]"
    )


# Locators tried (in order) to find the download button.
# FromSmash renders its UI with JavaScript, so we search by visible text.
BUTTON_LOCATORS = [
    (By.XPATH, _text_contains("button", "download")),
    (By.XPATH, _text_contains("button", "get files")),
    (By.XPATH, _text_contains("button", "télécharger")),
    (By.XPATH, _text_contains("a", "download")),
    (By.XPATH, _text_contains("a", "get files")),
    (By.XPATH, "//*[@role='button'][contains(translate(normalize-space(.), "
               f"'{UPPER}', '{LOWER}'), 'download')]"),
    (By.CSS_SELECTOR, "button[class*='download' i], a[class*='download' i]"),
]


def setup_driver(download_dir, headless=False):
    """Create a Chrome driver that downloads automatically into download_dir."""
    options = Options()

    prefs = {
        "download.default_directory": download_dir,   # where files are saved
        "download.prompt_for_download": False,        # no "Save as" dialog
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        # allow the site to download multiple files without asking
        "profile.default_content_setting_values.automatic_downloads": 1,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    options.add_argument("--start-maximized")

    if headless:
        options.add_argument("--headless=new")  # visible browser is the default

    # webdriver-manager downloads a ChromeDriver matching your Chrome version
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def wait_for_page_render(driver):
    """Wait until the document is loaded AND the JS app has rendered some UI."""
    WebDriverWait(driver, PAGE_TIMEOUT).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    # FromSmash is a single-page app: wait for buttons/links to actually appear
    WebDriverWait(driver, PAGE_TIMEOUT).until(
        lambda d: len(d.find_elements(By.CSS_SELECTOR, "button, a, [role='button']")) > 0
    )


def find_download_button(driver):
    """Wait until any known download-button locator matches a visible, enabled element."""

    def _any_button(d):
        for by, selector in BUTTON_LOCATORS:
            for el in d.find_elements(by, selector):
                try:
                    if el.is_displayed() and el.is_enabled():
                        return el
                except WebDriverException:
                    continue  # element went stale while the page re-rendered
        return False

    return WebDriverWait(driver, BUTTON_TIMEOUT, poll_frequency=0.5).until(_any_button)


def click_button(driver, button):
    """Scroll to the button and click it (real click first, JS click as fallback)."""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
    try:
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable(button))
        button.click()
    except WebDriverException:
        driver.execute_script("arguments[0].click();", button)


def list_files(folder):
    return set(os.listdir(folder))


def wait_for_download(folder, before):
    """
    Wait until a new file appears in `folder` and no Chrome temp files remain.
    Uses WebDriverWait with a plain object, so no time.sleep is needed.
    """

    def _finished(_):
        current = list_files(folder)
        new_files = current - before
        in_progress = [f for f in current if f.endswith((".crdownload", ".tmp"))]
        return bool(new_files) and not in_progress and sorted(new_files)

    # WebDriverWait only needs an object to pass to the callback
    return WebDriverWait(object(), DOWNLOAD_TIMEOUT, poll_frequency=1).until(_finished)


def download(url, download_dir, headless=False):
    os.makedirs(download_dir, exist_ok=True)
    driver = None
    try:
        print("[1/5] Starting Chrome...")
        driver = setup_driver(download_dir, headless)

        print(f"[2/5] Opening {url}")
        driver.get(url)

        print("[3/5] Waiting for the page to render...")
        wait_for_page_render(driver)

        print("[4/5] Looking for the Download / Get files button...")
        button = find_download_button(driver)
        print(f"      Found: '{button.text.strip() or button.tag_name}'")

        before = list_files(download_dir)
        click_button(driver, button)  # download starts only after this click
        print("      Button clicked.")

        print("[5/5] Waiting for the download to finish...")
        files = wait_for_download(download_dir, before)
        print("\nDownload complete:")
        for name in files:
            print(f"  - {os.path.join(download_dir, name)}")
        return True

    except TimeoutException:
        print("\nERROR: Timed out (page didn't render, button not found, or download "
              "didn't finish). Check the link is valid and not expired.")
        if driver:
            shot = os.path.join(download_dir, "debug_screenshot.png")
            driver.save_screenshot(shot)
            print(f"Saved screenshot for debugging: {shot}")
        return False
    except WebDriverException as e:
        print(f"\nERROR: Browser/driver problem: {e.msg if hasattr(e, 'msg') else e}")
        return False
    finally:
        if driver:
            driver.quit()


def main():
    parser = argparse.ArgumentParser(description="Download files from a FromSmash link.")
    parser.add_argument("url", nargs="?", help="FromSmash download page URL")
    parser.add_argument("-o", "--output",
                        default=os.path.join(os.path.expanduser("~"), "Downloads", "FromSmash"),
                        help="Download folder (default: Downloads\\FromSmash)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a window")
    args = parser.parse_args()

    url = args.url or input("Enter FromSmash download URL: ").strip()
    if not url.startswith(("http://", "https://")):
        print("ERROR: URL must start with http:// or https://")
        sys.exit(1)
    if "fromsmash.com/" not in url or url.rstrip("/").endswith("fromsmash.com"):
        print("ERROR: Please give the full transfer link (e.g. https://fromsmash.com/AbCdEf), "
              "not the homepage.")
        sys.exit(1)

    sys.exit(0 if download(url, args.output, args.headless) else 1)


if __name__ == "__main__":
    main()
