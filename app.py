import pathlib
import re, json, sqlite3, hashlib
from datetime import datetime, timezone
from urllib.parse import quote_plus
import feedparser
import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup

ROOT=pathlib.Path(__file__).parent
DB=ROOT/"connexr_ideation.db"
st.set_page_config(page_title="ConnexR News Ideation Studio",page_icon="💡",layout="wide")

SERVICES={
"Custom AI Solutions":{"queries":["enterprise AI agents","generative AI enterprise adoption","LLM deployment business"],"keywords":["enterprise AI solutions","AI agent development","generative AI for business","enterprise generative AI","AI workflow automation","custom AI development"],"questions":["How can enterprises implement AI agents safely?","What are the benefits of custom AI solutions?","How do businesses move generative AI from pilot to production?"],"angles":["implementation roadmap","business value and ROI","security and governance","build vs buy considerations","industry use cases"]},
"AIOps & IT Operations":{"queries":["AIOps enterprise IT operations","AI IT operations automation","observability incident management"],"keywords":["AIOps solutions","AI for IT operations","IT operations automation","AI incident management","predictive IT operations","AIOps platform"],"questions":["What is AIOps and how does it work?","How does AI reduce IT incident response time?","How can enterprises automate IT operations?"],"angles":["incident prevention","operational efficiency","observability and monitoring","implementation checklist","measuring MTTR and service reliability"]},
"Digital & AI Transformation":{"queries":["enterprise AI transformation","AI adoption at scale","responsible AI governance"],"keywords":["enterprise AI transformation","digital transformation strategy","AI adoption strategy","responsible AI governance","AI transformation roadmap","enterprise AI implementation"],"questions":["How should enterprises build an AI transformation roadmap?","Why do enterprise AI pilots fail to scale?","How can businesses measure digital transformation success?"],"angles":["strategy and operating model","pilot-to-production gap","change management","governance and risk","business outcome measurement"]},
"Cloud & AI Infrastructure":{"queries":["AI infrastructure cloud enterprise","GPU cloud infrastructure","cloud cost optimization enterprise"],"keywords":["AI infrastructure","enterprise cloud modernization","GPU infrastructure for AI","cloud cost optimization","MLOps infrastructure","AI cloud infrastructure"],"questions":["What infrastructure do enterprises need for generative AI?","How can businesses optimize cloud costs for AI workloads?","What should CIOs consider when scaling AI infrastructure?"],"angles":["architecture choices","cost and performance","scalability","security and resilience","cloud readiness checklist"]},
"Enterprise Systems Modernization":{"queries":["ERP modernization enterprise","legacy systems modernization","enterprise API integration"],"keywords":["enterprise systems modernization","legacy system modernization","ERP modernization strategy","enterprise application integration","API integration services","modernizing legacy applications"],"questions":["How can enterprises modernize legacy systems without disruption?","What are the benefits of enterprise application modernization?","How should businesses plan an ERP modernization project?"],"angles":["modernization roadmap","integration and interoperability","risk reduction","cloud migration","business continuity"]}
}
INDUSTRIES=["Healthcare","FinTech","Banking & Financial Services","Insurance","Manufacturing","Retail & E-Commerce","Education & EdTech","Transportation & Airlines","Technology & Software"]

def conn():
 c=sqlite3.connect(DB,check_same_thread=False)
 c.execute("""CREATE TABLE IF NOT EXISTS stories(id TEXT PRIMARY KEY,title TEXT,link TEXT,source TEXT,published TEXT,summary TEXT,service TEXT,industry TEXT,score INTEGER,created_at TEXT)""")
 c.execute("""CREATE TABLE IF NOT EXISTS ideas(id TEXT PRIMARY KEY,story_id TEXT,topic TEXT,service TEXT,industry TEXT,primary_kw TEXT,secondary_kws TEXT,intent TEXT,angle TEXT,aeo TEXT,prompt TEXT,priority TEXT,source_url TEXT,created_at TEXT)""")
 c.commit();return c

