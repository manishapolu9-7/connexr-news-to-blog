import streamlit as st
import feedparser
import requests
import pandas as pd
import re, json, time, hashlib, io
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
from email.utils import parsedate_to_datetime

st.set_page_config(page_title="ConnexR Content Intelligence", page_icon="🧭", layout="wide")

# ---------------- ConnexR knowledge base ----------------
SOLUTIONS = {
    "Custom AI Solutions": ["custom ai", "enterprise ai", "generative ai", "genai", "ai agent", "agentic ai",
        "ai automation", "workflow automation", "machine learning", "llm", "rag", "ai integration"],
    "AIOps & IT Operations": ["aiops", "observability", "incident management", "it operations", "site reliability",
        "sre", "monitoring", "root cause analysis", "predictive maintenance", "it service management"],
    "Digital & AI Transformation": ["digital transformation", "ai transformation", "enterprise transformation",
        "ai adoption", "ai governance", "responsible ai", "change management", "process transformation"],
    "Cloud & AI Infrastructure": ["cloud infrastructure", "cloud modernization", "hybrid cloud", "multi cloud",
        "gpu", "ai infrastructure", "cloud native", "kubernetes", "mlops", "model deployment"],
    "Enterprise Systems Modernization": ["legacy modernization", "legacy systems", "application modernization",
        "enterprise systems", "erp", "api integration", "systems integration", "data modernization",
        "microservices", "mainframe"]
}
INDUSTRIES = {
    "Healthcare": ["healthcare", "hospital", "clinical", "patient", "health tech", "medical"],
    "Banking & Financial Services": ["bank", "banking", "financial services", "finance", "capital markets"],
    "FinTech": ["fintech", "payments", "digital wallet", "lending", "payment"],
    "Insurance": ["insurance", "insurtech", "underwriting", "claims"],
    "Manufacturing": ["manufacturing", "factory", "industrial", "supply chain", "industrial iot"],
    "Retail & E-commerce": ["retail", "ecommerce", "e-commerce", "merchant", "customer experience"],
    "Education": ["education", "edtech", "university", "learning"],
    "Transportation": ["transportation", "airline", "aviation", "logistics", "fleet"],
    "Technology & Software": ["software", "saas", "technology", "developer", "enterprise software"]
}
BUYER_TERMS = ["cio", "cto", "ciso", "chief data officer", "it director", "enterprise", "business leader",
               "technology leader", "digital leader", "engineering", "operations", "decision maker"]
PROBLEM_TERMS = ["risk", "cost", "security", "compliance", "governance", "integration", "scalability",
                 "reliability", "downtime", "productivity", "efficiency", "legacy", "complexity",
                 "skills gap", "data quality", "implementation", "deployment", "roi", "workforce"]
OFFICIAL_FEEDS = [
    ("OpenAI News", "https://openai.com/news/rss.xml", "Official announcement"),
    ("Google AI Blog", "https://blog.google/technology/ai/rss/", "Official announcement"),
    ("Microsoft Tech Community", "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=MicrosoftMechanicsBlog", "Official announcement"),
    ("AWS Architecture Blog", "https://aws.amazon.com/blogs/architecture/feed/", "Official announcement"),
    ("NVIDIA Blog", "https://blogs.nvidia.com/feed/", "Official announcement"),
    ("arXiv AI", "https://export.arxiv.org/rss/cs.AI", "Research"),
    ("arXiv Software Engineering", "https://export.arxiv.org/rss/cs.SE", "Research"),
    ("Reddit Machine Learning", "https://www.reddit.com/r/MachineLearning/.rss", "Community"),
    ("Reddit Artificial Intelligence", "https://www.reddit.com/r/artificial/.rss", "Community"),
    ("Reddit DevOps", "https://www.reddit.com/r/devops/.rss", "Community"),
]
DEFAULT_COMPETITORS = ["accenture.com", "deloitte.com", "capgemini.com", "thoughtworks.com", "cognizant.com"]

