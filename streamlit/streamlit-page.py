import streamlit as st
import requests
from bs4 import BeautifulSoup
import time
import json
import re

# CompletionExecutor 클래스: API 호출
class CompletionExecutor:
    def __init__(self, host, api_key, api_key_primary_val, request_id):
        self._host = host
        self._api_key = api_key
        self._api_key_primary_val = api_key_primary_val
        self._request_id = request_id

    def execute(self, completion_request):
        headers = {
            'X-NCP-CLOVASTUDIO-API-KEY': self._api_key,
            'X-NCP-APIGW-API-KEY': self._api_key_primary_val,
            'X-NCP-CLOVASTUDIO-REQUEST-ID': self._request_id,
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'text/event-stream'
        }

        with requests.post(self._host + '/testapp/v1/tasks/iqsmk52h/chat-completions',
                           headers=headers, json=completion_request, stream=True) as r:
            event_stream_data = []
            for line in r.iter_lines():
                if line:
                    event_stream_data.append(line.decode("utf-8"))
            return event_stream_data

#네이버 뉴스를 검색해 크롤링
def get_search_results(keyword):
    response = requests.get(
        #관련도순, 24시간 이내의 뉴스 수집
        f"https://search.naver.com/search.naver?where=news&sm=tab_jum&query={keyword}&sort=0&pd=1d")
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    return soup.select("div.info_group")

# 개별 뉴스 기사를 크롤링
def get_article_details(url):
    response = requests.get(url, headers={'User-agent': 'Mozilla/5.0'})
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    #뉴스 타입마다 구조가 다름. 뉴스 타입에 따라 다른 방식으로 본문을 가져옴
    if "entertain" in response.url:
        title = soup.select_one(".end_tit")
        content = soup.select_one("#articeBody")
    elif "sports" in response.url:
        title = soup.select_one("h4.title")
        content = soup.select_one("#newsEndContents")
        divs = content.select("div")
        for div in divs:
            div.decompose()
        paragraphs = content.select("p")
        for p in paragraphs:
            p.decompose()
    else:
        title = soup.select_one(".media_end_head_headline")
        content = soup.select_one("#dic_area")

    return title.text.strip(), content.text.strip()

# 뉴스 데이터를 수집
def collect_news_data(keyword):
    articles = get_search_results(keyword) #뉴스 검색 함수 호출
    titles = []
    contents = []
    links = []

    for i, article in enumerate(articles):
        if i >= 3: #최대 3개의 기사만 수집
            break
        links_in_article = article.select("a.info")
        #제목, 본문, 링크 추출
        if len(links_in_article) >= 2:
            url = links_in_article[1].attrs["href"]
            title, content = get_article_details(url)#개별 뉴스기사 수집 함수 호출
            titles.append(title)
            contents.append(content)
            links.append(url)
            time.sleep(0.3)# 요청 간격을 두어 서버 과부하 방지

    return titles, contents, links

# 모델의 응답 데이터 스트림에서 마지막 메시지 내용을 추출
def parse_event_stream(stream):
    last_message_content = None
    for line in stream:
        if line.startswith("data:"):
            data = json.loads(line[len("data:"):])
            if "message" in data and "content" in data["message"]:
                last_message_content = data["message"]["content"]
    return last_message_content

# 응답받은 퀴즈를 부분별로 나눠 저장. 페이지에서 순차적으로 출력하기 위함
def parse_response(data):
    lines = data.split('\n')
    parsed_data = {
        "오늘의 질문": "",
        "1": "",
        "2": "",
        "3": "",
        "4": "",
        "정답": "",
        "해설": ""
    }
    for line in lines:
        if line.startswith("오늘의 질문"):
            parsed_data["오늘의 질문"] = line
        elif line.startswith("1."):
            parsed_data["1"] = line
        elif line.startswith("2."):
            parsed_data["2"] = line
        elif line.startswith("3."):
            parsed_data["3"] = line
        elif line.startswith("4."):
            parsed_data["4"] = line
        elif line.startswith("정답"):
            parsed_data["정답"] = line
        elif line.startswith("해설"):
            parsed_data["해설"] = line
    return parsed_data

# 정답 번호를 추출하는 함수. 사용자 선택값의 정답 유무를 판단하기 위함
def extract_answer_number(answer_text):
    match = re.search(r'정답\s*:\s*(\d)', answer_text)
    return match.group(1) if match else None