def clean(s): return BeautifulSoup(s or "","html.parser").get_text(" ",strip=True)
def rss(q,days): return f"https://news.google.com/rss/search?q={quote_plus(q+' when:'+str(days)+'d')}&hl=en-US&gl=US&ceid=US:en"
def discover(days,selected_services,selected_industries,limit):
 out=[];seen=set()
 qs=[(q,s,"") for s in selected_services for q in SERVICES[s]["queries"]]+[(f"{i} enterprise AI technology automation modernization","",i) for i in selected_industries]
 for q,s,i in qs:
  try:
   for e in feedparser.parse(rss(q,days)).entries[:limit]:
    title,link=clean(e.get("title","")),e.get("link","")
    if not title or not link: continue
    sid=hashlib.sha1(link.encode()).hexdigest()[:18]
    if sid in seen: continue
    seen.add(sid); summary=clean(e.get("summary",""))[:1000]; blob=(title+" "+summary).lower()
    score=sum(2 for w in ["enterprise","AI","automation","cloud","security","modernization","operations","governance","infrastructure","business","deployment"] if w.lower() in blob)+(3 if s else 0)+(2 if i else 0)
    out.append(dict(id=sid,title=title,link=link,source=e.get("source",{}).get("title","Google News"),published=e.get("published",""),summary=summary,service=s,industry=i,score=min(score,30)))
  except Exception: pass
 return sorted(out,key=lambda x:x["score"],reverse=True)
def save_stories(rows):
 c=conn()
 for r in rows:c.execute("INSERT OR IGNORE INTO stories VALUES(?,?,?,?,?,?,?,?,?,?)",(r["id"],r["title"],r["link"],r["source"],r["published"],r["summary"],r["service"],r["industry"],r["score"],datetime.now(timezone.utc).isoformat()))
 c.commit();c.close()
def get_stories():
 c=conn();d=pd.read_sql_query("SELECT * FROM stories ORDER BY score DESC,created_at DESC",c);c.close();return d
def build_prompt(topic,service,industry,primary,secondary,angle,question,news_title,news_url):
 return f"""Act as a senior B2B technology editor and SEO, GEO and AEO content strategist for ConnexR.

Develop a detailed blog article brief and then write an original, evidence-led article using this news development as the timely hook. Do not copy the news report, imply ConnexR was involved, or invent facts, statistics, quotes, case studies or capabilities. Verify every factual claim against credible sources and clearly distinguish reported facts from analysis.

NEWS HOOK
Headline: {news_title}
Original source: {news_url}

CONTENT BRIEF
Topic: {topic}
ConnexR service line: {service}
Target industry: {industry}
Primary keyword: {primary}
Secondary keyword ideas: {', '.join(secondary)}
Editorial angle: {angle}
AEO question to answer: {question}
Audience: CIOs, CTOs, IT Directors, Enterprise Architects and business decision-makers.

REQUIREMENTS
- Propose an engaging H1 and write a useful, original article of approximately 1,000–1,300 words.
- Address the search intent directly; answer the central question near the beginning.
- Use the primary keyword naturally and incorporate relevant secondary terms without stuffing.
- Use descriptive H2/H3 headings, clear definitions, practical examples and actionable recommendations.
- For GEO: explain named entities and concepts clearly, use verifiable citations, add original synthesis and make important passages independently understandable.
- For AEO: provide a concise direct answer, question-led sections and 4–5 concise FAQs.
- Explain practical implications for {industry} organizations and connect naturally to ConnexR's {service} capabilities without making unsupported product claims.
- Include a source note linking to the original news item and additional authoritative sources consulted.
- If a claim cannot be verified, omit it or mark [EDITOR: VERIFY].
- Do not keyword-stuff, fabricate search volume, or make unsupported ranking promises.

RETURN THESE EDITORIAL ASSETS
1. Blog article with H1/H2/H3 structure.
2. SEO title (aim for 50–60 characters).
3. Meta description (aim for 140–160 characters).
4. Suggested URL slug.
5. Primary and secondary keywords.
6. Search intent and target audience.
7. 4–5 AEO FAQs with concise answers.
8. GEO entity/context checklist.
9. Suggested featured-image concept and descriptive alt text.
10. LinkedIn promotional caption.

This is a writing brief. Research and verify the source before publishing; do not present the news hook as independently verified unless you have checked the original reporting."""