st.markdown("""
<style>
.block-container{padding-top:1.5rem;padding-bottom:2rem}
div[data-testid="stMetric"]{background:rgba(120,120,120,.08);padding:12px;border-radius:12px}
.small-muted{color:gray;font-size:.85rem}
</style>
""", unsafe_allow_html=True)

def clean_html(s):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    return re.sub(r"\s+", " ", s).strip()

def parse_date(entry):
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if val:
            try:
                dt = parsedate_to_datetime(val)
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try: return datetime(*val[:6], tzinfo=timezone.utc)
            except Exception: pass
    return None

def google_news_url(query, days):
    return "https://news.google.com/rss/search?q=" + quote_plus(query + f" when:{days}d") + "&hl=en-US&gl=US&ceid=US:en"

def fetch_feed(name, url, category, timeout=12):
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0 ConnexRContentIntelligence/1.0"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        rows=[]
        for e in parsed.entries[:60]:
            title=clean_html(e.get("title",""))
            link=e.get("link","")
            summary=clean_html(e.get("summary","") or e.get("description",""))
            dt=parse_date(e)
            if title and link:
                rows.append({"title":title,"url":link,"summary":summary,"published":dt,
                             "source":name,"source_type":category})
        return rows, None
    except Exception as ex:
        return [], f"{name}: {str(ex)[:160]}"

def relevance(article, selected_solutions, selected_industries, custom_terms):
    text=(article["title"]+" "+article["summary"]).lower()
    sol_hits={s:[k for k in SOLUTIONS[s] if k in text] for s in selected_solutions}
    sol_hits={k:v for k,v in sol_hits.items() if v}
    ind_hits={s:[k for k in INDUSTRIES[s] if k in text] for s in selected_industries}
    ind_hits={k:v for k,v in ind_hits.items() if v}
    custom_hits=[k for k in custom_terms if k.lower() in text]
    buyer_hits=[k for k in BUYER_TERMS if k in text]
    problem_hits=[k for k in PROBLEM_TERMS if k in text]
    # Strong penalty for broad AI-only matches with no enterprise/solution evidence.
    score=min(100, len(sol_hits)*22 + min(18,sum(map(len,sol_hits.values()))*5)
              + min(15,len(ind_hits)*8) + min(15,len(custom_hits)*7)
              + min(15,len(buyer_hits)*5) + min(15,len(problem_hits)*3))
    if not sol_hits: score=min(score,24)
    if not (buyer_hits or problem_hits): score=max(0,score-8)
    reasons=[]
    if sol_hits: reasons.append("Solution fit: "+", ".join(sol_hits.keys()))
    if ind_hits: reasons.append("Industry: "+", ".join(ind_hits.keys()))
    if custom_hits: reasons.append("Your keywords: "+", ".join(custom_hits[:5]))
    if buyer_hits: reasons.append("Enterprise audience signals: "+", ".join(buyer_hits[:4]))
    if problem_hits: reasons.append("Business problem signals: "+", ".join(problem_hits[:5]))
    return score, sol_hits, ind_hits, custom_hits, buyer_hits, problem_hits, reasons

def expand_autocomplete(seed):
    url="https://suggestqueries.google.com/complete/search?client=firefox&q="+quote_plus(seed)
    try:
        r=requests.get(url,timeout=8,headers={"User-Agent":"Mozilla/5.0"})
        r.raise_for_status()
        data=r.json()
        return data[1] if len(data)>1 else []
    except Exception:
        return []

def topic_angles(article, solution, industries, custom_terms, problem_hits, objectives):
    title=article["title"]
    title_l=title.lower()
    anchor=solution or "enterprise technology"
    industry=industries[0] if industries else "enterprise teams"
    problem=problem_hits[0] if problem_hits else "implementation challenges"
    # Angle templates transform the signal into a problem-led editorial question, not headline paraphrases.
    return [
      ("Business challenge", f"What {industry} Leaders Need to Solve Before Scaling {anchor}",
       "Explain the operational and organisational barriers behind the development.", "Traffic + thought leadership"),
      ("Implementation framework", f"A Practical Enterprise Framework for {anchor}: From Evaluation to Operations",
       "Give readers a decision framework, readiness checks and implementation sequence.", "Traffic + lead generation"),
      ("Risk and governance", f"The Hidden Risks of {anchor}: Security, Governance and Operational Accountability",
       "Explore controls, ownership, risk boundaries and measurable safeguards.", "Thought leadership + leads"),
      ("Buyer decision", f"Build, Buy or Integrate? How Enterprises Should Evaluate {anchor}",
       "Help technology buyers compare approaches, trade-offs and evaluation criteria.", "Lead generation"),
      ("Operational impact", f"How {anchor} Changes Enterprise Operations: Reliability, Cost and Measurable Outcomes",
       "Connect technology change to business outcomes and operational metrics.", "Traffic + lead generation")
    ]

