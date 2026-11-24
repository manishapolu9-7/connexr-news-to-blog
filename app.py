import re
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from pathlib import Path

import feedparser
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
DB_PATH = ROOT / "connexr_content_intelligence.db"

st.set_page_config(page_title="ConnexR Content Intelligence", page_icon="🧭", layout="wide")

# ConnexR solution taxonomy and editorial opportunity map
SERVICE_MAP = {
    "Custom AI Solutions": {
        "queries": ['"enterprise AI" OR "AI agents" OR "generative AI"'],
        "keywords": ["enterprise AI solutions", "AI agent development", "generative AI for business",
                     "AI workflow automation", "custom AI development", "enterprise AI implementation"],
        "problems": ["moving AI pilots into production", "workflow redesign", "AI reliability and evaluation",
                     "human oversight", "data readiness", "AI security and governance"],
        "buyer_questions": ["Which enterprise workflows are suitable for AI agents?",
                            "How should enterprises evaluate AI before production deployment?",
                            "How can leaders measure business value from custom AI?"],
    },
    "AIOps & IT Operations": {
        "queries": ['"AIOps" OR "IT operations automation" OR "observability"'],
        "keywords": ["AIOps solutions", "AI for IT operations", "IT operations automation",
                     "AI incident management", "predictive IT operations", "enterprise observability"],
        "problems": ["alert fatigue", "incident response and MTTR", "service reliability",
                     "operational toil", "observability gaps", "safe automation"],
        "buyer_questions": ["How can IT teams reduce alert fatigue?",
                            "Which metrics prove the value of AIOps?",
                            "How can enterprises move from incident detection to prevention?"],
    },
    "Digital & AI Transformation": {
        "queries": ['"enterprise AI transformation" OR "digital transformation" OR "AI governance"'],
        "keywords": ["enterprise AI transformation", "digital transformation strategy", "AI adoption strategy",
                     "responsible AI governance", "AI transformation roadmap", "enterprise AI implementation"],
        "problems": ["pilot-to-scale gap", "operating model and accountability", "change management",
                     "AI governance", "business outcome measurement", "process redesign"],
        "buyer_questions": ["Why do enterprise AI pilots fail to scale?",
                            "How should CIOs build an AI transformation roadmap?",
                            "How can businesses measure digital transformation outcomes?"],
    },
    "Cloud & AI Infrastructure": {
        "queries": ['"AI infrastructure" OR "GPU cloud" OR "cloud cost optimization"'],
        "keywords": ["AI infrastructure", "enterprise cloud modernization", "GPU infrastructure for AI",
                     "cloud cost optimization", "MLOps infrastructure", "AI cloud infrastructure"],
        "problems": ["compute and GPU capacity", "AI inference cost", "cloud architecture choices",
                     "MLOps readiness", "data residency and security", "resilience and scalability"],
        "buyer_questions": ["What infrastructure is required to scale enterprise AI?",
                            "How can enterprises control AI infrastructure costs?",
                            "How should leaders choose a cloud architecture for AI workloads?"],
    },
    "Enterprise Systems Modernization": {
        "queries": ['"legacy system modernization" OR "ERP modernization" OR "enterprise integration"'],
        "keywords": ["enterprise systems modernization", "legacy system modernization", "ERP modernization strategy",
                     "enterprise application integration", "API integration services", "modernizing legacy applications"],
        "problems": ["technical debt", "legacy integration constraints", "migration risk",
                     "business continuity", "data quality and migration", "architecture governance"],
        "buyer_questions": ["How can enterprises modernize legacy systems without disruption?",
                            "When should a business replace, refactor or integrate a legacy application?",
                            "How should CIOs measure modernization success?"],
    },
}

INDUSTRIES = [
    "Cross-industry", "Healthcare", "FinTech", "Banking & Financial Services", "Insurance",
    "Manufacturing", "Retail & E-Commerce", "Education & EdTech",
    "Transportation & Airlines", "Technology & Software"
]

STOPWORDS = set("""
about after again against also among because before being between both could does doing down during
each from further have having here how into itself just more most other our out over same should some
such than that the their them then there these they this those through under until very was were what
when where which while who why will with would your says said report reports according latest today
""".split())