# Streamlit 웹 애플리케이션
def main():
    st.title("주식 퀴즈 생성기")

    # 사용자 입력 섹션
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
    with col1:
        blank = []
    with col2:
        age = st.number_input("투자자 나이:", min_value=0, max_value=120, value=25)
    with col3:
        year = st.number_input("투자경력(년):", min_value=0, max_value=100, value=1)
    with col4:
        blank = []
    keyword = st.text_input("보유 종목:", value="", placeholder="보유 종목을 입력하세요",
                            key='keyword_input', label_visibility="collapsed")
    
    titles = []
    links =[]

    #뉴스 크롤링 함수 호출
    if keyword and 'quiz_data' not in st.session_state:
        with st.spinner('뉴스 읽는중..📰'):
            titles, contents, links = collect_news_data(keyword)
            #크롤링 완료 확인 위해 뉴스 제목 출력
            if contents:
                articles_content = " ".join(contents)
                st.success("수집된 뉴스 제목")
                for i in titles:
                    st.write(i)

                #모델에 전달할 프롬프트 정의. 사용자 입력값과 크롤링한 뉴스 데이터 포함
                preset_text = [
                    {
                        "role": "system",
                        "content": (
                            "너는 사용자가 주는 최신 뉴스 기사의 내용을 취합해 사용자에게 주식 투자 교육 제공을 목적으로 퀴즈를 만들어줄거야."
                            "\n퀴즈는 사용자가 주는 최신기사 내용에서 주식 가격에 영향을 줄 정보를 중심으로, 사용자의 보유종목에 관해서 내줘."
                            "\n4지선다에 정답은 1개인 퀴즈이고, 딱 1개의 퀴즈만 만들면 돼."
                            "\n아래에 너가 해야하는 답변의 형식을 지정해줄게. 여기 ~~~부분에 너의 답변을 넣어주면 돼."
                            "\n\n[답변 형식]\n오늘의 질문 :~~~? \n1.~~~\n2.~~~\n3.~~~\n4.~~~\n\n정답 :~~~번 ~~~\n\n해설 :~~~"
                        )
                    },
                    {
                        "role": "user",
                        "content": f"{articles_content}\n나이: {age}세\n투자경력: {year}년\n보유종목: {keyword}"
                    }
                ]

                request_data = {
                    'messages': preset_text,
                    'topP': 0.8,
                    'topK': 0,
                    'maxTokens': 256,
                    'temperature': 0.5,
                    'repeatPenalty': 5.0,
                    'stopBefore': [],
                    'includeAiFilters': True,
                    'seed': 0
                }

                #튜닝 모델 API 호출
                completion_executor = CompletionExecutor(
                    host='https://clovastudio.stream.ntruss.com',
                    api_key='NTA0MjU2MWZlZTcxNDJiY45r/DkTDk7oBmqKVrH2tgppYRF/3kCtv0bwtT7ihqUM',
                    api_key_primary_val='2vb3PzZVsMZcjwGY1yQG7xbuK0FqU7hrFGli34ou',
                    request_id='76902a7a-2232-400c-843f-65a8edfc8e46'
                )

                #모델의 응답 결과 수신 확인
                with st.spinner('퀴즈 생성중..🧐'):
                    event_stream_data = completion_executor.execute(request_data)
                    response = parse_event_stream(event_stream_data)
                    st.success("퀴즈 생성완료✔")
                    parsed_response = parse_response(response)
                    st.session_state.quiz_data = parsed_response
    
    #모델의 응답 퀴즈에서 질문과 선지만 출력
    if 'quiz_data' in st.session_state:
        parsed_response = st.session_state.quiz_data
        #모델의 응답 퀴즈를 부분별로 나누어 저장하는 함수 호출
        question, numberOne, numberTwo, numberThree, numberFour, answer, description = list(parsed_response.keys())[:7]
        st.write(parsed_response[question])

        # 사용자 선택 초기화
        if 'user_choice' not in st.session_state:
            st.session_state.user_choice = None

        choice = st.radio("답을 선택하세요", 
                          (parsed_response[numberOne], 
                           parsed_response[numberTwo], 
                           parsed_response[numberThree], 
                           parsed_response[numberFour]))

        if st.button("제출"):
            st.session_state.user_choice = choice

        #정답여부 체크
        if st.session_state.user_choice:
            user_choice = st.session_state.user_choice
            answer_number = extract_answer_number(parsed_response[answer])
            selected_number = user_choice.split('.')[0]
        
            if selected_number == answer_number:
                st.success("정답입니다!")
            else:
                st.error("오답입니다!")

            #정답과 해설 출력
            st.write(parsed_response[answer])
            st.write(parsed_response[description])
            

if __name__ == "__main__":
    main()
