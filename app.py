# === Ứng dụng Streamlit: Chuyển nội dung YouTube thành bài viết chuẩn SEO ===
# Hướng dẫn xuất cookies.txt chi tiết:
# 1. Cài extension 'Get cookies.txt' cho Chrome/Firefox:
#    - Chrome: https://chrome.google.com/webstore/detail/get-cookiestxt/lgblnfidahcdcjddiepkckcfdhpknnjh
#    - Firefox: https://addons.mozilla.org/firefox/addon/get-cookiestxt/
# 2. Mở YouTube và đăng nhập tài khoản Google của bạn.
# 3. Nhấp vào icon extension và chọn 'Export' -> lưu file 'cookies.txt' vào thư mục chứa script.
# 4. Kiểm tra file 'cookies.txt' đã có cookie của YouTube (ví dụ: VISITOR_INFO1_LIVE, YSC, LOGIN_INFO...).
# 5. Sử dụng file này để yt-dlp giả lập phiên đăng nhập, bỏ qua captcha/bot-check.

import streamlit as st
import os
import requests
import json
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from urllib.parse import urlparse, parse_qs
import openai
import yt_dlp

# === CONFIG ===
BLOGGER_API_KEY = st.secrets.get("BLOGGER_API_KEY", "YOUR_BLOGGER_API_KEY")
BLOG_ID = st.secrets.get("BLOG_ID", "YOUR_BLOG_ID")
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", "YOUR_GROQ_API_KEY")
ASSEMBLYAI_API_KEY = st.secrets.get("ASSEMBLYAI_API_KEY", "YOUR_ASSEMBLYAI_API_KEY")

openai.api_key = GROQ_API_KEY

# === HÀM HỖ TRỢ ===
def extract_video_id(youtube_url):
    query = urlparse(youtube_url)
    if query.hostname == 'youtu.be':
        return query.path[1:]
    if query.hostname in ('www.youtube.com', 'youtube.com'):
        if query.path == '/watch':
            return parse_qs(query.query)['v'][0]
        if query.path.startswith('/embed/'):
            return query.path.split('/')[2]
    return None


def get_transcript(video_id):
    """
    Lấy transcript từ YouTube nếu có sẵn
    """
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['vi', 'en'])
        return ' '.join([item['text'] for item in transcript])
    except (TranscriptsDisabled, NoTranscriptFound):
        return None


def download_youtube_audio(video_id):
    """
    Tải audio từ YouTube và dùng cookies.txt để xác thực
    """
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{video_id}.mp3',
        'quiet': True,
        # Sử dụng cookies.txt từ trình duyệt (file export ở thư mục):
        'cookiefile': 'cookies.txt',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([f'https://www.youtube.com/watch?v={video_id}'])
    return f'{video_id}.mp3'


def transcribe_audio_assemblyai(mp3_path):
    """
    Gửi file audio lên AssemblyAI để chuyển giọng nói thành văn bản
    """
    headers = {
        "authorization": ASSEMBLYAI_API_KEY,
        "content-type": "application/json"
    }
    # Upload
    with open(mp3_path, 'rb') as f:
        upload_resp = requests.post(
            'https://api.assemblyai.com/v2/upload',
            headers={"authorization": ASSEMBLYAI_API_KEY},
            files={'file': f}
        )
    audio_url = upload_resp.json().get('upload_url')

    # Request transcript
    json_data = {"audio_url": audio_url, "language_code": "vi"}
    transcript_resp = requests.post(
        'https://api.assemblyai.com/v2/transcript',
        headers=headers,
        json=json_data
    )
    transcript_id = transcript_resp.json().get('id')

    # Poll until completed
    status = None
    while status != 'completed':
        poll = requests.get(
            f'https://api.assemblyai.com/v2/transcript/{transcript_id}',
            headers=headers
        ).json()
        status = poll.get('status')
        if status == 'error':
            return None
        import time; time.sleep(3)
    return poll.get('text')


def summarize_to_seo_article(transcript, video_title):
    prompt = f"""
Viết một bài blog chuẩn SEO dựa trên:
- Tiêu đề video: {video_title}
- Nội dung: {transcript}
Yêu cầu:
1. Bài >600 từ, có tiêu đề hấp dẫn
2. Mô tả meta
3. 5-10 tags keywords
4. HTML hoặc markdown
"""
    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content


def post_to_blogger(title, content, labels, description):
    url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/"
    headers = {"Content-Type": "application/json"}
    params = {"key": BLOGGER_API_KEY}
    body = {
        "kind": "blogger#post",
        "title": title,
        "content": content,
        "labels": labels,
        "customMetaData": description,
    }
    resp = requests.post(url, headers=headers, params=params, json=body)
    return resp.status_code, resp.json()

# === GIAO DIỆN STREAMLIT ===
st.set_page_config(page_title="YouTube ➜ Blogger SEO", layout="wide")
st.title("📝 Chuyển video YouTube ➜ Bài viết Blogger chuẩn SEO")

youtube_url = st.text_input("Nhập URL video YouTube:")

if st.button("Chuyển thành bài viết") and youtube_url:
    with st.spinner("Đang xử lý..."):
        vid = extract_video_id(youtube_url)
        txt = get_transcript(vid)
        if not txt:
            st.warning("Không tìm thấy transcript, đang tải audio và chuyển STT...")
            audio = download_youtube_audio(vid)
            txt = transcribe_audio_assemblyai(audio)
        if not txt:
            st.error("Không thể lấy nội dung từ video.")
        else:
            article = summarize_to_seo_article(txt, youtube_url)
            st.subheader("✅ Bài viết SEO:")
            st.text_area("Nội dung bài viết:", article, height=400)
            if st.button("Đăng lên Blogger"):
                status, result = post_to_blogger(
                    f"Bài viết từ YouTube: {vid}",
                    article,
                    ["YouTube", "SEO"],
                    f"Bài viết tự động từ video {vid}"
                )
                if status == 200:
                    st.success("Đã đăng lên Blogger thành công!")
                else:
                    st.error(f"Lỗi khi đăng: {result}")