def gemini_analyse(api_key, model, article, context):
    if not api_key: return None, "No free-tier Gemini key configured; using transparent rule-based analysis."
    prompt=f"""You are a B2B enterprise technology research analyst for ConnexR.
Analyse the supplied article and return valid JSON only with keys:
relevance_verdict (high/medium/low), event_summary (2 sentences), enterprise_implication (2-3 sentences),
buyer_problem (one clear problem), affected_roles (array), conn exr_solution_fit (array),
why_now (one sentence), evidence_gaps (array), original_content_angles (array of 3 objects with title, angle, objective).
Do not invent facts. If article does not materially connect to ConnexR enterprise AI, AIOps, digital transformation,
cloud/AI infrastructure or systems modernization, say low and explain. Never simply rewrite the headline.
Article title: {article['title']}
Article summary: {article['summary'][:3500]}
ConnexR context: {context}"""
    prompt=prompt.replace("conn exr_solution_fit","connexr_solution_fit")
    try:
        endpoint=f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        body={"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"temperature":0.25,"responseMimeType":"application/json"}}
        r=requests.post(endpoint,json=body,timeout=45)
        r.raise_for_status()
        txt=r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt), None
    except Exception as ex:
        return None, f"Gemini analysis unavailable: {str(ex)[:180]}. Rule-based analysis used."

def make_prompt(topic, article, primary, related, question, solution, objective, audience, angle):
    return f"""Act as a senior B2B enterprise technology researcher and SEO/GEO/AEO content strategist writing for ConnexR.

Do NOT draft the blog. Produce a research-backed editorial brief and recommendations for a human writer.

APPROVED TOPIC: {topic}
EDITORIAL ANGLE: {angle}
BUSINESS OBJECTIVE: {objective}
TARGET AUDIENCE: {audience}
CONNEXR SERVICE CONNECTION: {solution}
PRIMARY KEYWORD: {primary}
RELATED KEYWORDS: {', '.join(related)}
ANSWER-ENGINE QUESTION: {question}
SOURCE SIGNAL: {article['title']}
SOURCE URL: {article['url']}
SOURCE SUMMARY: {article['summary'][:1800]}

Research requirements:
1. Verify the source and distinguish confirmed facts from interpretation.
2. Explain the enterprise problem, who experiences it, and its operational/business consequences.
3. Develop a differentiated ConnexR point of view without making unsupported claims about ConnexR capabilities or customers.
4. Identify what additional primary sources, statistics and expert evidence the writer should verify.
5. Recommend an SEO title, meta description, URL slug, H1/H2 outline, internal-link themes and 4-6 FAQs.
6. Include GEO recommendations: clear entity definitions, named sources, evidence, context and concise factual passages.
7. Include AEO recommendations: answer the main question directly near the beginning, then support it with detail.
8. Avoid keyword stuffing, generic AI commentary, fabricated statistics and headline rewriting.
9. End with a factual verification checklist.
Return a structured editorial brief only. Do not write the complete article."""

