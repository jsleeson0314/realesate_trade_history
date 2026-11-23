"""비교 그룹(단지 + 평형 묶음)을 내 컴퓨터의 data/groups.json에 저장하고 불러옵니다.

파일 모양:
    {
      "last": "안양 갈아타기 후보",          # 마지막으로 쓴 그룹 (다음에 열 때 자동으로 불러옴)
      "groups": {
        "안양 갈아타기 후보": [
          {"complex_id": "41210|철산동|...|도덕파크타운2단지", "areas": [49]},
          {"complex_id": "41171|안양동|...|안양역푸르지오더샵", "areas": [41]},
          {"complex_id": "41111|정자동|...|꽃뫼마을신안", "areas": []}   # 빈 목록 = 전체 평형
        ]
      }
    }
"""

import json

import db

GROUPS_FILE = db.DB_PATH.parent / "groups.json"
OLD_FAVORITES_FILE = db.DB_PATH.parent / "favorites.json"  # 예전 "관심 단지" 저장 파일
OLD_FAVORITES_NAME = "관심 단지"


def _read() -> dict:
    try:
        data = json.loads(GROUPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("groups", {})
    data.setdefault("last", None)

    # 예전 버전의 "관심 단지로 저장" 목록이 있으면 그룹 하나로 옮겨 옵니다(한 번만).
    if not GROUPS_FILE.exists() and OLD_FAVORITES_FILE.exists():
        try:
            old = json.loads(OLD_FAVORITES_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = []
        if old:
            data["groups"][OLD_FAVORITES_NAME] = [{"complex_id": c, "areas": []} for c in old]
            data["last"] = OLD_FAVORITES_NAME
            _write(data)
    return data


def _write(data: dict) -> None:
    GROUPS_FILE.parent.mkdir(exist_ok=True)
    GROUPS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def names() -> list[str]:
    return list(_read()["groups"].keys())


def last_used() -> str | None:
    return _read()["last"]


def get(name: str) -> list[dict]:
    return _read()["groups"].get(name, [])


def save(name: str, picks: list[dict]) -> bool:
    """그룹 저장. 같은 이름이 이미 있었으면 True(덮어씀)."""
    data = _read()
    existed = name in data["groups"]
    data["groups"][name] = picks
    data["last"] = name
    _write(data)
    return existed


def set_last(name: str) -> None:
    data = _read()
    data["last"] = name
    _write(data)


def delete(name: str) -> None:
    data = _read()
    data["groups"].pop(name, None)
    if data["last"] == name:
        data["last"] = None
    _write(data)


def merge(other: dict) -> int:
    """내려받아 둔 groups.json 내용을 합칩니다. 가져온 그룹 수를 돌려줍니다."""
    incoming = other["groups"]
    if not isinstance(incoming, dict):
        raise TypeError("groups must be a dict")
    data = _read()
    data["groups"].update(incoming)
    _write(data)
    return len(incoming)


def export() -> dict:
    """내려받기용: 저장된 그룹 전체."""
    return _read()
