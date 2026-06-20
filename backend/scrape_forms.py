import os
from urllib.parse import urljoin

# Use the operating system's trust store (e.g. macOS Keychain) for TLS so that
# corporate root CAs used for HTTPS inspection are trusted. Without this,
# requests' bundled certificate store rejects intercepted connections with
# "unable to get local issuer certificate".
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Load credentials from .env regardless of the process' current working
# directory. Look next to this file first (backend/.env), then fall back to the
# repo root one level up (the .env actually lives there).
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in (
    os.path.join(_HERE, ".env"),
    os.path.join(os.path.dirname(_HERE), ".env"),
):
    if os.path.exists(_candidate):
        load_dotenv(_candidate)
        break

BASE_URL = "https://lifeinsdata.com"

# The site can be slow, so use a generous, env-tunable timeout and retry
# transient failures (slow reads / 5xx) instead of aborting the whole scrape.
TIMEOUT = int(os.getenv("SCRAPE_TIMEOUT", "45"))
RETRIES = int(os.getenv("SCRAPE_RETRIES", "3"))


def get_headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "Host": "lifeinsdata.com",
        "Sec-Ch-Ua": '"Not-A.Brand";v="24", "Chromium";v="146"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Linux"',
        "Accept-Language": "en-GB,en;q=0.9",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-User": "?1",
        "Sec-Fetch-Dest": "document",
        "Priority": "u=0, i",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Host": "lifeinsdata.com",
            "Sec-Ch-Ua": '"Not-A.Brand";v="24", "Chromium";v="146"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
            "Accept-Language": "en-GB,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:134.0) Gecko/20100101 Firefox/134.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-User": "?1",
            "Sec-Fetch-Dest": "document",
            "Priority": "u=0, i",
        }
    )
    # Retry slow reads / connection drops / 5xx on GET requests (the bulk of the
    # scrape) with exponential backoff so one hiccup doesn't kill the whole run.
    retry = Retry(
        total=RETRIES,
        connect=RETRIES,
        read=RETRIES,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def login(session: requests.Session, username: str | None = None, password: str | None = None) -> bool:
    initial_url = BASE_URL
    session.get(initial_url, headers=get_headers(initial_url), timeout=TIMEOUT)
    print(f"Initialized session with session_id: {session.cookies.get('PHPSESSID')}")

    login_url = f"{BASE_URL}/index.php"
    data = {
        "username": username or os.getenv("ADMIN_USERNAME"),
        "password": password or os.getenv("ADMIN_PASSWORD"),
        "utype": "subadmin",
        "login": "SIGN IN",
    }
    response = session.post(
        login_url,
        headers=get_headers(login_url),
        data=data,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    if "already logged in" in response.text.lower():
        raise RuntimeError(
            "This account is already logged in on lifeinsdata.com. Log out of the "
            "site (in your browser / other session) and try again."
        )
    if "Access time is over or not started" in response.text:
        raise RuntimeError(
            "Login blocked: access time is over or not started for this account."
        )

    # The site sets a PHPSESSID for anonymous visitors too, so a cookie alone is
    # not proof of login. If we land back on the sign-in page, auth failed.
    body = response.text.lower()
    on_login_page = "auth-img-bg" in body or 'name="password"' in body
    if on_login_page:
        return False

    return response.ok and session.cookies.get("PHPSESSID") is not None


def logout(session: requests.Session) -> bool:
    url = f"{BASE_URL}/LO.php"
    response = session.get(url, headers=get_headers(url), timeout=TIMEOUT)
    return response.ok


def get_user_list(session: requests.Session) -> list[str]:
    url = f"{BASE_URL}/entry_list.php"
    response = session.get(url, headers=get_headers(url), timeout=10)
    user_list: list[str] = []
    if response.ok:
        soup = BeautifulSoup(response.content, "html.parser")
        select_element = soup.find("select", id="exampleSelect3")
        if select_element:
            for option in select_element.find_all("option"):
                value = option.get("value")
                if value and value != "selectuser":
                    user_list.append(value)
    return user_list


def get_user_forms(session: requests.Session, user_id: str) -> None:
    url = f"{BASE_URL}/entry_list.php?inq={user_id}&submit="
    response = session.get(url, headers=get_headers(url), timeout=10)
    user_form_links = []
    if response.ok:
        soup = BeautifulSoup(response.content, "html.parser")
        table = soup.find("table", id="sampleTable")
        if table:
            for row in table.find_all("tr"):
                for link in row.find_all(
                    "a", href=lambda x: x and x.startswith("viewform.php?id=")
                ):
                    user_form_links.append(urljoin(BASE_URL, link.get("href")))
            return user_form_links
        else:
            print(f"No forms found for user {user_id}.")
    else:
        print(f"Failed to retrieve forms for user {user_id}: {response.status_code}")


def get_form_details(session: requests.Session, form_url: str) -> dict[str, str]:
    response = session.get(form_url, headers=get_headers(form_url), timeout=10)
    form_details = {}
    if response.ok:
        corrected_response_content = response.text.replace(
            "<td>25</td>\n            <td>Blood Group</td>",
            "<tr><td>25</td>\n            <td>Blood Group</td>",
        )
        soup = BeautifulSoup(corrected_response_content, "html.parser")
        for row in soup.find_all("tr")[1:]:  # Skip the header row
            cells = row.find_all("td")
            if len(cells) >= 3:
                key = cells[1].get_text(strip=True).lower().replace(" ", "_")
                value = cells[2].get_text(strip=True)
                form_details[key] = value
    else:
        print(
            f"Failed to retrieve form details from {form_url}: {response.status_code}"
        )
    return form_details


def scrape_all_forms(username: str | None = None, password: str | None = None) -> list[dict]:
    """Log in, scrape every user's form details, log out, return the records.

    Credentials are taken from the username/password arguments when provided;
    otherwise they fall back to ADMIN_USERNAME / ADMIN_PASSWORD in the .env.
    Raises RuntimeError if the login fails."""
    with create_session() as session:
        if not login(session, username=username, password=password):
            raise RuntimeError(
                "Login failed - check username / password"
            )
        try:
            details: list[dict] = []
            for user_id in get_user_list(session):
                forms = get_user_forms(session, user_id) or []
                for form_link in forms:
                    details.append(get_form_details(session, form_link))
            return details
        finally:
            logout(session)


if __name__ == "__main__":
    import json

    records = scrape_all_forms()
    with open("all_user_forms_details.json", "w") as f:
        json.dump(records, f, indent=4)
    print(f"Scraped {len(records)} forms -> all_user_forms_details.json")
