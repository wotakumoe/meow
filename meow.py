#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
# ]
# ///

import requests
from bs4 import BeautifulSoup
import sys
import urllib.parse
from pathlib import Path
import time
import re

def sanitize_filename(filename):
    """Remove or replace invalid characters from filename"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename.strip()

def create_folder_name(base_url):
    """Create a folder name based on the URL"""
    try:
        parsed_url = urllib.parse.urlparse(base_url)

        # Extract meaningful parts from URL
        if '/user/' in parsed_url.path:
            username = parsed_url.path.split('/user/')[1].split('?')[0]
            folder_name = f"nyaa_{username}"
        elif '?q=' in base_url:
            query_params = urllib.parse.parse_qs(parsed_url.query)
            if 'q' in query_params:
                search_query = query_params['q'][0]
                folder_name = sanitize_filename(search_query.replace('+', ' '))
            else:
                folder_name = "nyaa_torrents"
        else:
            folder_name = "nyaa_torrents"

        return sanitize_filename(folder_name)
    except Exception:
        return "nyaa_torrents"

def extract_title_from_row(row):
    """Extract title using improved strategies"""
    
    # Strategy 1: Look for the main title link (most common case)
    # Nyaa.si typically has the title in a link that goes to /view/ID
    title_links = row.find_all('a', href=re.compile(r'/view/\d+'))
    for link in title_links:
        # Get the text and clean it up
        title = link.get_text(strip=True)
        if title and len(title) > 3 and not title.isdigit():
            # Skip if it's just numbers or very short
            if not re.match(r'^\d+(\.\d+)?$', title.strip()):
                return title
    
    # Strategy 2: Look for title in specific table columns
    # Nyaa.si usually has: Category | Title | Links | Size | Date | Seeders | Leechers | Downloads
    tds = row.find_all('td')
    
    if len(tds) >= 2:
        # The title is typically in the second column (index 1)
        title_td = tds[1] if len(tds) > 1 else None
        
        if title_td:
            # Look for any links in the title column
            links = title_td.find_all('a')
            for link in links:
                title = link.get_text(strip=True)
                if title and len(title) > 3:
                    # Check if it's not just a number or size info
                    if (not title.isdigit() and 
                        'MiB' not in title and 
                        'GiB' not in title and 
                        'KB' not in title and
                        not re.match(r'^\d+(\.\d+)?(MB|GB|KB|MiB|GiB)?$', title.strip())):
                        return title
            
            # If no links, try getting direct text from the td
            direct_text = title_td.get_text(strip=True)
            # Clean up the text by removing extra whitespace and newlines
            direct_text = ' '.join(direct_text.split())
            
            if (direct_text and len(direct_text) > 5 and 
                not direct_text.isdigit() and
                'MiB' not in direct_text and 
                'GiB' not in direct_text):
                # Try to extract the main title part if there are multiple parts
                # Split on common separators and take the longest meaningful part
                parts = re.split(r'[\n\t\|]+', direct_text)
                for part in parts:
                    part = part.strip()
                    if (len(part) > 10 and 
                        any(c.isalpha() for c in part) and
                        not re.match(r'^\d+$', part)):
                        return part
                
                # If no good parts found, return the whole text if it's reasonable
                if len(direct_text) > 5:
                    return direct_text
    
    # Strategy 3: Look for title attribute in any element
    for element in row.find_all(['a', 'td', 'span'], title=True):
        title = element.get('title', '').strip()
        if (title and len(title) > 5 and 
            not title.isdigit() and
            'MiB' not in title and 
            'GiB' not in title):
            return title
    
    # Strategy 4: Parse all text and try to find the title
    # Get all text from the row and try to identify the title
    all_text = row.get_text()
    
    # Split text into lines and parts
    lines = [line.strip() for line in all_text.split('\n') if line.strip()]
    
    for line in lines:
        # Skip lines that are clearly not titles
        if (len(line) > 10 and 
            any(c.isalpha() for c in line) and
            not line.isdigit() and
            'MiB' not in line and 
            'GiB' not in line and
            'UTC' not in line and
            not re.match(r'^\d+$', line.strip()) and
            not re.match(r'^\d+(\.\d+)?\s*(MB|GB|KB|MiB|GiB)$', line.strip())):
            
            # Additional cleaning
            cleaned_line = re.sub(r'^[^\w\[\(]+', '', line)  # Remove leading non-word chars except brackets
            cleaned_line = re.sub(r'[^\w\s\(\)\[\]._-]+$', '', cleaned_line)  # Clean trailing chars
            
            if len(cleaned_line) > 10:
                return cleaned_line
    
    # Strategy 5: Last resort - look for any substantial text that might be a title
    # This is more aggressive and might catch edge cases
    text_content = ' '.join(row.get_text().split())
    
    # Try to extract meaningful chunks
    words = text_content.split()
    potential_titles = []
    current_chunk = []
    
    for word in words:
        # Skip obvious non-title words
        if (word.isdigit() or 
            word in ['MiB', 'GiB', 'MB', 'GB', 'KB', 'UTC', 'Trusted', 'Remake'] or
            re.match(r'^\d+(\.\d+)?$', word)):
            if current_chunk and len(' '.join(current_chunk)) > 10:
                potential_titles.append(' '.join(current_chunk))
            current_chunk = []
        else:
            current_chunk.append(word)
    
    # Add the last chunk if it exists
    if current_chunk and len(' '.join(current_chunk)) > 10:
        potential_titles.append(' '.join(current_chunk))
    
    # Return the longest potential title
    if potential_titles:
        longest_title = max(potential_titles, key=len)
        if len(longest_title) > 10:
            return longest_title
    
    return None

def get_torrent_links_from_page(session, url):
    """Extract torrent download links and titles from a single page"""
    try:
        print(f"Scraping: {url}")
        response = session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        torrents = []

        # Find the table body containing torrent rows
        tbody = soup.find('tbody')
        if not tbody:
            print("No tbody found on page")
            return []

        # Find all table rows
        rows = tbody.find_all('tr')
        print(f"Found {len(rows)} rows to process")

        for row_idx, row in enumerate(rows):
            try:
                # Find download link
                download_link = row.find('a', href=re.compile(r'/download/\d+\.torrent'))
                if not download_link:
                    continue

                download_path = download_link.get('href')
                download_url = 'https://nyaa.si' + download_path
                torrent_id = download_path.split('/')[-1].replace('.torrent', '')

                # Extract title using improved strategies
                torrent_title = extract_title_from_row(row)

                # Enhanced debugging for failed extractions
                if not torrent_title:
                    torrent_title = f"torrent_{torrent_id}"
                    print(f"  Warning: Could not extract title for row {row_idx + 1}, using ID: {torrent_id}")
                    
                    # More detailed debugging output
                    if len([t for t in torrents if t['title'].startswith('torrent_')]) < 3:  # Only debug first few failures
                        print(f"  Debug info for row {row_idx + 1}:")
                        tds = row.find_all('td')
                        for i, td in enumerate(tds):
                            text = td.get_text(strip=True)[:100]  # First 100 chars
                            print(f"    Column {i}: {text}")
                        
                        # Show all links in the row
                        links = row.find_all('a')
                        print(f"    Links found: {len(links)}")
                        for i, link in enumerate(links):
                            href = link.get('href', '')
                            text = link.get_text(strip=True)[:50]
                            print(f"      Link {i}: {href} -> '{text}'")
                else:
                    print(f"  Extracted title: {torrent_title[:60]}{'...' if len(torrent_title) > 60 else ''}")

                torrents.append({
                    'title': torrent_title,
                    'download_url': download_url,
                    'filename': f"{sanitize_filename(torrent_title)}.torrent"
                })

            except Exception as e:
                print(f"Error processing row {row_idx + 1}: {e}")
                continue

        return torrents

    except Exception as e:
        print(f"Error scraping page {url}: {e}")
        return []

def download_torrent(session, url, filepath):
    """Download a single torrent file"""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()

        with open(filepath, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False

def get_base_url_and_page_param(url):
    """Extract base URL and determine page parameter format"""
    parsed_url = urllib.parse.urlparse(url)
    query_params = urllib.parse.parse_qs(parsed_url.query)

    # Remove page parameter if it exists
    if 'p' in query_params:
        del query_params['p']

    # Rebuild URL without page parameter
    new_query = urllib.parse.urlencode(query_params, doseq=True)
    base_url = urllib.parse.urlunparse((
        parsed_url.scheme,
        parsed_url.netloc,
        parsed_url.path,
        parsed_url.params,
        new_query,
        parsed_url.fragment
    ))

    return base_url

def scrape_all_pages(base_url):
    """Main function to scrape all pages and download torrents"""
    try:
        # Create session for connection reuse
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

        # Create folder
        folder_name = create_folder_name(base_url)
        folder_path = Path(folder_name)
        folder_path.mkdir(exist_ok=True)
        print(f"Created/Using folder: {folder_path.absolute()}")

        # Get base URL without page parameter
        clean_base_url = get_base_url_and_page_param(base_url)

        all_torrents = []
        page = 1

        while True:
            # Construct URL for current page
            if '?' in clean_base_url:
                current_url = f"{clean_base_url}&p={page}"
            else:
                current_url = f"{clean_base_url}?p={page}"

            # Get torrents from current page
            page_torrents = get_torrent_links_from_page(session, current_url)

            if not page_torrents:
                print(f"No torrents found on page {page}, stopping...")
                break

            print(f"Found {len(page_torrents)} torrents on page {page}")
            all_torrents.extend(page_torrents)

            # Check if next page exists by trying to access it
            next_page_url = f"{clean_base_url}&p={page + 1}" if '?' in clean_base_url else f"{clean_base_url}?p={page + 1}"
            next_page_torrents = get_torrent_links_from_page(session, next_page_url)

            if not next_page_torrents:
                print(f"No more pages found after page {page}")
                break

            page += 1
            time.sleep(1)  # Be respectful to the server

        if not all_torrents:
            print("No torrents found!")
            return

        print(f"\nTotal torrents found: {len(all_torrents)}")

        # Show summary of titles that couldn't be extracted properly
        fallback_titles = [t for t in all_torrents if t['title'].startswith('torrent_')]
        if fallback_titles:
            print(f"Warning: {len(fallback_titles)} torrents are using fallback names:")
            for t in fallback_titles[:5]:  # Show first 5
                print(f"  - {t['title']}")
            if len(fallback_titles) > 5:
                print(f"  ... and {len(fallback_titles) - 5} more")
        else:
            print("✓ All torrent titles were successfully extracted!")

        print("Starting downloads...")

        downloaded = 0
        failed = 0
        skipped = 0

        for i, torrent in enumerate(all_torrents, 1):
            try:
                filepath = folder_path / torrent['filename']

                print(f"[{i}/{len(all_torrents)}] {torrent['title']}")

                # Skip if file already exists
                if filepath.exists():
                    print(f"  -> Already exists, skipping")
                    skipped += 1
                    continue

                # Download torrent
                if download_torrent(session, torrent['download_url'], filepath):
                    print(f"  -> Downloaded successfully")
                    downloaded += 1
                else:
                    print(f"  -> Download failed")
                    failed += 1

                # Small delay to be respectful
                time.sleep(0.5)

            except Exception as e:
                print(f"Error processing torrent {i}: {e}")
                failed += 1

        print(f"\nDownload Summary:")
        print(f"Successfully downloaded: {downloaded}")
        print(f"Already existed (skipped): {skipped}")
        print(f"Failed downloads: {failed}")
        print(f"Total torrents: {len(all_torrents)}")
        print(f"Files saved to: {folder_path.absolute()}")

    except Exception as e:
        print(f"Unexpected error: {e}")

def main():
    """Main entry point"""
    if len(sys.argv) != 2:
        print("Usage: python meow.py <NYAA_URL>")
        sys.exit(1)

    url = sys.argv[1]

    # Validate URL
    if not url.startswith('http'):
        print("Error: Please provide a valid HTTP/HTTPS URL")
        sys.exit(1)

    if 'nyaa.si' not in url:
        print("Warning: This script is designed for nyaa.si URLs")

    scrape_all_pages(url)

if __name__ == "__main__":
    main()