def generate_ideas(row,service,industry,n):
 cfg=SERVICES[service]
 industry_label = industry if industry and industry != "Cross-industry" else "enterprise"
 signal_text = (str(row.get("title","")) + " " + str(row.get("summary",""))).lower()
 stop = {"about","after","before","could","their","there","these","those","which","while","where","would","should","report","reports","latest","says","said","from","with","into","over","under","across","will","have","been","more","than","business","industry","enterprise"}
 signal_words = [w for w in re.findall(r"[a-z0-9]+", signal_text) if len(w)>4 and w not in stop]
 signal_terms = list(dict.fromkeys(signal_words))[:5]
 angle_bank = {
 "Custom AI Solutions": [
 ("From AI pilots to production: the operating decisions enterprises must get right","pilot-to-production strategy","AI implementation roadmap"),
 ("Where should enterprises deploy AI agents first? A use-case prioritisation framework","AI agent use-case prioritisation","AI agent development"),
 ("Build, buy or partner? A decision framework for enterprise AI solutions","enterprise AI build vs buy","custom AI development"),
 ("The enterprise AI readiness gap: data, workflows, skills and governance","enterprise AI readiness","enterprise generative AI"),
 ("How to measure business value from custom AI beyond model accuracy","AI business value measurement","AI workflow automation"),
 ("Human oversight in AI-powered workflows: designing the right control points","human-in-the-loop AI","enterprise AI governance"),
 ("What it takes to integrate generative AI into core business processes","generative AI integration","generative AI for business"),
 ("A practical risk checklist before deploying AI agents at scale","AI agent risk management","AI agent development"),
 ("How industry-specific AI workflows can improve decision-making","industry AI use cases","custom AI solutions"),
 ("The hidden costs of scaling enterprise AI—and how to plan for them","enterprise AI total cost","AI implementation")],
 "AIOps & IT Operations": [
 ("Beyond alert volume: how to build an incident response model that reduces business disruption","AI incident response","AIOps solutions"),
 ("Predictive versus reactive IT operations: what should enterprises measure?","predictive IT operations","AI for IT operations"),
 ("How to reduce alert fatigue without losing critical signals","IT alert fatigue","observability and monitoring"),
 ("A CIO's guide to measuring AIOps value: MTTR, availability and operational toil","AIOps ROI metrics","IT operations automation"),
 ("Connecting observability data to faster, better operational decisions","enterprise observability strategy","AIOps platform"),
 ("The case for automating repetitive IT work—and where human approval still matters","IT operations automation","AI incident management"),
 ("Designing resilient IT operations for complex hybrid environments","hybrid IT resilience","predictive IT operations"),
 ("From incident detection to prevention: a maturity roadmap for IT teams","incident prevention maturity","AIOps solutions"),
 ("How to evaluate an AIOps initiative before investing in a platform","AIOps evaluation framework","AIOps platform"),
 ("Operationalising AI in IT: governance, accountability and safe automation","AI operations governance","AI for IT operations")],
 "Digital & AI Transformation": [
 ("Why enterprise AI transformation is an operating-model challenge, not just a technology project","AI transformation operating model","enterprise AI transformation"),
 ("How to move from isolated AI experiments to an enterprise-wide roadmap","AI pilot to scale","AI transformation roadmap"),
 ("The executive scorecard for measuring digital transformation outcomes","digital transformation KPIs","digital transformation strategy"),
 ("Building an AI adoption roadmap that connects business priorities to delivery","AI adoption roadmap","AI adoption strategy"),
 ("Who owns AI governance? Defining accountability across business and technology teams","enterprise AI accountability","responsible AI governance"),
 ("How to redesign business processes before introducing enterprise AI","AI process redesign","enterprise AI implementation"),
 ("Managing workforce change during enterprise AI adoption","AI change management","AI adoption strategy"),
 ("A practical maturity model for assessing enterprise AI readiness","enterprise AI maturity","enterprise AI transformation"),
 ("Why transformation programmes stall—and how leaders can restore momentum","transformation execution risks","digital transformation strategy"),
 ("Turning AI strategy into measurable business value: a 90-day planning framework","AI value realisation","AI transformation roadmap")],
 "Cloud & AI Infrastructure": [
 ("The enterprise AI infrastructure checklist: compute, data, security and operations","enterprise AI infrastructure planning","AI infrastructure"),
 ("How to control inference costs as generative AI usage grows","generative AI inference costs","cloud cost optimization"),
 ("GPU capacity planning: questions technology leaders should ask before scaling AI","GPU capacity planning","GPU infrastructure for AI"),
 ("Choosing between public cloud, private infrastructure and hybrid AI environments","enterprise AI cloud architecture","AI cloud infrastructure"),
 ("Why FinOps needs to evolve for AI workloads","AI FinOps","cloud cost optimization"),
 ("Building reliable MLOps foundations for models in production","MLOps production readiness","MLOps infrastructure"),
 ("Data residency, security and resilience in enterprise AI infrastructure","AI infrastructure governance","enterprise cloud modernization"),
 ("How to assess cloud readiness before moving AI workloads into production","AI cloud readiness","AI cloud infrastructure"),
 ("Balancing performance, availability and cost in AI platform architecture","AI platform performance","AI infrastructure"),
 ("A practical framework for modernising infrastructure for AI at scale","AI infrastructure modernization","enterprise cloud modernization")],
 "Enterprise Systems Modernization": [
 ("How to modernise legacy systems without disrupting critical business operations","legacy modernization risk","legacy system modernization"),
 ("The business case for application modernization: cost, agility and resilience","application modernization business case","enterprise systems modernization"),
 ("API-led integration: connecting legacy platforms to modern digital services","enterprise API integration","enterprise application integration"),
 ("A phased roadmap for reducing technical debt across enterprise applications","enterprise technical debt","modernizing legacy applications"),
 ("ERP modernization readiness: the questions business and IT leaders must answer","ERP modernization readiness","ERP modernization strategy"),
 ("Cloud migration or re-platforming? A decision framework for legacy workloads","legacy cloud migration strategy","enterprise systems modernization"),
 ("How to protect data quality and continuity during system modernization","modernization data migration","enterprise application integration"),
 ("The role of architecture governance in large-scale modernization programmes","enterprise architecture governance","legacy system modernization"),
 ("When should enterprises replace, refactor or integrate a legacy application?","legacy application strategy","modernizing legacy applications"),
 ("Measuring modernization success beyond project delivery and go-live","modernization outcome metrics","ERP modernization strategy")]
 }
 selected=angle_bank[service]
 ideas=[]
 for i in range(min(n,len(selected))):
  topic,angle,keyword_focus=selected[i]
  primary=cfg["keywords"][i%len(cfg["keywords"])]
  secondary=list(dict.fromkeys([cfg["keywords"][(i+j+1)%len(cfg["keywords"])] for j in range(4)]+[f"{industry_label} {primary}",f"{keyword_focus} for {industry_label}"]))[:8]
  question=cfg["questions"][i%len(cfg["questions"])]
  intent="Informational" if i not in (2,6) else "Commercial investigation"
  connection=("Use the news item as a timely signal, not as a headline to rewrite. Explore what the development may mean "
              f"for {industry_label} organisations, what decision or operational problem it highlights, and what practical "
              f"framework leaders can use. News context terms to investigate: {', '.join(signal_terms[:5]) or service}.")
  prompt=build_prompt(topic,service,industry_label,primary,secondary,angle,question,row["title"],row["link"])
  prompt += "\\n\\nEDITORIAL DIFFERENTIATION\\n" + connection + "\\nThe article must answer a broader business or technology question, not summarise or paraphrase the news story."
  priority="High" if row["score"]>=10 and i<3 else ("Medium" if i<7 else "Explore")
  ideas.append(dict(topic=topic,service=service,industry=industry_label,primary=primary,secondary=secondary,
                    intent=intent,angle=angle,question=question,prompt=prompt,priority=priority,
                    source=row["link"],news_connection=connection))
 return ideas
