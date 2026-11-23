"""국토교통부 아파트 매매 실거래가 API를 호출해서 거래 목록을 받아오는 모듈.

API 하나의 호출은 "시군구 1곳 + 1개월"치 데이터만 돌려줍니다.
"""

import os
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
ROWS_PER_PAGE = 1000

# 프로젝트 폴더 안의 .streamlit/secrets.toml 파일에서 인증키를 읽습니다.
# 이 파일은 .gitignore에 들어 있어서 GitHub에 올라가지 않습니다.
SECRETS_FILE = Path(__file__).parent / ".streamlit" / "secrets.toml"


def load_api_key() -> str:
    # 인터넷(Streamlit Cloud)에서는 Secrets 설정값이 환경변수로도 들어옵니다.
    if os.environ.get("MOLIT_API_KEY"):
        return os.environ["MOLIT_API_KEY"].strip()
    if not SECRETS_FILE.exists():
        raise RuntimeError(
            f"{SECRETS_FILE} 파일이 없습니다. secrets.toml.example을 복사해서 인증키를 넣어주세요."
        )
    text = SECRETS_FILE.read_text(encoding="utf-8")
    match = re.search(r'MOLIT_API_KEY\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("secrets.toml에서 MOLIT_API_KEY를 찾지 못했습니다.")
    return match.group(1).strip()


def _text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _parse_item(item: ET.Element) -> dict:
    return {
        "sgg_cd": _text(item, "sggCd"),
        "umd_nm": _text(item, "umdNm"),
        "jibun": _text(item, "jibun"),
        "apt_nm": _text(item, "aptNm"),
        "apt_dong": _text(item, "aptDong"),
        "build_year": int(_text(item, "buildYear") or 0),
        "area_m2": float(_text(item, "excluUseAr") or 0),  # 전용면적(㎡)
        "floor": int(_text(item, "floor") or 0),
        "deal_date": "{}-{:02d}-{:02d}".format(
            _text(item, "dealYear"),
            int(_text(item, "dealMonth") or 0),
            int(_text(item, "dealDay") or 0),
        ),
        "price_manwon": int(_text(item, "dealAmount").replace(",", "") or 0),  # 거래금액(만원)
        "dealing_type": _text(item, "dealingGbn"),  # 중개거래 / 직거래
        "cancel_type": _text(item, "cdealType"),  # "O"이면 해제(취소)된 거래
        "cancel_day": _text(item, "cdealDay"),
    }


def fetch_month(api_key: str, lawd_cd: str, deal_ym: str, retries: int = 3) -> list[dict]:
    """시군구 코드(5자리)와 계약년월(YYYYMM)의 거래를 모두 받아옵니다."""
    results: list[dict] = []
    page = 1
    while True:
        params = {
            "serviceKey": api_key,
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ym,
            "numOfRows": ROWS_PER_PAGE,
            "pageNo": page,
        }
        for attempt in range(retries):
            try:
                resp = requests.get(ENDPOINT, params=params, timeout=30)
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
                break
            except (requests.RequestException, ET.ParseError):
                if attempt == retries - 1:
                    raise
                time.sleep(2 * (attempt + 1))

        code = root.findtext("header/resultCode", "")
        if code not in ("000", "00"):
            msg = root.findtext("header/resultMsg", "")
            raise RuntimeError(f"API 오류 {code}: {msg} (시군구 {lawd_cd}, {deal_ym})")

        items = root.findall("body/items/item")
        results.extend(_parse_item(it) for it in items)

        total = int(root.findtext("body/totalCount", "0") or 0)
        if page * ROWS_PER_PAGE >= total or not items:
            return results
        page += 1