# ---------------- UI ----------------
st.title("🧭 ConnexR Content Intelligence")
st.caption("Research relevant enterprise developments → identify business problems → prioritise content opportunities.")
with st.sidebar:
    st.header("Research configuration")
    selected_solutions=st.multiselect("ConnexR solution pillars",list(SOLUTIONS),default=list(SOLUTIONS))
    selected_industries=st.multiselect("Target industries",list(INDUSTRIES),default=list(INDUSTRIES))
    custom_raw=st.text_area("Your custom keywords",placeholder="enterprise AI governance, AI workflow automation, legacy modernization",height=90)
    custom_terms=[x.strip() for x in re.split(r"[,;\n]",custom_raw) if x.strip()]
    competitor_domains=st.text_area("Competitor domains (optional)",placeholder="competitor.com\nanothercompetitor.com",height=75)
    days=st.selectbox("Publication date window",[1,3,7,14,30],index=2,format_func=lambda x:f"Last {x} day(s)")
    min_score=st.slider("Minimum ConnexR relevance score",0,90,35,5)
    max_items=st.slider("Maximum items per source",10,60,30,5)
    st.divider()
    st.subheader("Optional free contextual analysis")
    st.caption("Google AI Studio offers a limited free tier for eligible models. A key is optional; the app remains usable without it. Check current terms and limits before use.")
    gemini_key=st.text_input("Gemini API key (optional)",type="password")
    gemini_model=st.selectbox("Free-tier model",["gemini-2.5-flash","gemini-2.0-flash"],index=0)
    st.caption("Free-tier availability and model access can change. Do not enter confidential company or customer information.")

tabs=st.tabs(["Overview","News Intelligence","Content Opportunities","Keyword Intelligence","Editorial Prompt & Export","Methodology"])

with tabs[0]:
    st.subheader("Your research workspace")
    st.write("Release 1 focuses on source-grounded discovery and topic quality. No CMS connection and no automatic blog writing.")
    c1,c2,c3=st.columns(3)
    c1.metric("Solution pillars",len(selected_solutions))
    c2.metric("Target industries",len(selected_industries))
    c3.metric("Custom keywords",len(custom_terms))
    st.info("Start in **News Intelligence** and click **Run research**. The system searches public feeds, applies the selected date window, scores ConnexR fit and builds editorial opportunities.")
    st.markdown("**Research sources included**")
    st.write("Google News search feeds · Official technology/company RSS feeds · arXiv research feeds · Reddit community RSS · Competitor-domain news search · Google autocomplete.")
    st.warning("Not every named publisher, regulator or competitor exposes an accessible public RSS/API. Release 1 uses accessible feeds and indexed search results; it does not claim exhaustive coverage of the web.")

