import re
import html
import xml.etree.ElementTree as ET

from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://eeb.org"
LIBRARY_URL = "https://eeb.org/en/library/"
OUTPUT_FILE = "eeb-library.xml"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EEB-RSS/1.0)"
    )
}


def get_page(page_number=1):
    """
    Download an EEB library page.

    EEB uses a paginated/filterable library.
    """

    if page_number == 1:
        url = LIBRARY_URL
    else:
        url = f"{LIBRARY_URL}page/{page_number}/"

    print(f"Fetching: {url}")

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return BeautifulSoup(
        response.text,
        "html.parser",
    )


def parse_date(text):
    """
    Convert EEB dates such as:

        5 August 2026

    into a Python datetime.
    """

    match = re.search(
        r"\d{1,2}\s+"
        r"(January|February|March|April|May|June|July|"
        r"August|September|October|November|December)"
        r"\s+\d{4}",
        text,
    )

    if not match:
        return None

    return datetime.strptime(
        match.group(0),
        "%d %B %Y",
    ).replace(
        tzinfo=timezone.utc
    )


def extract_items(soup):
    """
    Extract EEB library entries.
    """

    items = {}

    # Individual library documents currently live under:
    #
    # /en/library/some-document-name/
    #
    for link in soup.find_all("a", href=True):

        href = urljoin(
            BASE_URL,
            link["href"],
        )

        if not re.match(
            r"^https://eeb\.org/en/library/[^/?#]+/?$",
            href,
        ):
            continue

        title = link.get_text(
            " ",
            strip=True,
        )

        if not title:
            continue

        # Ignore the library itself.
        if href.rstrip("/") == LIBRARY_URL.rstrip("/"):
            continue

        # Find a parent containing the publication metadata.
        container = link

        for _ in range(10):

            container = container.parent

            if container is None:
                break

            text = container.get_text(
                " ",
                strip=True,
            )

            if "Published:" in text:
                break

        if container is None:
            continue

        text = container.get_text(
            " ",
            strip=True,
        )

        # Extract publication date.
        published_match = re.search(
            r"Published:\s*"
            r"(\d{1,2}\s+"
            r"(?:January|February|March|April|May|June|July|"
            r"August|September|October|November|December)"
            r"\s+\d{4})",
            text,
        )

        if not published_match:
            continue

        published = datetime.strptime(
            published_match.group(1),
            "%d %B %Y",
        ).replace(
            tzinfo=timezone.utc
        )

        # Categories
        categories = ""

        category_match = re.search(
            r"Categories:\s*(.*?)\s+Types:",
            text,
        )

        if category_match:
            categories = category_match.group(1).strip()

        # Types
        types = ""

        type_match = re.search(
            r"Types:\s*(.*?)\s+Published:",
            text,
        )

        if type_match:
            types = type_match.group(1).strip()

        # Find a download link if one exists.
        download_url = None

        for a in container.find_all(
            "a",
            href=True,
        ):

            href2 = urljoin(
                BASE_URL,
                a["href"],
            )

            if (
                ".pdf" in href2.lower()
                or
                "Download File" in a.get_text(
                    " ",
                    strip=True,
                )
            ):
                download_url = href2
                break

        # Use metadata as the RSS description.
        description_parts = []

        if types:
            description_parts.append(
                f"Type: {types}"
            )

        if categories:
            description_parts.append(
                f"Categories: {categories}"
            )

        if download_url:
            description_parts.append(
                f"Download: {download_url}"
            )

        description = " | ".join(
            description_parts
        )

        items[href] = {
            "title": title,
            "url": href,
            "published": published,
            "description": description,
            "categories": categories,
            "types": types,
            "download_url": download_url,
        }

    return list(items.values())


def collect_items():
    """
    Crawl the EEB library until no new documents
    are discovered.
    """

    items = {}

    # Safety limit.
    for page in range(1, 101):

        soup = get_page(page)

        page_items = extract_items(soup)

        print(
            f"Found {len(page_items)} documents"
        )

        if not page_items:
            break

        previous_count = len(items)

        for item in page_items:
            items[item["url"]] = item

        if len(items) == previous_count:
            print(
                "No new documents found. Stopping."
            )
            break

    return sorted(
        items.values(),
        key=lambda x: x["published"],
        reverse=True,
    )


def create_rss(items):

    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
        },
    )

    channel = ET.SubElement(
        rss,
        "channel",
    )

    ET.SubElement(
        channel,
        "title",
    ).text = "European Environmental Bureau — Library"

    ET.SubElement(
        channel,
        "link",
    ).text = LIBRARY_URL

    ET.SubElement(
        channel,
        "description",
    ).text = (
        "Latest documents and publications "
        "from the European Environmental Bureau"
    )

    ET.SubElement(
        channel,
        "language",
    ).text = "en"

    ET.SubElement(
        channel,
        "lastBuildDate",
    ).text = format_datetime(
        datetime.now(timezone.utc)
    )

    for item_data in items:

        item = ET.SubElement(
            channel,
            "item",
        )

        ET.SubElement(
            item,
            "title",
        ).text = item_data["title"]

        ET.SubElement(
            item,
            "link",
        ).text = item_data["url"]

        ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "true"
            },
        ).text = item_data["url"]

        ET.SubElement(
            item,
            "pubDate",
        ).text = format_datetime(
            item_data["published"]
        )

        description = html.escape(
            item_data["description"]
        )

        ET.SubElement(
            item,
            "description",
        ).text = description

        if item_data["types"]:
            ET.SubElement(
                item,
                "category",
            ).text = item_data["types"]

    return ET.ElementTree(rss)


def main():

    documents = collect_items()

    print()
    print(
        f"Total documents found: {len(documents)}"
    )

    if not documents:
        raise RuntimeError(
            "No EEB documents were found. "
            "The website structure may have changed."
        )

    rss = create_rss(documents)

    ET.indent(
        rss,
        space="  ",
    )

    rss.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
    )

    print(
        f"RSS feed written to: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
