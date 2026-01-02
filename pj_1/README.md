# Web Scraper for CVPR Papers

This script extracts paper information (titles, authors, links) from CVPR HTML pages and outputs the data to a JSON file.

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Usage

### Basic Usage (with example HTML)

Run the script with the example HTML included:

```bash
python scraper.py
```

This will create `papers_output.json` with the extracted data.

### Scraping from a File

To scrape from an HTML file, modify the script or use:

```python
from scraper import scrape_from_file, save_to_json

papers = scrape_from_file('your_file.html')
save_to_json(papers, 'output.json')
```

### Scraping from a URL

To scrape from a URL, use:

```python
from scraper import scrape_from_url, save_to_json

papers = scrape_from_url('https://example.com/cvpr2024')
save_to_json(papers, 'output.json')
```

## Output Format

The JSON output will have the following structure:

```json
{
  "total_papers": 1,
  "papers": [
    {
      "title": "Paper Title",
      "link": "/path/to/paper",
      "authors": ["Author 1", "Author 2", ...],
      "num_authors": 2
    }
  ]
}
```


