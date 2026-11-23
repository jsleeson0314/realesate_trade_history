# 인터넷에 올리기 (휴대폰, 다른 PC에서 접속)

무료 서비스인 **Streamlit Community Cloud**에 올립니다. 한 번만 하면 되고, 이후에는
GitHub의 `main` 브랜치가 바뀔 때마다 자동으로 다시 올라갑니다.

## 미리 알아 둘 점

| 항목 | 인터넷 버전에서는 |
| --- | --- |
| 데이터 | 저장소의 `seed/trades.db.gz`(내 PC 데이터를 압축한 것)로 시작합니다. |
| 데이터 최신화 | 왼쪽 **🔄 받아 둔 지역 모두 최신화** 버튼으로 최근 3개월을 다시 받을 수 있습니다. |
| 앱이 다시 켜지면 | 앱이 한동안 안 쓰여서 잠들었다 깨거나, 코드가 바뀌어 다시 올라가면 **data 폴더가 초기화**되어 `seed/`의 데이터로 돌아갑니다. 그동안 받은 데이터와 새로 저장한 그룹이 사라질 수 있습니다. |
| 비교 그룹 | 처음에는 `seed/groups.json`(내 PC의 그룹)으로 시작합니다. 인터넷에서 만든 그룹은 **📁 비교 그룹 → 📤 그룹 파일 내보내기·가져오기**로 내려받아 두세요. |
| 비밀번호 | Secrets에 `APP_PASSWORD`를 넣으면 비밀번호를 아는 사람만 화면을 봅니다. |
| 인증키 | Secrets에 넣으므로 GitHub에는 올라가지 않습니다. |

`seed/` 데이터를 새것으로 바꾸고 싶으면 내 PC에서 데이터를 받은 뒤 Claude에게
"seed 데이터 새로 올려줘"라고 하면 됩니다.

## 올리는 순서

1. 브라우저에서 https://share.streamlit.io 에 들어가 **Continue with GitHub**로 로그인합니다.
   GitHub 권한 요청 화면이 나오면 **Authorize**를 누릅니다.
   저장소가 비공개(private)라서, 비공개 저장소 접근도 허용해야 목록에 보입니다.
2. 오른쪽 위 **Create app**을 누르고, GitHub에 있는 앱을 올리는 쪽을 고릅니다.
3. 다음처럼 채웁니다.
   - Repository: `jsleeson0314/realesate_trade_history`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: 원하는 주소 (예: `patrick-apt`) → `https://patrick-apt.streamlit.app`처럼 됩니다.
4. **Advanced settings**를 엽니다.
   - Python version: `3.12`
   - Secrets 칸에 아래 두 줄을 붙여 넣고, 따옴표 안을 바꿉니다.

     ```toml
     MOLIT_API_KEY = "공공데이터포털_일반_인증키"
     APP_PASSWORD = "원하는_비밀번호"
     ```

   - **Save**를 누릅니다.
5. **Deploy**를 누르고 2~5분 기다립니다. 비밀번호 화면이 나오면 성공입니다.
6. 휴대폰에서 같은 주소로 들어가 비밀번호를 넣어 봅니다.
   Streamlit 로그인을 하라는 화면이 나오면, 앱 오른쪽 아래 **Manage app** → 점 세 개 →
   **Settings → Sharing**에서 누구나 볼 수 있게 바꿉니다. (비밀번호 화면이 있으니 주소를 알아도 내용은 안 보입니다.)

## 나중에 바꾸고 싶을 때

- 비밀번호나 인증키 바꾸기: **Manage app → Settings → Secrets**에서 고치고 저장.
- 앱이 잠들어 있으면 "Yes, get this app back up!" 버튼을 누르면 1분쯤 뒤에 깨어납니다.
- 내 PC에서 실행하는 방법(`run.bat`)은 그대로입니다. 내 PC의 `secrets.toml`에는
  `APP_PASSWORD`를 안 넣으면 비밀번호 없이 열립니다.