with tabs[1]:
    st.subheader("News Intelligence")
    st.write("Stories are scored against selected ConnexR services, industries, custom keywords, enterprise roles and business-problem signals.")
    query_terms=[]
    for s in selected_solutions: query_terms += SOLUTIONS[s][:5]
    for i in selected_industries: query_terms += INDUSTRIES[i][:2]
    query_terms += custom_terms[:12]
    query_terms=list(dict.fromkeys(query_terms))
    research_queries=[
      ("Enterprise AI & agentic systems","(enterprise AI OR agentic AI OR AI agents) (governance OR deployment OR business OR operations)"),
      ("AIOps & operational resilience","(AIOps OR observability OR IT operations) (enterprise OR reliability OR incident OR automation)"),
      ("Cloud & AI infrastructure","(AI infrastructure OR cloud modernization OR GPU infrastructure OR MLOps) enterprise"),
      ("Systems modernization","(legacy modernization OR application modernization OR enterprise integration)"),
      ("Regulation & governance","(AI regulation OR AI governance OR data protection) enterprise"),
      ("Industry transformation","(healthcare OR banking OR manufacturing OR insurance OR retail) (enterprise AI OR automation OR modernization)")
    ]
    if custom_terms:
        research_queries.append(("Your keyword watchlist"," OR ".join(custom_terms[:8])))
    if selected_solutions:
        st.caption("The query set adapts to your selected service pillars and custom keywords.")
    if st.button("🔎 Run research",type="primary",use_container_width=True):
        all_rows=[]; errors=[]
        progress=st.progress(0)
        tasks=[]
        for label,q in research_queries:
            tasks.append((label,google_news_url(q,days),"Google News"))
        for name,url,cat in OFFICIAL_FEEDS:
            tasks.append((name,url,cat))
        domains=[x.strip().replace("https://","").replace("http://","").strip("/") for x in competitor_domains.splitlines() if x.strip()]
        for d in domains:
            tasks.append((f"Competitor search: {d}",google_news_url(f"site:{d} (AI OR cloud OR modernization OR automation)",days),"Competitor indexed content"))
        for idx,(name,url,cat) in enumerate(tasks):
            rows,err=fetch_feed(name,url,cat)
            all_rows.extend(rows[:max_items])
            if err: errors.append(err)
            progress.progress((idx+1)/max(1,len(tasks)))
            time.sleep(.03)
        cutoff=datetime.now(timezone.utc)-timedelta(days=days)
        filtered=[]
        seen=set()
        for a in all_rows:
            if not a["published"] or a["published"]<cutoff: continue
            key=hashlib.md5((a["title"].lower().strip()+a["url"]).encode()).hexdigest()
            if key in seen: continue
            seen.add(key)
            score,sol,ind,custom,buyer,problem,reasons=relevance(a,selected_solutions,selected_industries,custom_terms)
            a.update({"score":score,"solution_hits":sol,"industry_hits":ind,"custom_hits":custom,
                      "buyer_hits":buyer,"problem_hits":problem,"reasons":reasons})
            if score>=min_score: filtered.append(a)
        filtered.sort(key=lambda x:(x["score"],x["published"]),reverse=True)
        st.session_state["articles"]=filtered
        st.session_state["research_errors"]=errors
        st.session_state["research_at"]=datetime.now().strftime("%Y-%m-%d %H:%M")
    if "articles" in st.session_state:
        articles=st.session_state["articles"]
        m1,m2,m3=st.columns(3)
        m1.metric("Qualified articles",len(articles))
        m2.metric("High relevance (70+)",sum(a["score"]>=70 for a in articles))
        m3.metric("Research errors",len(st.session_state.get("research_errors",[])))
        st.caption("Last run: "+st.session_state.get("research_at",""))
        if st.session_state.get("research_errors"):
            with st.expander("Source availability warnings"):
                for e in st.session_state["research_errors"]: st.write("• "+e)
        if not articles: st.warning("No stories passed the relevance and date filters. Try a broader date range or lower relevance threshold. Do not lower it just to increase volume.")
        for idx,a in enumerate(articles):
            with st.container(border=True):
                top=st.columns([5,1])
                top[0].markdown(f"**{a['title']}**")
                top[1].metric("Fit",a["score"])
                st.caption(f"{a['source']} · {a['source_type']} · {a['published'].astimezone().strftime('%d %b %Y %H:%M %Z')}")
                st.write(a["summary"][:500] or "No description supplied by feed.")
                if a["reasons"]: st.caption(" · ".join(a["reasons"]))
                st.markdown(f"[Open original source]({a['url']})")
                if st.button("Analyse this development",key=f"analyse_{idx}"):
                    st.session_state["selected_article"]=idx
                    st.session_state["selected_tab"]="Content Opportunities"
                    st.rerun()
    else:
        st.info("No research has been run in this session yet.")

