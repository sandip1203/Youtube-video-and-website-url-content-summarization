# app.py
import re
import validators
import streamlit as st

from langchain_groq import ChatGroq
from langchain_core.documents import Document
from langchain_community.document_loaders import UnstructuredURLLoader

# ✅ Use langchain_classic consistently (matches your environment)
from langchain_classic.prompts import PromptTemplate
from langchain_classic.chains.summarize import load_summarize_chain

import youtube_transcript_api
from youtube_transcript_api import YouTubeTranscriptApi


# -----------------------------
# YouTube transcript (works across different youtube_transcript_api APIs)
# -----------------------------
def extract_video_id(url: str) -> str:
    patterns = [
        r"v=([^&]+)",                       # youtube.com/watch?v=ID
        r"youtu\.be/([^?&]+)",              # youtu.be/ID
        r"youtube\.com/shorts/([^?&/]+)",   # youtube.com/shorts/ID
        r"youtube\.com/embed/([^?&/]+)",    # youtube.com/embed/ID
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    raise ValueError("Invalid YouTube URL")


def _snippets_to_text(snippets) -> str:
    if snippets is None:
        return ""
    # unwrap common container attributes
    for attr in ("snippets", "segments", "items"):
        if hasattr(snippets, attr):
            snippets = getattr(snippets, attr)
            break

    texts = []
    try:
        for s in snippets:
            if isinstance(s, dict):
                t = s.get("text", "")
            else:
                t = getattr(s, "text", "")
                if not t and hasattr(s, "to_dict"):
                    try:
                        t = s.to_dict().get("text", "")
                    except Exception:
                        t = ""
            if t:
                texts.append(t)
    except TypeError:
        return ""
    return " ".join(texts).strip()


def fetch_transcript_any_version(video_id: str, preferred_langs=None) -> str:
    if preferred_langs is None:
        preferred_langs = ["en", "en-US", "hi", "ne"]

    # 1) Some versions have get_transcript
    if hasattr(YouTubeTranscriptApi, "get_transcript"):
        for lang in preferred_langs:
            try:
                data = YouTubeTranscriptApi.get_transcript(video_id, languages=[lang])
                text = _snippets_to_text(data)
                if text:
                    return text
            except Exception:
                pass
        try:
            data = YouTubeTranscriptApi.get_transcript(video_id)
            text = _snippets_to_text(data)
            if text:
                return text
        except Exception:
            pass

    # 2) Some versions have list_transcripts -> transcript.fetch()
    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        tl = YouTubeTranscriptApi.list_transcripts(video_id)

        for lang in preferred_langs:
            try:
                t = tl.find_transcript([lang])
                data = t.fetch()
                text = _snippets_to_text(data)
                if text:
                    return text
            except Exception:
                pass

        # fallback: try any available transcript
        try:
            for t in tl:
                try:
                    data = t.fetch()
                    text = _snippets_to_text(data)
                    if text:
                        return text
                except Exception:
                    pass
        except Exception:
            pass

    # 3) Some variants expose fetch on instance/class
    for api_obj in (YouTubeTranscriptApi, YouTubeTranscriptApi()):
        if hasattr(api_obj, "fetch"):
            for lang in preferred_langs:
                for kwargs in ({"languages": [lang]}, {}):
                    try:
                        data = api_obj.fetch(video_id, **kwargs)
                        text = _snippets_to_text(data)
                        if text:
                            return text
                    except TypeError:
                        pass
                    except Exception:
                        pass

    raise RuntimeError(
        "Could not retrieve a transcript for this video. "
        "Possible reasons: captions disabled, private/age-restricted video, "
        "or your transcript library cannot access it."
    )


def load_youtube_docs(url: str) -> list[Document]:
    video_id = extract_video_id(url)
    text = fetch_transcript_any_version(video_id)
    if not text:
        raise RuntimeError("Transcript fetched but empty.")
    return [Document(page_content=text)]


# -----------------------------
# Website loader
# -----------------------------
def load_website_docs(url: str) -> list[Document]:
    loader = UnstructuredURLLoader(
        urls=[url],
        ssl_verify=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/116.0.0.0 Safari/537.36"
            )
        },
    )
    docs = loader.load()
    if not docs:
        raise RuntimeError("Could not load content from the website.")
    return docs


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="LangChain: Summarize Text From YT or Website", page_icon="🦜")
st.title("🦜 LangChain: Summarize Text From YT or Website")
st.subheader("Summarize URL")

with st.sidebar:
    groq_api_key = st.text_input("Groq API Key", value="", type="password")

generic_url = st.text_input("URL", label_visibility="collapsed")

# ✅ map_reduce prompts for langchain_classic
map_prompt = PromptTemplate(
    template="""
Write a concise partial summary of the following text.

TEXT:
{text}

PARTIAL SUMMARY:
""",
    input_variables=["text"],
)

combine_prompt = PromptTemplate(
    template="""
You will be given a set of partial summaries.
Write a final well-structured summary in about 300 words.
Use short headings and bullet points where helpful.

PARTIAL SUMMARIES:
{text}

FINAL SUMMARY:
""",
    input_variables=["text"],
)

if st.button("Summarize the Content from YT or Website"):
    if not groq_api_key.strip() or not generic_url.strip():
        st.error("Please provide the Groq API key and a URL to get started.")
        st.stop()

    if not validators.url(generic_url):
        st.error("Please enter a valid URL (YouTube or website).")
        st.stop()

    try:
        with st.spinner("Working..."):
            # ✅ Create LLM after validation
            llm = ChatGroq(model="llama-3.1-8b-instant", api_key=groq_api_key.strip())

            # ✅ Load docs
            if ("youtube.com" in generic_url) or ("youtu.be" in generic_url):
                docs = load_youtube_docs(generic_url)
            else:
                docs = load_website_docs(generic_url)

            # ✅ Correct map_reduce call for langchain_classic
            chain = load_summarize_chain(
                llm,
                chain_type="map_reduce",
                map_prompt=map_prompt,
                combine_prompt=combine_prompt,
            )

            output_summary = chain.run(docs)

            st.success("✅ Summary generated")
            st.write(output_summary)

    except Exception as e:
        st.exception(e)
