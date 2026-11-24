import os, re, json, sqlite3, hashlib
from datetime import datetime, timezone
from urllib.parse import quote_plus
import feedparser
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup
from openai import OpenAI

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "connexr_content.db")

st.set_page_config(page_title="ConnexR News-to-Blog Studio", page_icon="📰", layout="wide")

SERVICE_LINES = {
    "Custom AI Solutions": [
        "enterprise AI agents", "generative AI in business", "LLM deployment enterprise",
        "AI workflow automation", "predictive analytics enterprise", "computer vision business"
    ],
    "AIOps & IT Operations": [
        "AIOps enterprise IT", "AI IT operations automation", "predictive IT operations",
        "self healing infrastructure", "observability incident management"
    ],
    "Digital & AI Transformation": [
        "enterprise AI transformation", "AI adoption at scale", "responsible AI governance",
        "enterprise AI pilot to production", "AI operating model"
    ],
    "Cloud & AI Infrastructure": [
        "AI infrastructure cloud", "enterprise cloud modernization", "GPU cloud infrastructure",
        "cloud cost optimization enterprise", "MLOps infrastructure"
    ],
    "Enterprise Systems Modernization": [
        "ERP modernization enterprise", "CRM modernization integration", "legacy systems modernization",
        "enterprise API integration", "digital platform modernization"
    ],
}
INDUSTRIES = [
    "Healthcare", "FinTech", "Banking & Financial Services", "Insurance", "Manufacturing",
    "Retail & E-Commerce", "Education & EdTech", "Transportation & Airlines", "Technology & Software"
]
COMPANY_CONTEXT = """ConnexR is an enterprise AI and IT partner that designs, builds and operates technology.
Its five service lines are Custom AI Solutions; AIOps & IT Operations; Digital & AI Transformation;
Cloud & AI Infrastructure; and Enterprise Systems Modernization. It serves enterprise buyers across
healthcare, fintech, banking/financial services, insurance, manufacturing, retail/e-commerce,
education/EdTech, transportation/airlines, and technology/software. Positioning: connect strategy,
engineering and ongoing operations; move enterprise AI beyond pilots into production and measurable
business outcomes. Website: https://connexr.com"""

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""CREATE TABLE IF NOT EXISTS articles (
        id TEXT PRIMARY KEY, title TEXT, link TEXT, source TEXT, published TEXT,
        summary TEXT, service TEXT, industry TEXT, score INTEGER, status TEXT DEFAULT 'New',
        created_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS drafts (
        id TEXT PRIMARY KEY, article_id TEXT, title TEXT, meta_title TEXT, meta_description TEXT,
        slug TEXT, keywords TEXT, content TEXT, created_at TEXT)""")
    conn.commit()
    return conn

def clean_html(s):
    return BeautifulSoup(s or "", "html.parser").get_text(" ", strip=True)

def stable_id(link, title):
    return hashlib.sha256((link or title).encode("utf-8")).hexdigest()[:20]

def google_news_url(query, days):
    return f"https://news.google.com/rss/search?q={quote_plus(query + ' when:' + str(days) + 'd')}&hl=en-US&gl=US&ceid=US:en"

def fetch_news(days, selected_services, selected_industries, max_per_query=12):
    queries = []
    for service in selected_services:
        for term in SERVICE_LINES[service][:3]:
            queries.append((term, service, ""))
    for industry in selected_industries:
        queries.append((f"{industry} enterprise AI digital transformation technology", "", industry))
    rows, seen = [], set()
    for query, service, industry in queries:
        try:
            feed = feedparser.parse(google_news_url(query, days))
            for entry in feed.entries[:max_per_query]:
                title = clean_html(entry.get("title", ""))
                link = entry.get("link", "")
                if not title or not link:
                    continue
                aid = stable_id(link, title)
                if aid in seen: continue
                seen.add(aid)
                summary = clean_html(entry.get("summary", ""))[:1200]
                published = entry.get("published", "")
                source = entry.get("source", {}).get("title", "Google News RSS")
                text = (title + " " + summary).lower()
                score = 0
                keywords = ["enterprise", "business", "deployment", "production", "governance",
                            "automation", "infrastructure", "modernization", "operations", "security",
                            "cost", "risk", "cloud", "AI", "data", "workflow"]
                score += sum(2 for k in keywords if k.lower() in text)
                if service: score += 3
                if industry: score += 2
                rows.append({"id": aid, "title": title, "link": link, "source": source,
                             "published": published, "summary": summary, "service": service,
                             "industry": industry, "score": min(score, 100)})
        except Exception:
            continue
    return sorted(rows, key=lambda x: x["score"], reverse=True)

def save_articles(rows):
    conn = db()
    for r in rows:
        conn.execute("""INSERT OR IGNORE INTO articles
        (id,title,link,source,published,summary,service,industry,score,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (r["id"],r["title"],r["link"],r["source"],r["published"],r["summary"],
         r["service"],r["industry"],r["score"],datetime.now(timezone.utc).isoformat()))
    conn.commit()

def load_articles():
    conn = db()
    df = pd.read_sql_query("SELECT * FROM articles ORDER BY score DESC, created_at DESC", conn)
    conn.close()
    return df

def save_draft(article_id, data):
    did = hashlib.sha256((article_id + datetime.now().isoformat()).encode()).hexdigest()[:20]
    conn = db()
    conn.execute("""INSERT INTO drafts
    (id,article_id,title,meta_title,meta_description,slug,keywords,content,created_at)
    VALUES (?,?,?,?,?,?,?,?,?)""",
    (did,article_id,data.get("title",""),data.get("meta_title",""),data.get("meta_description",""),
     data.get("slug",""),json.dumps(data.get("keywords",[])),data.get("content",""),
     datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()

def generate_blog(article, api_key, model, audience, tone, target_words, primary_keyword, extra_instructions):
    client = OpenAI(api_key=api_key)
    prompt = f"""
You are ConnexR's senior B2B technology editor and SEO strategist.
Create an original, evidence-led blog draft using the news item below as a timely hook.
Do not copy the source article. Do not invent statistics, quotes, customer examples, product capabilities,
dates, or claims. Clearly distinguish reported facts from analysis and recommendations.
If the source details are thin, keep claims conservative and add [EDITOR: VERIFY] where needed.
Do not imply ConnexR was involved in the news. Explain the business implications and connect naturally
to relevant ConnexR capabilities without making the article an advertisement.

CONNEXR CONTEXT:
{COMPANY_CONTEXT}

NEWS ITEM:
Headline: {article['title']}
Publisher: {article['source']}
Published: {article['published']}
URL: {article['link']}
Available summary: {article['summary']}

RELEVANCE:
Service line: {article['service'] or 'Choose the most relevant one'}
Industry: {article['industry'] or 'Choose the most relevant one'}
Audience: {audience}
Tone: {tone}
Target length: approximately {target_words} words
Primary keyword: {primary_keyword or 'Choose a natural high-intent keyword'}
Additional instructions: {extra_instructions or 'None'}

Return valid JSON only with keys:
title, meta_title (<=60 characters), meta_description (140-160 characters),
slug, primary_keyword, secondary_keywords (array of 5-8),
excerpt (40-60 words), content_markdown, suggested_internal_links (array of objects with
anchor_text and URL chosen only from https://connexr.com/what-we-build/, https://connexr.com/industries/,
https://connexr.com/insights/), faq (array of 3-5 question/answer objects),
editorial_checks (array of facts/claims the editor should verify),
social_linkedin (short post).
Structure content_markdown with a compelling H1, concise intro, useful H2/H3s, practical implications,
a section on what enterprise leaders should do next, a natural ConnexR relevance section, and conclusion.
Avoid keyword stuffing. Include source attribution and a link to the original reporting near the end.
"""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role":"system","content":"Return strict JSON only. No markdown code fences."},
                  {"role":"user","content":prompt}],
        temperature=0.45
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw).strip()
    return json.loads(raw)

st.title("📰 ConnexR News-to-Blog Studio")
st.caption("Discover relevant industry news → score opportunities → generate SEO-ready, editor-reviewable blog drafts.")
with st.sidebar:
    st.header("Configuration")
    api_key = st.text_input("OpenAI API key", type="password", value=os.getenv("OPENAI_API_KEY",""),
                            help="Used only when you generate a blog. Not saved to the database.")
    model = st.text_input("Model", value=os.getenv("OPENAI_MODEL","gpt-4.1-mini"))
    st.divider()
    st.markdown("**ConnexR positioning**")
    st.caption("Custom AI • AIOps • AI transformation • Cloud & AI infrastructure • Systems modernization")
    st.caption("Sources: Google News RSS search feeds. Verify original reporting before publishing.")

tab1, tab2, tab3 = st.tabs(["Discover news", "Generate a blog", "Saved drafts"])

with tab1:
    st.subheader("Find news aligned with ConnexR's solutions")
    c1,c2 = st.columns([1,2])
    with c1:
        days = st.selectbox("Look-back period", [1,3,7,14,30], index=2, format_func=lambda x: f"Last {x} days")
        max_items = st.slider("Max articles per search", 5, 25, 12)
    with c2:
        services = st.multiselect("ConnexR service lines", list(SERVICE_LINES.keys()), default=list(SERVICE_LINES.keys()))
        industries = st.multiselect("Industries", INDUSTRIES, default=INDUSTRIES)
    if st.button("🔎 Discover relevant news", type="primary", use_container_width=True):
        with st.spinner("Searching news feeds and scoring relevance..."):
            found = fetch_news(days, services, industries, max_items)
            save_articles(found)
            st.session_state["latest_found"] = found
        st.success(f"Found {len(found)} unique stories. Saved new items to your local content library.")
    df = load_articles()
    if not df.empty:
        f1,f2,f3 = st.columns(3)
        with f1: min_score = st.slider("Minimum relevance score", 0, 30, 2)
        with f2: service_filter = st.selectbox("Service filter", ["All"] + list(SERVICE_LINES.keys()))
        with f3: status_filter = st.selectbox("Workflow status", ["All","New","Shortlisted","Drafted","Published"])
        view = df[df.score >= min_score]
        if service_filter != "All": view = view[(view.service == service_filter) | (view.service == "")]
        if status_filter != "All": view = view[view.status == status_filter]
        st.caption(f"{len(view)} stories in your filtered library")
        for _, row in view.head(100).iterrows():
            with st.container(border=True):
                a,b = st.columns([5,1])
                with a:
                    st.markdown(f"**{row['title']}**")
                    st.caption(f"{row['source']} · {row['published'] or 'Date unavailable'} · Score {row['score']}/100")
                    st.write((row['summary'] or "No summary available")[:450])
                    st.markdown(f"[Open original story]({row['link']})")
                    st.caption(f"Service: {row['service'] or 'Unassigned'} | Industry: {row['industry'] or 'Unassigned'}")
                with b:
                    if st.button("Shortlist", key=f"short_{row['id']}"):
                        conn=db(); conn.execute("UPDATE articles SET status='Shortlisted' WHERE id=?",(row['id'],)); conn.commit(); conn.close()
                        st.rerun()
                    if st.button("Draft", key=f"draft_{row['id']}"):
                        st.session_state["selected_article_id"] = row['id']
                        st.info("Open the Generate a blog tab to create the draft.")
    else:
        st.info("Discover news to populate your content library.")

with tab2:
    st.subheader("Turn a selected story into an SEO blog draft")
    df = load_articles()
    if df.empty:
        st.info("First discover news in the Discover news tab.")
    else:
        options = {f"{r['title'][:110]} · score {r['score']} · {r['source']}": r['id'] for _,r in df.iterrows()}
        default_idx = 0
        selected_id = st.session_state.get("selected_article_id")
        if selected_id in options.values():
            default_idx = list(options.values()).index(selected_id)
        selected_label = st.selectbox("Choose a news story", list(options.keys()), index=default_idx)
        article_id = options[selected_label]
        article = df[df.id == article_id].iloc[0].to_dict()
        with st.expander("Source details", expanded=True):
            st.write(article["summary"])
            st.markdown(f"[Read source article]({article['link']})")
        x1,x2,x3 = st.columns(3)
        with x1: audience = st.selectbox("Target reader", ["CIOs and CTOs","IT directors and technology leaders","Enterprise business leaders","Industry-specific decision makers","Mixed enterprise audience"])
        with x2: tone = st.selectbox("Editorial tone", ["Insightful and authoritative","Practical and analytical","Executive thought leadership","Clear and educational"])
        with x3: target_words = st.selectbox("Target word count", [800,1000,1200,1500,1800], index=2)
        primary_keyword = st.text_input("Primary SEO keyword (optional)")
        extra = st.text_area("Additional editorial instructions (optional)", placeholder="Example: Focus on healthcare CIOs, include practical implementation considerations...")
        if st.button("✨ Generate SEO blog draft", type="primary", use_container_width=True):
            if not api_key:
                st.error("Add your OpenAI API key in the sidebar to generate content.")
            else:
                try:
                    with st.spinner("Writing and structuring your blog draft..."):
                        result = generate_blog(article, api_key, model, audience, tone, target_words, primary_keyword, extra)
                        save_draft(article_id, result)
                        st.session_state["generated_blog"] = result
                        st.session_state["generated_article_id"] = article_id
                    st.success("Draft generated and saved locally. Review all editorial checks before publishing.")
                except Exception as e:
                    st.error(f"Generation failed: {e}")
        result = st.session_state.get("generated_blog")
        if result:
            st.divider()
            st.markdown(f"## {result.get('title','Untitled')}")
            st.markdown(f"**Meta title:** {result.get('meta_title','')}")
            st.markdown(f"**Meta description:** {result.get('meta_description','')}")
            st.markdown(f"**Slug:** `{result.get('slug','')}`")
            st.markdown(f"**Primary keyword:** {result.get('primary_keyword','')}")
            st.markdown("**Secondary keywords:** " + ", ".join(result.get("secondary_keywords",[])))
            st.markdown("---")
            st.markdown(result.get("content_markdown",""))
            with st.expander("FAQ suggestions"):
                for item in result.get("faq",[]):
                    st.markdown(f"**{item.get('question','')}**\n\n{item.get('answer','')}")
            with st.expander("Internal links"):
                for item in result.get("suggested_internal_links",[]):
                    st.markdown(f"- [{item.get('anchor_text','')}]({item.get('URL','')})")
            with st.expander("Editorial checks — complete before publishing", expanded=True):
                for item in result.get("editorial_checks",[]): st.markdown(f"- [ ] {item}")
            st.markdown("**LinkedIn post**")
            st.write(result.get("social_linkedin",""))
            md = f"""# {result.get('title','')}

**Meta title:** {result.get('meta_title','')}  
**Meta description:** {result.get('meta_description','')}  
**Slug:** {result.get('slug','')}  
**Primary keyword:** {result.get('primary_keyword','')}

{result.get('content_markdown','')}

## FAQs
""" + "\n\n".join([f"### {x.get('question','')}\n{x.get('answer','')}" for x in result.get("faq",[])])
            st.download_button("⬇️ Download blog as Markdown", md, file_name=(result.get("slug") or "connexr-blog")+".md", mime="text/markdown")
            st.download_button("⬇️ Download SEO package as JSON", json.dumps(result,indent=2), file_name="connexr-seo-package.json", mime="application/json")

with tab3:
    st.subheader("Saved content drafts")
    conn = db()
    drafts = pd.read_sql_query("SELECT * FROM drafts ORDER BY created_at DESC", conn)
    conn.close()
    if drafts.empty:
        st.info("Generated drafts will appear here.")
    else:
        for _,d in drafts.iterrows():
            with st.expander(f"{d['title']} · {d['created_at'][:16]}"):
                st.markdown(f"**Meta title:** {d['meta_title']}")
                st.markdown(f"**Meta description:** {d['meta_description']}")
                st.markdown(f"**Slug:** `{d['slug']}`")
                st.markdown(d["content"])
                st.download_button("Download Markdown", d["content"], file_name=(d["slug"] or "blog")+".md", key=f"dl_{d['id']}")

st.divider()
st.caption("Editorial rule: this tool creates first drafts, not publish-ready verified reporting. Check original sources, dates, statistics, quotes, legal/regulatory claims and ConnexR service references before publishing.")
