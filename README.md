# Workforce
A Python-based data engineering and automation pipeline designed to optimize Workforce Management (WFM) tracking. The system automates the extraction of raw call center data and agent break logs, enforces complex operational shift rules to sanitize timelines, calculates deep performance metrics (such as precise idleness and untracked time), and consolidates the data with external sales records from Google Sheets. The architecture outputs ready-to-use flat databases for Power BI dashboards and highly customized, visually rich Excel reports for management.

## ⚙️ Features

* **Automated Scraping:** Uses `playwright` to securely log into the call center platform, downloading raw engagement data and break logs for any target date.
* **Dynamic Shift Sanitization:** Evaluates data agent-by-agent to apply specific business compliance rules, removing pre-shift activity noise (5-minute gap threshold) and dynamically adjusting shift schedules for late logins (10-minute sliding window rule).
* **Intelligent Break Optimization:** Automatically matches and cross-references timeline gaps to close open-ended agent breaks based on subsequent platform activities and dynamic shift end times.
* **Advanced WFM Metrics Calculation:** Leverages `pandas` and `numpy` to calculate total seconds spent on calls, productive interactions (CPC), idle time waiting for dialer distribution, and untracked gaps during the working hours.
* **Multi-Sheet Sheets Integration:** Connects to external Google Sheets to extract, validate, and aggregate external sales data across multiple monthly tabs, checking file integrity against the targeted month.
* **Rich Excel Exporting:** Generates stylized spreadsheets with `xlsxwriter` that feature automatic layout scaling, visual conditional alerts for operational anomalies (e.g., high idleness or untracked time), and real-time profile picture downloads directly from Google Drive.
* **Power BI Timeline Generation:** Transforms sparse call and break logs into structured, sequential blocks of time, filtering out insignificant events to build a clean chronological visualization pipeline.
* **Desktop GUI Application:** Offers an interactive user interface built with `tkinter` and `tkcalendar`, supporting keyboard arrow key navigation to pick processing dates easily.

## 🛠️ Tech Stack

### Data Engineering & Automation

* **Python:** Core environment for the entire tool.
* **Playwright:** Headless browser automation engine used to navigate and extract reports from the operational system.
* **Pandas & NumPy:** Fast data manipulation, datetime parsing, calculations, and relational merges.

### Visualization & UI

* **Tkinter & Tkcalendar:** Provides a lightweight native GUI prompt allowing users to choose whether to fetch new web data and select dates comfortably.
* **XlsxWriter:** Specialized spreadsheet writer configured with complex corporate formatting styles and image embedding parameters.
* **Pillow (PIL):** Used to download, stream, and properly rescale agent avatar thumbnails before writing them to disk.

## 📁 Project Structure

Below is the breakdown of the repository's main directories:

```text
└── ./
    ├── analysis/              # Data Processing & Analytics Engine
    │   ├── engine/            # Core business logic pipelines
    │   │   ├── cleaners.py    # Raw data cleaning, shift rules, and break closures
    │   │   ├── metrics.py     # Idleness algorithms and external Sheets fetcher
    │   │   └── timeline.py    # Power BI chronological event block generator
    │   ├── bi_exporter.py     # Exports normalized database structures for Power BI
    │   ├── config.py          # Operational constants, status mapping, and paths
    │   ├── excel_exporter.py  # Builds the formatted Excel spreadsheet with image layouts
    │   └── main.py            # Orchestrator coordinating the entire analysis flow
    │
    ├── scraper/               # Data Gathering Module
    │   └── main.py            # Playwright script for system login and file downloads
    │
    ├── run.py                 # Main application entrypoint featuring the Tkinter GUI
    └── utils.py               # Time transformation helpers and image processing services
```

## 🚀 Usage

### Scope and Customization Notice
This project is a highly tailored, proprietary WFM solution developed specifically for a single call center environment running on the Joytec platform. It is not a generic plug-and-play SaaS tool. The internal data parsing architecture relies heavily on specific, hardcoded operational parameters, including custom call dispositions, tailored break classifications, and granular business exceptions. Therefore, replication of this pipeline in another call center operation would require substantial refactoring of the underlying configuration structures to match the new business vocabulary.

### Prerequisites
Before running the engine, ensure you have Python 3.8+ installed along with the required web automation binaries.

```text
# Install python dependencies
pip install pandas numpy playwright openpyxl xlsxwriter pillow python-dotenv tkcalendar

# Install Playwright browser binaries
playwright install chromium
```

### Environment Variables
Create a `.env` file in the root directory of the project to store your credentials and integration URLs:

```text
SITE_USER=your_joytec_username
SITE_PASS=your_joytec_password
SHEETS_URL=your_google_sheets_exported_excel_url
```

### Running the Application
To launch the complete pipeline with the graphical calendar interface, simply execute the orchestrator script:

```text
python run.py
```

> **Note:** You can also bypass the GUI and run the analysis directly through the terminal by passing specific arguments (e.g., `python run.py --only-process` or `python run.py --date 27/05/2026`).