def db():
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.execute("""CREATE TABLE IF NOT EXISTS stories(
        id TEXT PRIMARY KEY, title TEXT, link TEXT, source TEXT, published TEXT,
        published_iso TEXT, summary TEXT, service TEXT, industry TEXT, relevance INTEGER,
        fetched_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS ideas(
        id TEXT PRIMARY KEY, story_id TEXT, topic TEXT, service TEXT, industry TEXT,
        problem TEXT, primary_keyword TEXT, secondary_keywords TEXT, intent TEXT,
        rationale TEXT, aeo_question TEXT, geo_angle TEXT, priority TEXT,
        prompt TEXT, source_url TEXT, created_at TEXT)""")
    con.commit()
    return con

def clean_html(value):
    return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)

def parse_published(entry):
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            from time import mktime
            return datetime.fromtimestamp(mktime(parsed), tz=timezone.utc)
        except Exception:
            pass
    raw = entry.get("published") or entry.get("updated") or ""
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return None

def date_query(days):
    # Search engine date operators improve recall; app also enforces its own cutoff.
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    return f"after:{since}"

def make_rss_url(query, days):
    q = f"({query}) {date_query(days)}"
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"

def tokens(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9-]{2,}", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 3]

def score_story(title, summary, service):
    text = f"{title} {summary}".lower()
    signals = {
        "enterprise buyer relevance": ["enterprise", "cio", "cto", "business", "organization", "company"],
        "implementation relevance": ["deploy", "deployment", "production", "implementation", "adoption", "scale"],
        "technology relevance": ["ai", "agent", "cloud", "data", "automation", "platform", "model", "system"],
        "risk and operations": ["security", "governance", "risk", "cost", "reliability", "incident", "compliance"],
        "change signal": ["launch", "investment", "partnership", "regulation", "acquisition", "funding", "report"]
    }
    detail = {k: sum(1 for term in v if term in text) for k, v in signals.items()}
    score = min(100, sum(detail.values()) * 5 + (10 if service else 0))
    return score, detail

def fetch_news(days, services, industries, per_query=15):
    found = {}
    queries = []
    for service in services:
        for q in SERVICE_MAP[service]["queries"]:
            queries.append((q, service, "Cross-industry"))
    for industry in industries:
        if industry != "Cross-industry":
            queries.append((f'"{industry}" AND (AI OR cloud OR automation OR modernization OR cybersecurity)', "", industry))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    for query, service, industry in queries:
        try:
            feed = feedparser.parse(make_rss_url(query, days))
            for entry in feed.entries[:per_query]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                if not title or not link:
                    continue
                published_dt = parse_published(entry)
                # Strictly exclude undated or out-of-window items so a "last 1 day" filter is real.
                if published_dt is None or published_dt < cutoff or published_dt > datetime.now(timezone.utc) + timedelta(hours=2):
                    continue
                summary = clean_html(entry.get("summary", ""))[:1800]
                sid = hashlib.sha256(link.encode("utf-8")).hexdigest()[:20]
                score, _ = score_story(title, summary, service)
                record = {
                    "id": sid, "title": title, "link": link,
                    "source": entry.get("source", {}).get("title", "Google News"),
                    "published": published_dt.astimezone().strftime("%Y-%m-%d %H:%M"),
                    "published_iso": published_dt.isoformat(),
                    "summary": summary, "service": service, "industry": industry,
                    "relevance": score
                }
                # Merge duplicate stories and retain the most specific mapping.
                if sid not in found or (service and not found[sid]["service"]):
                    found[sid] = record
        except Exception:
            continue
    return sorted(found.values(), key=lambda x: (x["relevance"], x["published_iso"]), reverse=True)