def save_ideas(story_id,ideas):
 c=conn()
 for x in ideas:
  iid=hashlib.sha1((story_id+x["topic"]).encode()).hexdigest()[:18]
  c.execute("INSERT OR IGNORE INTO ideas VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(iid,story_id,x["topic"],x["service"],x["industry"],x["primary"],json.dumps(x["secondary"]),x["intent"],x["angle"],x["question"],x["prompt"],x["priority"],x["source"],datetime.now(timezone.utc).isoformat()))
 c.commit();c.close()

st.title("💡 ConnexR News Ideation Studio")
st.caption("Latest news → blog topic ideas → keyword clusters → SEO/GEO/AEO brief → ready-to-copy writing prompt.")
st.info("This application does not write blogs. It creates independent editorial angles, keyword clusters and ready-to-copy prompts. Topics explore business implications and practical decisions—not rewrites of news headlines.")
with st.sidebar:
 st.subheader("ConnexR solution mapping")
 st.caption("Custom AI • AIOps • Digital & AI Transformation • Cloud & AI Infrastructure • Systems Modernization")
 st.caption("No OpenAI API key, paid AI API, or CMS connection required.")
tab1,tab2,tab3=st.tabs(["1. Discover latest news","2. Ideate topics & prompts","3. Saved ideation"])
with tab1:
 days=st.selectbox("News look-back window",[1,3,7,14,30],index=2,format_func=lambda x:f"Last {x} days")
 svcs=st.multiselect("ConnexR service lines",list(SERVICES),default=list(SERVICES))
 inds=st.multiselect("Target industries",INDUSTRIES,default=INDUSTRIES)
 limit=st.slider("Stories per search phrase",5,20,10)
 if st.button("Discover latest news",type="primary"):
  with st.spinner("Searching public news RSS feeds..."):
   rows=discover(days,svcs,inds,limit);save_stories(rows)
  st.success(f"Found {len(rows)} unique stories.")
 df=get_stories()
 if not df.empty:
  for _,r in df.head(80).iterrows():
   with st.container(border=True):
    st.markdown(f"**{r['title']}**")
    st.caption(f"{r['source']} · {r['published'] or 'Date unavailable'} · Relevance {r['score']}/30")
    st.write(r["summary"][:400])
    st.markdown(f"[Open original news]({r['link']})")
with tab2:
 df=get_stories()
 if df.empty: st.warning("Discover news first.")
 else:
  choices={f"{r['title'][:115]} · {r['source']}":r["id"] for _,r in df.iterrows()}
  label=st.selectbox("Select a news development",list(choices))
  row=df[df.id==choices[label]].iloc[0].to_dict()
  a,b=st.columns(2)
  with a: service=st.selectbox("ConnexR service line",list(SERVICES),index=list(SERVICES).index(row["service"]) if row["service"] in SERVICES else 0)
  with b: industry=st.selectbox("Target industry",["Cross-industry"]+INDUSTRIES,index=(["Cross-industry"]+INDUSTRIES).index(row["industry"]) if row["industry"] in INDUSTRIES else 0)
  count=st.slider("Number of topic ideas",5,15,10)
  if st.button("Generate ideation + keywords + prompts",type="primary"):
   ideas=generate_ideas(row,service,industry,count);save_ideas(row["id"],ideas);st.session_state["ideas"]=ideas
  ideas=st.session_state.get("ideas",[])
  for i,x in enumerate(ideas,1):
   with st.expander(f"{i}. {x['topic']} · {x['priority']}",expanded=(i==1)):
    st.markdown(f"**Primary keyword:** {x['primary']}")
    st.markdown("**Secondary keyword ideas:** "+", ".join(x["secondary"]))
    st.markdown(f"**Search intent:** {x['intent']}")
    st.markdown(f"**Editorial angle:** {x['angle']}")
    st.markdown(f"**Why this is different from the news headline:** {x.get('news_connection', 'Explore the broader business implications of this news development.')}")
    st.markdown(f"**AEO question:** {x['question']}")
    st.markdown(f"**News source:** [Open source]({x['source']})")
    st.text_area("Ready-to-copy blog prompt",x["prompt"],height=420,key=f"prompt_{i}")
    st.download_button("Download this prompt",x["prompt"],file_name=f"connexr-blog-prompt-{i}.txt",key=f"promptdl_{i}")
  if ideas:
   export=pd.DataFrame([{"Topic":x["topic"],"Service":x["service"],"Industry":x["industry"],"Primary keyword":x["primary"],"Secondary keywords":", ".join(x["secondary"]),"Search intent":x["intent"],"SEO/GEO angle":x["angle"],"AEO question":x["question"],"Priority":x["priority"],"News source":x["source"],"Ready-to-copy prompt":x["prompt"]} for x in ideas])
   st.download_button("Download all ideas, keywords and prompts (CSV)",export.to_csv(index=False).encode(), "connexr_ideation_prompts.csv","text/csv")
with tab3:
 c=conn();saved=pd.read_sql_query("SELECT topic,service,industry,primary_kw,secondary_kws,intent,angle,aeo,prompt,priority,source_url,created_at FROM ideas ORDER BY created_at DESC",c);c.close()
 if saved.empty: st.info("Saved topic ideas will appear here after generation.")
 else:
  st.dataframe(saved.drop(columns=["prompt"]),use_container_width=True,hide_index=True)
  st.download_button("Export saved ideation and prompts (CSV)",saved.to_csv(index=False).encode(),"connexr_saved_ideation.csv","text/csv")
st.divider()
st.caption("Keyword lists are ideation suggestions, not measured search volumes, CPC or difficulty. Validate demand with Google Keyword Planner or Search Console. GEO/AEO guidance improves clarity and answerability but cannot guarantee AI citations or rankings. Review original news and verify all claims before using the prompt.")