with tabs[2]:
    st.subheader("Content Opportunity Engine")
    articles=st.session_state.get("articles",[])
    if not articles:
        st.info("Run News Intelligence first. Topics are generated only from qualified source signals.")
    else:
        choices=[f"{a['score']} · {a['title'][:100]}" for a in articles]
        default_idx=min(st.session_state.get("selected_article",0),len(articles)-1)
        ai_idx=st.selectbox("Select a qualified research signal",range(len(articles)),index=default_idx,format_func=lambda i:choices[i])
        article=articles[ai_idx]
        st.markdown(f"**Source:** [{article['title']}]({article['url']})")
        st.write(article["summary"][:900])
        fit_solutions=list(article["solution_hits"].keys())
        fit_industries=list(article["industry_hits"].keys())
        st.markdown("**What the system detected**")
        st.write({"ConnexR solutions":fit_solutions,"Industries":fit_industries,
                  "Enterprise roles":article["buyer_hits"],"Problem signals":article["problem_hits"]})
        context="; ".join(selected_solutions)+" | Target industries: "+", ".join(selected_industries)
        if st.button("Run contextual analysis",type="primary"):
            result,err=gemini_analyse(gemini_key,gemini_model,article,context)
            st.session_state["context_analysis"]=result
            st.session_state["context_analysis_error"]=err
            st.session_state["context_article_url"]=article["url"]
        if st.session_state.get("context_analysis_error"):
            st.caption(st.session_state["context_analysis_error"])
        analysis=st.session_state.get("context_analysis")
        if analysis and st.session_state.get("context_article_url")==article["url"]:
            st.markdown("#### Contextual research findings")
            for key,label in [("event_summary","What happened"),("enterprise_implication","Enterprise implication"),("buyer_problem","Buyer problem"),("why_now","Why now")]:
                if analysis.get(key):
                    st.markdown(f"**{label}**")
                    st.write(analysis[key])
            if analysis.get("evidence_gaps"):
                st.markdown("**Evidence to verify**")
                st.write(analysis["evidence_gaps"])
        st.divider()
        objective=st.selectbox("Primary objective for this topic",["Organic traffic","Enterprise lead generation","Thought leadership"],index=0)
        audience=st.selectbox("Target audience",["CIOs and CTOs","CISOs and risk leaders","IT directors and operations leaders","Enterprise architects","Data and AI leaders","Business transformation leaders"])
        solution_options=fit_solutions or selected_solutions
        solution=st.selectbox("ConnexR service connection",solution_options if solution_options else list(SOLUTIONS))
        angles=topic_angles(article,solution,fit_industries,custom_terms,article["problem_hits"],[objective])
        st.markdown("#### Recommended editorial opportunities")
        rows=[]
        for typ,title,angle,obj in angles:
            rows.append({"Opportunity type":typ,"Recommended topic":title,"Editorial angle":angle,"Best fit":obj})
        st.session_state["topic_rows"]=rows
        for n,row in enumerate(rows):
            with st.container(border=True):
                st.markdown(f"**{n+1}. {row['Recommended topic']}**")
                st.caption(f"{row['Opportunity type']} · {row['Best fit']}")
                st.write(row["Editorial angle"])
                if st.button("Use this topic",key=f"use_topic_{n}"):
                    st.session_state["chosen_topic"]=row["Recommended topic"]
                    st.session_state["chosen_angle"]=row["Editorial angle"]
                    st.session_state["chosen_objective"]=objective
                    st.session_state["chosen_audience"]=audience
                    st.session_state["chosen_solution"]=solution
                    st.session_state["chosen_article"]=article
                    st.success("Topic selected. Continue in Editorial Prompt & Export.")
        if analysis and analysis.get("original_content_angles"):
            with st.expander("Additional AI-generated angles (free-tier analysis)"):
                st.json(analysis["original_content_angles"])

with tabs[3]:
    st.subheader("Keyword Intelligence")
    st.write("Autocomplete suggestions are query ideas, not verified search-volume or difficulty metrics.")
    seed=st.text_input("Enter a keyword or topic seed",value=custom_terms[0] if custom_terms else "")
    if st.button("Discover related keywords",disabled=not seed.strip()):
        suggestions=expand_autocomplete(seed.strip())
        modifiers=["how to","what is","why does","best practices","implementation","framework","checklist",
                   "cost","benefits","challenges","vs","for enterprises","security","governance","ROI"]
        st.session_state["keyword_suggestions"]=list(dict.fromkeys(suggestions+ [f"{m} {seed.strip()}" for m in modifiers]))
        st.session_state["keyword_seed"]=seed.strip()
    if st.session_state.get("keyword_suggestions"):
        st.markdown(f"**Suggestions for:** {st.session_state.get('keyword_seed')}")
        df=pd.DataFrame({"Keyword":st.session_state["keyword_suggestions"],
                         "Source":["Google autocomplete" if i<len(expand_autocomplete(st.session_state.get("keyword_seed",""))) else "Question / intent modifier" for i,_ in enumerate(st.session_state["keyword_suggestions"])]})
        st.dataframe(df,use_container_width=True,hide_index=True)
        st.download_button("Download keyword suggestions CSV",df.to_csv(index=False).encode(), "connexr_keyword_suggestions.csv","text/csv")
    st.markdown("#### ConnexR solution keyword seeds")
    for sol,terms in SOLUTIONS.items():
        with st.expander(sol):
            st.write(", ".join(terms))

