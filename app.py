# app.py
# -*- coding: utf-8 -*-

import os
import streamlit as st

from langchain_openai import ChatOpenAI
from langchain_community.tools.tavily_search import TavilySearchResults

# -----------------------------
# (선택) LangSmith 경고(401) 방지
# - langchain tracing이 켜져있는데 키가 없으면 경고가 날 수 있어요.
# -----------------------------
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("LANGCHAIN_ENDPOINT", "")
os.environ.setdefault("LANGCHAIN_API_KEY", "")

# -----------------------------
# 환경 변수/시크릿 읽기
# - 1순위: OS 환경변수
# - 2순위: streamlit secrets (secrets.toml)
# -----------------------------
def get_secret(key: str, default: str = "") -> str:
    v = os.getenv(key, "")
    if v:
        return v
    # streamlit secrets
    try:
        return st.secrets.get(key, default)  # type: ignore
    except Exception:
        return default

OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
TAVILY_API_KEY = get_secret("TAVILY_API_KEY")

# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="KOSPI 투자 보고서", layout="centered")
st.title("📈 KOSPI 종목 투자 보고서 생성기")
st.caption("Tavily 뉴스 검색 + OpenAI 요약/분석")

with st.expander("✅ 실행 전 체크", expanded=False):
    st.write("- OPENAI_API_KEY, TAVILY_API_KEY가 필요합니다.")
    st.write("- 키는 환경변수 또는 Streamlit secrets로 설정하세요.")
    st.write("- (LangSmith 401 경고가 뜨면 tracing을 끄거나 LANGCHAIN_API_KEY를 설정하세요.)")

if not OPENAI_API_KEY:
    st.error("❌ OPENAI_API_KEY가 설정되지 않았습니다. (환경변수 또는 .streamlit/secrets.toml)")
    st.stop()

if not TAVILY_API_KEY:
    st.error("❌ TAVILY_API_KEY가 설정되지 않았습니다. (환경변수 또는 .streamlit/secrets.toml)")
    st.stop()

# 모델 설정 UI (원하면 바꿀 수 있게)
model = st.selectbox("모델 선택", ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"], index=0)
temperature = st.slider("temperature", 0.0, 1.0, 0.2, 0.05)
max_results = st.slider("뉴스 검색 결과 개수", 1, 8, 3, 1)

stock_name = st.text_input("KOSPI 종목명을 입력하세요 (예: 삼성전자)", placeholder="예: 삼성전자")

def tavily_search(query: str):
    tool = TavilySearchResults(
        tavily_api_key=TAVILY_API_KEY,
        max_results=max_results
    )

    # langchain 버전에 따라 run / invoke가 다를 수 있어 둘 다 대응
    try:
        return tool.run(query)
    except Exception:
        return tool.invoke(query)

def extract_contents(results):
    """
    results 형태가 버전에 따라:
    - list[dict] (content/url/title...) 이거나
    - dict 형태로 반환될 수 있어 방어적으로 처리
    """
    if results is None:
        return "", []

    docs = []
    if isinstance(results, list):
        docs = results
    elif isinstance(results, dict) and "results" in results and isinstance(results["results"], list):
        docs = results["results"]
    elif isinstance(results, dict):
        # dict 하나만 오는 경우
        docs = [results]

    contents = []
    sources = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        c = d.get("content") or d.get("snippet") or ""
        if c:
            contents.append(c)
        url = d.get("url") or d.get("link") or ""
        title = d.get("title") or ""
        if url or title:
            sources.append({"title": title, "url": url})

    return "\n\n".join(contents).strip(), sources

def build_llm():
    return ChatOpenAI(
        api_key=OPENAI_API_KEY,
        model=model,
        temperature=temperature
    )

if st.button("투자 보고서 생성") and stock_name.strip():
    q = f"{stock_name.strip()} 최근 뉴스"
    with st.spinner("🔎 뉴스 검색 중..."):
        try:
            results = tavily_search(q)
        except Exception as e:
            st.error(f"❌ Tavily 검색 오류: {e}")
            st.stop()

    combined_content, sources = extract_contents(results)

    if not combined_content:
        st.warning("❗ 관련 뉴스를 찾을 수 없습니다.")
        st.stop()

    # (선택) 출처 표시
    if sources:
        with st.expander("🔗 검색된 출처 보기", expanded=False):
            for s in sources[:10]:
                t = s.get("title") or s.get("url") or "(no title)"
                u = s.get("url") or ""
                if u:
                    st.markdown(f"- [{t}]({u})")
                else:
                    st.write(f"- {t}")

    llm = build_llm()

    # 1) 키워드 추출
    st.subheader("📌 뉴스 기반 주요 키워드")
    keyword_prompt = f"""
다음은 {stock_name}에 대한 최근 뉴스 요약 텍스트입니다.
이 내용을 바탕으로 핵심 키워드 5개를 **한글 단어/짧은 구** 형태로 추출해주세요.
불필요한 설명 없이, 줄바꿈으로 5개만 출력하세요.

뉴스 내용:
{combined_content}
""".strip()

    with st.spinner("🧠 키워드 추출 중..."):
        try:
            keyword_result = llm.invoke(keyword_prompt)
            st.markdown(keyword_result.content.strip())
        except Exception as e:
            st.error(f"❌ OpenAI 키워드 생성 오류: {e}")
            st.stop()

    st.divider()

    # 2) 보고서 생성
    st.subheader("📝 투자 보고서")
    report_prompt = f"""
당신은 한국 주식 리서치 애널리스트입니다.
다음 뉴스 내용을 바탕으로 **{stock_name}**에 대한 한국어 투자 보고서를 작성하세요.

형식:
1) 핵심 뉴스 요약 (3~5줄)
2) 종합 분석 (긍정/부정 요인 균형, 6~10줄)
3) 투자자에게 주는 시사점 (3~6줄, 리스크 포함)
4) 한 줄 결론 (중립적 톤, 과도한 단정 금지)

뉴스 내용:
{combined_content}
""".strip()

    with st.spinner("🧾 보고서 작성 중..."):
        try:
            report_result = llm.invoke(report_prompt)
            st.markdown(report_result.content.strip())
            st.success("✅ 보고서 생성 완료")
        except Exception as e:
            st.error(f"❌ OpenAI 보고서 생성 오류: {e}")
            st.stop()




