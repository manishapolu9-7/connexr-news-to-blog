# ConnexR News-to-Blog Studio

A local, ready-to-run Streamlit application that:
1. Searches Google News RSS for topics mapped to ConnexR's five service lines and target industries.
2. Scores and stores stories in a local SQLite content library.
3. Lets an editor shortlist stories and generate SEO blog drafts using the OpenAI API.
4. Produces title, meta title, meta description, slug, keywords, article Markdown, FAQ ideas, internal-link suggestions, editorial checks and a LinkedIn post.
5. Exports Markdown and JSON packages.

## Run on Windows
1. Install Python 3.10 or newer from https://www.python.org/downloads/
2. Extract this ZIP.
3. Double-click `run_windows.bat`.
4. The app opens in your browser at the local Streamlit address.
5. Paste your OpenAI API key in the sidebar to enable blog generation.

## Run on macOS / Linux
```bash
chmod +x run_mac_linux.sh
./run_mac_linux.sh
```

## API key
The app requires an OpenAI API key only for AI blog generation. You can enter it in the sidebar for the current session, or set `OPENAI_API_KEY` as an environment variable. The key is not stored in the SQLite database. API usage may incur charges under your OpenAI account.

## News discovery
News discovery uses public Google News RSS search feeds. No news API key is required. Search coverage, feed availability and article summaries depend on the RSS results. The app stores article metadata and links locally; it does not reproduce full source articles.

## ConnexR topic mapping
- Custom AI Solutions
- AIOps & IT Operations
- Digital & AI Transformation
- Cloud & AI Infrastructure
- Enterprise Systems Modernization

Industries include healthcare, FinTech, banking/financial services, insurance, manufacturing, retail/e-commerce, education/EdTech, transportation/airlines, and technology/software.

## Important editorial workflow
Treat generated content as a first draft. Before publishing:
- Open and read the original source.
- Verify dates, figures, quotes, named organizations and regulatory statements.
- Remove unsupported claims and all `[EDITOR: VERIFY]` markers.
- Confirm the ConnexR service description and internal links.
- Add original expert insight, examples and evidence; avoid thin rewrites of news.
- Check keyword intent, originality, accessibility and final SEO metadata.

## Data and privacy
The SQLite database `connexr_content.db` is created in the app folder. It stores article metadata and generated drafts locally. Do not put confidential information in the editorial instructions.