def save_stories(rows):
    con = db()
    for r in rows:
        con.execute("""INSERT INTO stories VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET title=excluded.title, summary=excluded.summary,
        service=CASE WHEN excluded.service!='' THEN excluded.service ELSE stories.service END,
        industry=CASE WHEN excluded.industry!='Cross-industry' THEN excluded.industry ELSE stories.industry END,
        relevance=MAX(stories.relevance,excluded.relevance)""",
        (r["id"], r["title"], r["link"], r["source"], r["published"], r["published_iso"],
         r["summary"], r["service"], r["industry"], r["relevance"], datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()

def load_stories(days=None):
    con = db()
    df = pd.read_sql_query("SELECT * FROM stories", con)
    con.close()
    if df.empty:
        return df
    df["published_dt"] = pd.to_datetime(df["published_iso"], utc=True, errors="coerce")
    if days is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        df = df[df["published_dt"].notna() & (df["published_dt"] >= cutoff)]
    return df.sort_values(["relevance", "published_dt"], ascending=[False, False])

def analyse_signal(row, service):
    text = f"{row.get('title','')} {row.get('summary','')}".lower()
    mapping = {
        "AI agent / automation": ["agent", "autonomous", "automation", "workflow"],
        "AI security / governance": ["security", "governance", "risk", "compliance", "privacy"],
        "AI adoption / deployment": ["adoption", "deploy", "production", "pilot", "implementation"],
        "Cloud / infrastructure": ["cloud", "gpu", "infrastructure", "compute", "data centre", "datacenter"],
        "Cost / efficiency": ["cost", "efficiency", "spending", "investment", "productivity"],
        "Legacy / integration": ["legacy", "modernization", "modernisation", "ERP", "integration", "migration"],
        "IT operations / resilience": ["outage", "incident", "observability", "operations", "resilience"]
    }
    hits = []
    for label, terms in mapping.items():
        matched = [t for t in terms if t in text]
        if matched:
            hits.append((label, matched))
    if not hits:
        hits = [("Enterprise technology strategy", tokens(text)[:4])]
    return hits

def create_ideas(row, service, industry, count):
    cfg = SERVICE_MAP[service]
    industry_name = industry if industry != "Cross-industry" else "large and mid-sized enterprises"
    signals = analyse_signal(row, service)
    signal_labels = [x[0] for x in signals]
    signal_terms = list(dict.fromkeys(t for _, terms in signals for t in terms))
    # Topic families are selected from the article's detected signal, not copied from its headline.
    frameworks = [
        ("Executive decision guide", f"What {industry_name} leaders should evaluate before investing in {service.lower()}", "decision framework"),
        ("Implementation playbook", f"A practical roadmap for implementing {service.lower()} in {industry_name}", "implementation roadmap"),
        ("Risk and governance", f"The overlooked risks of {service.lower()}—and how enterprise teams can manage them", "risk and governance"),
        ("Business value", f"How to build a business case for {service.lower()} beyond technology performance", "business value and ROI"),
        ("Readiness assessment", f"Is your organisation ready for {service.lower()}? A readiness checklist for technology leaders", "readiness assessment"),
        ("Architecture and integration", f"Architecture choices that determine whether {service.lower()} can scale across the enterprise", "architecture and integration"),
        ("Measurement", f"The metrics CIOs should use to measure the success of {service.lower()}", "KPIs and measurement"),
        ("Industry application", f"Where {service.lower()} can solve high-value problems in {industry_name}", "industry use cases"),
        ("Build vs buy", f"Build, buy or partner? How to evaluate {service.lower()} options", "vendor and sourcing decision"),
        ("Future outlook", f"What the next phase of {service.lower()} means for enterprise technology strategy", "future outlook")
    ]
    # Make the lead topic specifically responsive to the story's strongest detected signal.
    if any(k in " ".join(signal_terms) for k in ["security", "governance", "risk", "privacy", "compliance"]):
        frameworks[0] = ("Risk-led executive guide", f"How enterprise leaders should assess security and governance before scaling {service.lower()}", "security and governance decision framework")
    elif any(k in " ".join(signal_terms) for k in ["agent", "autonomous", "workflow"]):
        frameworks[0] = ("Workflow opportunity guide", f"Which enterprise workflows are ready for intelligent automation—and how should leaders decide?", "AI workflow prioritisation")
    elif any(k in " ".join(signal_terms) for k in ["cost", "spending", "investment"]):
        frameworks[0] = ("Cost and value guide", f"How to evaluate the total cost and business value of {service.lower()}", "total cost and ROI framework")
    elif any(k in " ".join(signal_terms) for k in ["legacy", "integration", "migration"]):
        frameworks[0] = ("Modernisation decision guide", f"When should enterprises modernise, integrate or replace critical technology systems?", "modernisation decision framework")

    out = []
    for i, (family, topic, angle) in enumerate(frameworks[:count]):
        primary = cfg["keywords"][i % len(cfg["keywords"])]
        problem = cfg["problems"][i % len(cfg["problems"])]
        secondary = list(dict.fromkeys([
            cfg["keywords"][(i+j+1) % len(cfg["keywords"])] for j in range(4)
        ] + [f"{industry_name} {primary}", f"{problem} in enterprise {service.lower()}"]))[:8]
        question = cfg["buyer_questions"][i % len(cfg["buyer_questions"])]
        intent = "Commercial investigation" if family in ["Build vs buy", "Cost and value guide"] else "Informational"
        rationale = (f"This is a {family.lower()} angle, not a rewrite of the news headline. "
                     f"The article's detected signals are {', '.join(signal_labels)}. "
                     f"It reframes the development around {problem}, enterprise decisions and practical action for {industry_name}.")
        geo = (f"Define the key entities and concepts; explain the industry context; include a concise, source-backed answer; "
               f"compare options; provide a practical framework and original implications for {industry_name}. "
               f"Do not claim ConnexR involvement in the news.")
        prompt = f"""Act as a B2B technology editor and SEO, GEO and AEO strategist for ConnexR.

Use the news item only as a timely research signal. Do NOT rewrite its headline or produce a news summary. Build an original, evergreen or news-pegged thought-leadership article around the broader enterprise problem.

NEWS SIGNAL
Headline: {row['title']}
Publisher: {row['source']}
Published: {row['published']}
Original URL: {row['link']}
Available summary: {row['summary']}

EDITORIAL BRIEF
Topic: {topic}
Editorial family: {family}
ConnexR solution area: {service}
Target industry: {industry_name}
Enterprise problem to explore: {problem}
Primary keyword: {primary}
Secondary keyword ideas: {', '.join(secondary)}
Search intent: {intent}
AEO question: {question}
GEO direction: {geo}

ARTICLE RULES
- Aim for 1,000–1,300 words.
- Answer the reader's main question near the beginning.
- Use useful H2/H3 headings, practical steps, decision criteria and examples.
- Explain why this matters to CIOs, CTOs, IT directors and business leaders.
- Include original analysis and recommendations, not a paraphrase of the news.
- Connect naturally to ConnexR's relevant solution area without inventing capabilities, clients or results.
- Cite credible sources for factual claims; verify dates, numbers and quotations.
- Never invent search volume, statistics, quotes or case studies.
- If the news source does not support a claim, omit it or mark [EDITOR: VERIFY].

RETURN A CONTENT BRIEF, NOT JUST A TITLE:
1. Recommended title and why it is worth publishing now.
2. Reader pain point and business question.
3. Primary keyword and secondary keyword cluster.
4. Search intent and suggested funnel stage.
5. SEO title, meta description and URL slug.
6. Article outline with H2/H3 headings.
7. 4–5 AEO FAQs.
8. GEO entity and source checklist.
9. Featured image concept and alt text.
10. LinkedIn angle.
11. Original news source plus additional authoritative references to verify.

Editorial differentiation: {rationale}
"""
        out.append({
            "family": family, "topic": topic, "service": service, "industry": industry_name,
            "problem": problem, "primary": primary, "secondary": secondary,
            "intent": intent, "rationale": rationale, "aeo": question, "geo": geo,
            "priority": "High" if i < 3 and row["relevance"] >= 25 else ("Medium" if i < 7 else "Explore"),
            "prompt": prompt, "source": row["link"]
        })
    return out

def save_ideas(story_id, ideas):
    con = db()
    for x in ideas:
        iid = hashlib.sha256((story_id + x["topic"]).encode()).hexdigest()[:20]
        con.execute("""INSERT OR IGNORE INTO ideas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (iid, story_id, x["topic"], x["service"], x["industry"], x["problem"],
                     x["primary"], json.dumps(x["secondary"]), x["intent"], x["rationale"],
                     x["aeo"], x["geo"], x["priority"], x["prompt"], x["source"],
                     datetime.now(timezone.utc).isoformat()))
    con.commit()
    con.close()

st.title("🧭 ConnexR Content Intelligence Studio")
st.caption("Relevant news discovery → business-signal analysis → strategic topic recommendations → keywords → SEO/GEO/AEO brief → ready-to-copy prompt.")
st.info("This is an ideation and research assistant. It does not generate articles, use a paid AI API or connect to the ConnexR website/CMS.")

with st.sidebar:
    st.subheader("Discovery settings")
    st.caption("News is filtered by actual publication timestamp, not only the search query.")
    st.caption("Undated articles are excluded from date-filtered results.")
    st.divider()
    st.subheader("ConnexR solution areas")
    st.caption("Custom AI • AIOps • Digital & AI Transformation • Cloud & AI Infrastructure • Systems Modernization")

tab1, tab2, tab3 = st.tabs(["1. News discovery", "2. Topic recommendations", "3. Saved ideas"])

with tab1:
    st.subheader("Find current news relevant to ConnexR")
    date_choice = st.selectbox("Publication date", ["Last 24 hours", "Last 3 days", "Last 7 days", "Last 14 days", "Last 30 days"], index=2)
    days = {"Last 24 hours": 1, "Last 3 days": 3, "Last 7 days": 7, "Last 14 days": 14, "Last 30 days": 30}[date_choice]
    services = st.multiselect("ConnexR solution areas", list(SERVICE_MAP.keys()), default=list(SERVICE_MAP.keys()))
    industries = st.multiselect("Industries", INDUSTRIES, default=["Cross-industry", "Healthcare", "Banking & Financial Services", "Manufacturing", "Technology & Software"])
    per_query = st.slider("Maximum stories per search", 5, 25, 15)
    if st.button("🔎 Fetch latest news", type="primary", use_container_width=True):
        if not services and len(industries) <= 1:
            st.warning("Select at least one solution area or industry.")
        else:
            with st.spinner("Searching news feeds and checking publication dates..."):
                items = fetch_news(days, services, industries, per_query)
                save_stories(items)
                st.session_state["last_fetch_count"] = len(items)
                st.session_state["active_days"] = days
            st.success(f"Fetched {len(items)} stories published within the selected window.")
    df = load_stories(days)
    if not df.empty:
        col1, col2, col3 = st.columns(3)
        with col1:
            min_rel = st.slider("Minimum relevance", 0, 100, 10, 5)
        with col2:
            service_filter = st.selectbox("Solution filter", ["All"] + list(SERVICE_MAP.keys()))
        with col3:
            sort_mode = st.selectbox("Sort by", ["Most relevant", "Newest first"])
        view = df[df["relevance"] >= min_rel].copy()
        if service_filter != "All":
            view = view[view["service"] == service_filter]
        if sort_mode == "Newest first":
            view = view.sort_values("published_dt", ascending=False)
        st.caption(f"{len(view)} matching stories · {date_choice} · All times shown in your browser/server local timezone")
        for _, r in view.head(100).iterrows():
            with st.container(border=True):
                st.markdown(f"**{r['title']}**")
                st.caption(f"{r['source']} · Published {r['published']} · Relevance {r['relevance']}/100")
                st.write((r["summary"] or "No feed summary available.")[:500])
                st.markdown(f"[Read original news]({r['link']})")
                if st.button("Create topic recommendations", key=f"select_{r['id']}"):
                    st.session_state["selected_story_id"] = r["id"]
                    st.session_state["selected_days"] = days
                    st.toast("Story selected. Open Topic recommendations.")
    else:
        st.info("No dated stories found for this period yet. Try a longer date window or fewer filters.")

with tab2:
    st.subheader("Get strategic topics—not rewritten headlines")
    all_stories = load_stories(None)
    if all_stories.empty:
        st.info("Fetch news first.")
    else:
        selected_id = st.session_state.get("selected_story_id")
        if selected_id and selected_id in all_stories["id"].values:
            default_index = all_stories.index[all_stories["id"] == selected_id][0]
        else:
            default_index = all_stories.index[0]
        labels = [f"{r['title'][:115]} · {r['source']} · {r['published']}" for _, r in all_stories.iterrows()]
        selected_label = st.selectbox("Select a news story", labels, index=list(all_stories.index).index(default_index))
        row = all_stories.iloc[labels.index(selected_label)].to_dict()
        a, b = st.columns(2)
        with a:
            service_default = row["service"] if row["service"] in SERVICE_MAP else list(SERVICE_MAP.keys())[0]
            service = st.selectbox("ConnexR solution area", list(SERVICE_MAP.keys()), index=list(SERVICE_MAP.keys()).index(service_default))
        with b:
            industry_default = row["industry"] if row["industry"] in INDUSTRIES else "Cross-industry"
            industry = st.selectbox("Target industry", INDUSTRIES, index=INDUSTRIES.index(industry_default))
        count = st.slider("Number of recommendations", 5, 10, 8)
        st.markdown("**News signal being analysed**")
        st.write(row["title"])
        st.caption(row["summary"][:650])
        detected = analyse_signal(row, service)
        st.markdown("**Detected signals:** " + " · ".join(x[0] for x in detected))
        if st.button("✨ Generate strategic recommendations", type="primary", use_container_width=True):
            ideas = create_ideas(row, service, industry, count)
            save_ideas(row["id"], ideas)
            st.session_state["current_ideas"] = ideas
        ideas = st.session_state.get("current_ideas", [])
        for idx, x in enumerate(ideas, 1):
            with st.expander(f"{idx}. {x['topic']} · {x['priority']} priority", expanded=(idx == 1)):
                st.markdown(f"**Editorial type:** {x['family']}")
                st.markdown(f"**Business problem:** {x['problem']}")
                st.markdown(f"**Why this is relevant:** {x['rationale']}")
                st.markdown(f"**Primary keyword idea:** {x['primary']}")
                st.markdown("**Secondary keyword ideas:** " + ", ".join(x["secondary"]))
                st.markdown(f"**Search intent:** {x['intent']}")
                st.markdown(f"**AEO question:** {x['aeo']}")
                st.markdown(f"**GEO direction:** {x['geo']}")
                st.markdown(f"**Original news:** [Open source]({x['source']})")
                st.text_area("Ready-to-copy research and writing prompt", x["prompt"], height=480, key=f"prompt_{idx}")
                st.download_button("Download this prompt", x["prompt"], file_name=f"connexr-topic-prompt-{idx}.txt", key=f"prompt_dl_{idx}")
        if ideas:
            export = pd.DataFrame([{
                "Topic": x["topic"], "Editorial type": x["family"], "Service": x["service"],
                "Industry": x["industry"], "Business problem": x["problem"],
                "Primary keyword": x["primary"], "Secondary keyword ideas": ", ".join(x["secondary"]),
                "Search intent": x["intent"], "Why relevant": x["rationale"],
                "AEO question": x["aeo"], "GEO direction": x["geo"], "Priority": x["priority"],
                "Source URL": x["source"], "Ready-to-copy prompt": x["prompt"]
            } for x in ideas])
            st.download_button("⬇️ Export all recommendations and prompts (CSV)", export.to_csv(index=False).encode("utf-8"), "connexr_content_recommendations.csv", "text/csv")

with tab3:
    st.subheader("Saved topic recommendations")
    con = db()
    saved = pd.read_sql_query("SELECT topic,service,industry,problem,primary_keyword,secondary_keywords,intent,rationale,aeo_question,geo_angle,priority,source_url,created_at FROM ideas ORDER BY created_at DESC", con)
    con.close()
    if saved.empty:
        st.info("Your saved recommendations will appear here after generating ideas.")
    else:
        st.dataframe(saved, use_container_width=True, hide_index=True)
        st.download_button("Export saved recommendations (CSV)", saved.to_csv(index=False).encode("utf-8"), "connexr_saved_recommendations.csv", "text/csv")

st.divider()
st.caption("Date filtering uses the published timestamp from RSS entries and excludes undated stories. Some feeds may publish timestamps in a different timezone or omit dates. Relevance scores are heuristic, not an AI judgement. Keyword suggestions are ideas, not verified search-volume or difficulty metrics. Validate demand in Google Keyword Planner/Search Console before prioritising. GEO/AEO guidance improves clarity and answerability but cannot guarantee AI citations or rankings.")
