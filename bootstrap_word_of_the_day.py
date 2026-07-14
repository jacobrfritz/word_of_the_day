import csv
import email.utils
import os

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass
from bs4 import BeautifulSoup


def fetch_new_words(filename="word_of_the_day_embeddings.csv"):
    """Fetches new Word of the Day entries from the podcast RSS feed,

    stopping when it encounters entries that are already in the existing CSV.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    existing_dates = set()
    existing_rows = []

    # 1. Load existing dates from CSV if the file exists
    if os.path.exists(filename):
        try:
            with open(filename, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                # Check that the required headers are present
                if reader.fieldnames and "date" in reader.fieldnames:
                    for row in reader:
                        date_val = row.get("date")
                        word_val = row.get("word")
                        if date_val and word_val:
                            existing_dates.add(date_val.strip())
                            existing_rows.append(
                                {"word": word_val.strip(), "date": date_val.strip()}
                            )
        except Exception as e:
            print(f"Warning: Could not read existing CSV: {e}")

    print(f"Loaded {len(existing_dates)} existing records from {filename}.")

    # 2. Fetch the podcast RSS feed
    podcast_feed_url = os.environ.get(
        "PODCAST_FEED_URL", "https://rss.art19.com/merriam-websters-word-of-the-day"
    )
    print("Fetching podcast feed...")
    try:
        r = requests.get(podcast_feed_url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"Error: Received status code {r.status_code} from feed.")
            return existing_rows
    except Exception as e:
        print(f"Error: Could not fetch podcast feed: {e}")
        return existing_rows

    # 3. Parse RSS feed items
    soup = BeautifulSoup(r.content, "xml")
    items = soup.find_all("item")

    new_entries = []

    for item in items:
        title_el = item.find("title")
        pub_date_el = item.find("pubDate")
        if title_el and pub_date_el:
            word = title_el.text.strip()
            pub_date_str = pub_date_el.text.strip()

            try:
                # Convert RFC 2822 date to YYYY-MM-DD
                dt = email.utils.parsedate_to_datetime(pub_date_str)
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                continue

            # Check if this record is already imported (by date)
            if date_str in existing_dates:
                # RSS feed is sorted newest to oldest. If we hit an existing date,
                # we can safely stop parsing because all older entries are
                # already present.
                print("Reached already-imported records. Stopping fetch.")
                break

            new_entries.append({"word": word, "date": date_str})

    if new_entries:
        print(f"Found {len(new_entries)} new entries to add.")
        # Combine new entries (which are newest first) with existing rows
        updated_data = new_entries + existing_rows
        return updated_data
    else:
        print("No new entries found.")
        return existing_rows


def save_to_csv(data, filename="word_of_the_day_embeddings.csv"):
    keys = ["word", "date"]
    with open(filename, "w", newline="", encoding="utf-8") as output_file:
        dict_writer = csv.DictWriter(output_file, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(data)
    print(f"Success! CSV updated. Total records: {len(data)}")


if __name__ == "__main__":
    csv_path = os.environ.get("SEED_CSV_PATH", "word_of_the_day_embeddings.csv")
    wotd_data = fetch_new_words(filename=csv_path)
    save_to_csv(wotd_data, filename=csv_path)