with tabs[4]:
    st.subheader("Editorial Prompt & Export")
    if "chosen_topic" not in st.session_state:
        st.info("Choose a recommended topic in Content Opportunities to prepare its research and writing prompt.")
    else:
        topic=st.text_input("Selected topic",value=st.session_state["chosen_topic"])
        angle=st.text_area("Editorial angle",value=st.session_state.get("chosen_angle",""))
        objective=st.selectbox("Objective",["Organic traffic","Enterprise lead generation","Thought leadership"],
            index=["Organic traffic","Enterprise lead generation","Thought leadership"].index(st.session_state.get("chosen_objective","Organic traffic")))
        audience=st.text_input("Audience",value=st.session_state.get("chosen_audience","CIOs and CTOs"))
        solution=st.text_input("ConnexR service",value=st.session_state.get("chosen_solution",""))
        primary=st.text_input("Primary keyword",value=(custom_terms[0] if custom_terms else ""))
        related_raw=st.text_area("Related keywords (comma-separated)",value="")
        question=st.text_input("AEO target question",value="How should enterprises approach this challenge?")
        article=st.session_state.get("chosen_article",st.session_state.get("articles",[{"title":"","url":"","summary":""}])[0])
        related=[x.strip() for x in related_raw.split(",") if x.strip()]
        prompt=make_prompt(topic,article,primary,related,question,solution,objective,audience,angle)
        st.text_area("Copy-ready research and writing prompt (not a blog)",value=prompt,height=420)
        st.download_button("Download prompt as TXT",prompt,"connexr_editorial_research_prompt.txt","text/plain")
        if st.session_state.get("articles"):
            export=[]
            for a in st.session_state["articles"]:
                export.append({"title":a["title"],"url":a["url"],"published":a["published"].isoformat(),
                               "source":a["source"],"source_type":a["source_type"],"relevance_score":a["score"],
                               "solution_fit":", ".join(a["solution_hits"].keys()),
                               "industry_fit":", ".join(a["industry_hits"].keys()),
                               "relevance_reasons":"; ".join(a["reasons"])})
            out=pd.DataFrame(export)
            st.download_button("Export qualified research (CSV)",out.to_csv(index=False).encode(),"connexr_research_export.csv","text/csv")
            excel_buffer=io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
                out.to_excel(writer, index=False, sheet_name="Qualified Research")
            st.download_button("Export qualified research (Excel)",excel_buffer.getvalue(),
                               "connexr_research_export.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
with tabs[5]:
    st.subheader("Methodology, limitations and trust")
    st.markdown("""
**What the relevance score means**
- The score is a transparent rules-based match across ConnexR services, industries, user keywords, enterprise roles and business-problem language.
- A low score means the article lacks sufficient evidence of ConnexR fit. It is not a judgement of the article's general quality.
- The score is not an AI confidence score and should not be presented as one.

**Contextual analysis**
- Without a model key, the app uses explicit matching and editorial frameworks.
- With an optional Google AI Studio key, it requests a structured contextual analysis from an eligible Gemini model. Free-tier model availability, quotas and terms may change.
- AI analysis is advisory. Verify every factual claim against the original source.

**Coverage**
- RSS, Google News RSS, Google autocomplete and Reddit feeds are best-effort public endpoints.
- Search suggestions do not provide search volume, keyword difficulty, CPC or ranking probability.
- This release does not scrape login-only sources, bypass access controls, or guarantee exhaustive coverage.
- It does not connect to ConnexR's CMS, publish content, or generate complete blog articles.
""")
    st.markdown("[Gemini API free-tier details](https://ai.google.dev/gemini-api/docs/pricing) · [Gemini API documentation](https://ai.google.dev/gemini-api/docs)")

st.caption("ConnexR Content Intelligence · Release 1 · Research support only. Human review required before publication.")
