import streamlit as st
import pandas as pd
from io import BytesIO
import unicodedata



st.set_page_config(page_title="(브랜드 상세) 상품흐름 대시보드", layout="wide")

# ----------------------------
# Google Sheets 연동
# ----------------------------
def get_gsheet_client(credentials_dict):
    if credentials_dict is None:
        return None
    import gspread
    from google.oauth2.service_account import Credentials
    # 스프레드시트/워크시트를 "생성"까지 하려면 readonly 권한으로는 불가능합니다.
    # 읽기만 해도 아래 scope는 동작하며, 생성/추가 시트 등도 지원합니다.
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        credentials_dict, scopes=scope
    )
    return gspread.authorize(creds)


def _normalize_spreadsheet_id(spreadsheet_id_or_url):
    """스프레드시트 ID 또는 URL을 받아 ID로 정규화."""
    import re

    if spreadsheet_id_or_url is None:
        return ""
    s = str(spreadsheet_id_or_url).strip()
    if not s:
        return ""

    # URL: https://docs.google.com/spreadsheets/d/<ID>/edit...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", s)
    if m:
        return m.group(1)

    # 공유 링크에 key= 로 들어오는 케이스
    m = re.search(r"(?:^|[?&])key=([a-zA-Z0-9-_]+)", s)
    if m:
        return m.group(1)

    return s


def open_or_create_spreadsheet(client, spreadsheet_id=None, spreadsheet_title=None, create_if_missing=False):
    """ID가 있으면 open_by_key, 없으면 title로 open(옵션으로 create)."""
    import gspread

    sid = _normalize_spreadsheet_id(spreadsheet_id)
    if sid:
        return client.open_by_key(sid)

    title = (spreadsheet_title or "").strip() if spreadsheet_title else ""
    if not title:
        raise ValueError("스프레드시트 ID/URL 또는 제목(spreadsheet_title)이 필요합니다.")

    try:
        return client.open(title)
    except gspread.exceptions.SpreadsheetNotFound:
        if not create_if_missing:
            raise
        return client.create(title)


@st.cache_data(ttl=300)
def _cached_load_sheet(spreadsheet_id: str, sheet_name: str, header_row: int):
    if not spreadsheet_id or not str(spreadsheet_id).strip():
        return None
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
        elif "google_service_account" in st.secrets:
            creds_dict = dict(st.secrets["google_service_account"])
        else:
            return None
    except Exception:
        return None
    client = get_gsheet_client(creds_dict)
    if client is None:
        return None
    return load_sheet_as_dataframe(
        client,
        spreadsheet_id,
        sheet_name=sheet_name or None,
        header_row=header_row,
    )


def load_sheet_as_dataframe(
    client,
    spreadsheet_id=None,
    sheet_name=None,
    header_row=0,
    spreadsheet_title=None,
    create_spreadsheet_if_missing=False,
    create_worksheet_if_missing=False,
):
    """header_row: 0 = 첫 번째 행이 헤더(기본), 1 = 두 번째 행이 헤더 등"""
    try:
        spreadsheet = open_or_create_spreadsheet(
            client,
            spreadsheet_id=spreadsheet_id,
            spreadsheet_title=spreadsheet_title,
            create_if_missing=create_spreadsheet_if_missing,
        )

        # 워크시트는 반드시 "스프레드시트를 연 뒤"에 가져옵니다.
        if sheet_name and str(sheet_name).strip():
            try:
                worksheet = spreadsheet.worksheet(str(sheet_name).strip())
            except Exception as e:
                # 없는 워크시트를 요청한 경우(옵션) 생성
                if create_worksheet_if_missing:
                    worksheet = spreadsheet.add_worksheet(title=str(sheet_name).strip(), rows=1000, cols=26)
                else:
                    raise e
        else:
            worksheet = spreadsheet.sheet1

        rows = worksheet.get_all_values()
        if not rows:
            return pd.DataFrame()
        # 자동 헤더 감지: 1행에 '리터칭'이 없으면 2행·3행 시도 (실제 머릿글이 2행인 시트 대응)
        if header_row == -1:
            header_row = 0
            for try_row in range(min(3, len(rows))):
                try_headers = [str(h).strip() for h in rows[try_row]]
                if any("리터칭" in str(h) for h in try_headers):
                    header_row = try_row
                    break
        if len(rows) <= header_row:
            return pd.DataFrame()
        headers = [str(h).strip() for h in rows[header_row]]
        data_rows = rows[header_row + 1:]
        return pd.DataFrame(data_rows, columns=headers)
    except Exception as e:
        st.error(f"시트 읽기 오류: {e}")
        return None

# 스타일코드 앞 2자리 → 브랜드 한글명
BRAND_CODE_MAP = {
    "sp": "스파오",
    "rm": "로엠",
    "mi": "미쏘",
    "wh": "후아유",
    "nb": "뉴발란스",
    "eb": "에블린",
    "hp": "슈펜",
    "cv": "클라비스",
    "nk": "뉴발란스키즈"
}
# 브랜드별 촬영·등록 여부 시트 (해당 시트에서만 읽어서 merge)
BRAND_TO_SHEET = {
    "스파오": "SP",
    "미쏘": "MI",
    "클라비스": "CV",
    "로엠": "RM",
    "후아유": "WH",
    "슈펜": "HP",  
    "에블린": "EB", 
    "뉴발란스키즈": "NK",
    "뉴발란스": "NB"
}

def _normalize_style_code_for_merge(val):
    """merge 시 브랜드 시트·BASE 시트 간 스타일코드 매칭을 위해 동일 형식으로 정규화 (공백 제거, nan 처리)"""
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    return "".join(s.split())


def brand_from_style_code(style_code):
    """스타일코드 앞 2자리로 브랜드명 반환 (소문자로 매핑)"""
    if pd.isna(style_code) or not str(style_code).strip():
        return ""
    code = str(style_code).strip()[:2].lower()
    return BRAND_CODE_MAP.get(code, code.upper())

# 스타일코드 5번째 자리 → 연도, 6번째 자리 → 시즌. 예: sp23g1fh28 → 5번째 G=2026년, 6번째 1=1시즌 → 20261 시즌 상품
STYLE_CODE_SEASON_TO_YEAR = {
    "G": "2026",
    "F": "2025",
    "H": "2027",
}

def year_from_style_code(style_code):
    """스타일코드 5번째 자리가 연도값이면 해당 연도 반환 (예: G → 2026). 매핑 없으면 빈 문자열."""
    if pd.isna(style_code) or not str(style_code).strip():
        return ""
    s = str(style_code).strip()
    if len(s) < 5:
        return ""
    year_char = s[4].upper()
    return STYLE_CODE_SEASON_TO_YEAR.get(year_char, "")


def year_season_from_style_code(style_code):
    """스타일코드 5번째(연도)·6번째(시즌) 자리로 '20261' 형태 반환. 표시용 '20261 시즌 상품'도 반환."""
    if pd.isna(style_code) or not str(style_code).strip():
        return "", ""
    s = str(style_code).strip()
    if len(s) < 6:
        return "", ""
    y = year_from_style_code(style_code)
    if not y:
        return "", ""
    season_digit = s[5]
    if not season_digit.isdigit():
        return "", ""
    ys = y + season_digit
    return ys, f"{ys} 시즌 상품"

# 시트 컬럼명 → 앱 필수 컬럼명 매핑 (한글/다른 표기 지원)
COLUMN_ALIASES = {
    "브랜드": "brand",
    "연도시즌": "yearSeason",
    "연도·시즌": "yearSeason",
    "연도 시즌": "yearSeason",
    "시즌(Now)": "yearSeason",
    "스타일코드": "styleCode",
    "스타일 코드": "styleCode",
    "스타일코드(Now)": "styleCode",
    "상품명": "productName",
    "컬러코드": "colorCode",
    "색상코드": "colorCode",
    "컬러 코드": "colorCode",
    "컬러명": "colorName",
    "색상": "colorName",
    "컬러 명": "colorName",
    "칼라(Now)": "colorName",
    "사이즈코드": "sizeCode",
    "사이즈 코드": "sizeCode",
    "입고수량": "inboundQty",
    "출고수량": "outboundQty",
    "재고수량": "stockQty",
    "판매수량": "salesQty",
    "누적입고량(물류+입고조정+브랜드간)": "inboundQty",
    "출고량[출고-반품](매장+고객+샘플+브랜드간)": "outboundQty",
    "누적 판매량": "salesQty",
    "판매재고량(입고량-누판량)": "stockQty",
    "리터칭 완료일": "isShot",
    "리터칭완료일": "isShot",
    "업로드완료일": "isShot",
    "공홈등록일": "isRegistered",
    "공홈 등록일": "isRegistered",
}

def ensure_year_season_from_columns(df):
    """년도(Now) + 시즌(Now) → yearSeason 조합"""
    if "yearSeason" in df.columns:
        return df
    if "년도(Now)" in df.columns and "시즌(Now)" in df.columns:
        df = df.copy()
        df["yearSeason"] = df["년도(Now)"].astype(str) + df["시즌(Now)"].astype(str)
    return df

def apply_column_aliases(df):
    """컬럼명 앞뒤 공백 제거 후 알려진 별칭으로 매핑"""
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = ensure_year_season_from_columns(df)
    rename = {}
    for col in list(df.columns):
        if col in COLUMN_ALIASES:
            target = COLUMN_ALIASES[col]
            # 이미 있는 컬럼으로 덮어쓰지 않음 (예: yearSeason은 년도+시즌으로 이미 채움)
            if target not in df.columns or col == target:
                rename[col] = target
    return df.rename(columns=rename) if rename else df

def fill_missing_required_columns(df, required_columns):
    """없는 필수 컬럼을 기본값으로 채움 (시트 구조가 다를 때 대시보드만 동작하도록)"""
    df = df.copy()
    for col in required_columns:
        if col not in df.columns:
            if col in ("isShot", "isRegistered", "isOnSale"):
                df[col] = 0
            elif col in ("inboundQty", "outboundQty", "stockQty", "salesQty"):
                df[col] = 0
            else:
                df[col] = ""
    return df

# ----------------------------
# 단계상태 판정 (단일 컬럼, flow와 무관)
# - 가장 앞 단계에서 멈춘 곳 하나만 표시
# ----------------------------
def compute_status(row):
    if row["inboundQty"] == 0:
        return "미입고"
    if row["outboundQty"] == 0:
        return "미출고"
    if row["__shot_done"] == 0:
        return "미촬영"
    if row["isRegistered"] == 0:
        return "미등록"
    return "판매개시"


# 기본 화면 정렬 순서
BASE_SORT_ORDER = {
    "미입고": 0,
    "미출고": 1,
    "미촬영": 2,
    "미등록": 3,
    "판매개시": 4,
}

# 버튼 클릭 시: 해당 단계가 안 된 스타일을 제일 위로
FLOW_SORT_ORDER = {
    "입고": ["미입고", "미출고", "미촬영", "미등록", "판매개시"],
    "출고": ["미출고", "미입고", "미촬영", "미등록", "판매개시"],
    "촬영": ["미촬영", "미입고", "미출고", "미등록", "판매개시"],
    "등록": ["미등록", "미입고", "미출고", "미촬영", "판매개시"],
}

# ----------------------------
# 촬영 완료 판정: 리터칭완료일·업로드완료일 등 날짜 컬럼
# ----------------------------
# 규칙: "리터칭완료일" 또는 "업로드완료일" 열에 날짜 값이 있으면 그 행은 촬영 O. (클라비스는 업로드완료일 사용)

def _normalize_col_name(name):
    """컬럼명 비교용: 앞뒤 공백·제어문자 제거, 유니코드 정규화, 공백 통일."""
    if name is None or not isinstance(name, str):
        return ""
    try:
        s = unicodedata.normalize("NFKC", str(name))
    except Exception:
        s = str(name)
    s = s.strip()
    s = "".join(c for c in s if ord(c) >= 32 or c in "\t\n\r")
    return s.replace(" ", "").replace("\u3000", "")

def _find_photo_date_column(df, preferred_name=None):
    """촬영 완료를 판정할 날짜 컬럼. 리터칭완료일·업로드완료일 우선, 없으면 촬영일자/포토촬영일 등."""
    # 0순위: Secrets에 지정된 컬럼명이 있으면 정확히 그 컬럼 사용
    if preferred_name and str(preferred_name).strip():
        name = str(preferred_name).strip()
        for c in df.columns:
            if str(c).strip() == name:
                return c
        name_norm = _normalize_col_name(name)
        for c in df.columns:
            if _normalize_col_name(c) == name_norm:
                return c
    # 1순위: 이름에 "리터칭"이 포함된 컬럼 (공백/특수문자 무관, 가장 관대하게)
    for c in df.columns:
        raw = str(c)
        if "리터칭" in raw or "retouch" in raw.lower():
            return c
    # 2순위: 머릿글 "리터칭완료일" 정확히 (공백/제어문자만 정규화)
    for c in df.columns:
        if _normalize_col_name(c) == "리터칭완료일":
            return c
    return None


def _find_registration_date_column(df):
    """등록 여부 판정용 날짜 컬럼. 공홈등록일 우선."""
    for c in df.columns:
        raw = str(c).strip()
        n = _normalize_col_name(c)
        if "공홈등록" in n or "공홈 등록" in n or "공홈등록일" in n:
            return c
    return None


def _parse_date_series(ser):
    """다양한 날짜 형식 파싱 (문자열, Excel/구글 시트 일련번호 등). 공백/형식 차이 관대하게 처리."""
    out = pd.to_datetime(ser, errors="coerce")
    # 파싱 실패한 셀: 앞뒤 공백 제거 후 재시도
    still_na = out.isna()
    if still_na.any():
        try:
            cleaned = ser.astype(str).str.strip()
            out2 = pd.to_datetime(cleaned, errors="coerce")
            out = out.fillna(out2)
        except Exception:
            pass
    # "2025. 1. 15"처럼 점 앞뒤 공백 제거 후 재시도
    still_na = out.isna()
    if still_na.any():
        try:
            s = ser.astype(str).str.strip()
            s = s.str.replace(r"\s*\.\s*", ".", regex=True).str.replace(r"\s*-\s*", "-", regex=True)
            out3 = pd.to_datetime(s, errors="coerce")
            out = out.fillna(out3)
        except Exception:
            pass
    # 구글 시트/엑셀 날짜 일련번호(문자열 "45324" 등)
    if out.isna().any():
        numeric = pd.to_numeric(ser, errors="coerce")
        valid_num = numeric.notna() & (numeric > 10000) & (numeric < 1000000)
        if valid_num.any():
            fixed = pd.to_datetime(numeric[valid_num], unit="D", origin="1899-12-30")
            out = out.fillna(fixed)
    return out

def _looks_like_date_value(val):
    """셀 값이 날짜처럼 보이면 True (파싱 실패해도 '값 있음'으로 촬영 완료 처리용)."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    s = str(val).strip()
    if not s or s in ("-", ".", "미정", "n/a", "N/A", "—"):
        return False
    # 숫자 4자리 이상 + 구분자(-./) 있으면 날짜로 간주
    if any(sep in s for sep in ("-", ".", "/")) and any(c.isdigit() for c in s):
        return True
    # 숫자만 있는 경우(엑셀 시리얼)
    if s.isdigit() and 10000 <= int(s) <= 1000000:
        return True
    return False


def compute_shot_done_series(df, preferred_date_column=None):
    """촬영 완료 여부(0/1) 시리즈를 생성.

    리터칭완료일에 값(날짜)이 있으면 그 행은 촬영 완료(O).
    리터칭완료일 컬럼이 없으면 촬영일자/포토촬영일 등 다른 날짜 컬럼, 없으면 isShot(0/1) 폴백.
    """
    date_col = _find_photo_date_column(df, preferred_name=preferred_date_column)
    if date_col is not None and date_col in df.columns:
        ser = _parse_date_series(df[date_col])
        done = ser.notna().astype(int)
        # 파싱은 실패했지만 값이 날짜 형태인 경우(공백/형식 이슈) O 처리
        if (done == 0).any():
            raw = df[date_col].astype(str).str.strip()
            fallback = raw.apply(_looks_like_date_value).astype(int)
            done = done.where(done == 1, fallback)
        return done

    if "isShot" in df.columns:
        return (pd.to_numeric(df["isShot"], errors="coerce").fillna(0).astype(int) == 1).astype(int)

    return pd.Series([0] * len(df), index=df.index, dtype="int64")

# ----------------------------
# 스냅샷 증감 계산
# ----------------------------
def compute_flow_deltas(df):
    if len(df) < 2:
        return None
    this_week = df.iloc[0]
    last_week = df.iloc[1]
    return {
        "입고": this_week["inboundDone"] - last_week["inboundDone"],
        "출고": this_week["outboundDone"] - last_week["outboundDone"],
        "촬영": this_week["shotDone"] - last_week["shotDone"],
        "등록": this_week["registeredDone"] - last_week["registeredDone"],
        "판매개시": this_week["onSaleDone"] - last_week["onSaleDone"],
    }

# ----------------------------
# 제목
# ----------------------------
st.title("브랜드 상품 흐름 대시보드")
st.caption("입고 · 출고 · 촬영 · 등록 · 판매개시 현황")

# ----------------------------
# Google Sheets 연결 (Secrets만 사용, UI 없음)
# ----------------------------
SPREADSHEET_OPTIONS = {
    "BASE_SPREADSHEET_ID": "BASE",
    "SP_SPREADSHEET_ID": "SP",
    "MI_SPREADSHEET_ID": "MI",
    "CV_SPREADSHEET_ID": "CV",
    "WH_SPREADSHEET_ID": "WH",
    "RM_SPREADSHEET_ID": "RM",
    "EB_SPREADSHEET_ID": "EB",
    "HP_SPREADSHEET_ID": "HP",
    "NK_SPREADSHEET_ID": "NK"
}

def get_spreadsheet_ids_from_secrets():
    ids = {}
    for secret_key, label in SPREADSHEET_OPTIONS.items():
        try:
            val = st.secrets.get(secret_key, "")
            if val and str(val).strip():
                ids[label] = str(val).strip()
        except Exception:
            pass
    return ids

creds_dict = None
try:
    if "gcp_service_account" in st.secrets:
        creds_dict = dict(st.secrets["gcp_service_account"])
    elif "google_service_account" in st.secrets:
        creds_dict = dict(st.secrets["google_service_account"])
except Exception:
    pass
gs_client = get_gsheet_client(creds_dict) if creds_dict else None

spreadsheet_ids = get_spreadsheet_ids_from_secrets()
spreadsheet_title = None
create_spreadsheet_if_missing = False

if not spreadsheet_ids:
    # ID가 없으면(옵션) 제목으로 열기/생성할 수 있게 지원
    # - AUTO_CREATE_SPREADSHEET=true 이고
    # - SPREADSHEET_TITLE(또는 BASE_SPREADSHEET_TITLE)가 있으면
    # 스프레드시트를 생성/오픈 후 계속 진행합니다.
    auto_create = str(st.secrets.get("AUTO_CREATE_SPREADSHEET", "")).strip().lower() in ("1", "true", "yes", "y")
    spreadsheet_title = str(st.secrets.get("SPREADSHEET_TITLE", "")).strip() or str(st.secrets.get("BASE_SPREADSHEET_TITLE", "")).strip()
    if auto_create and spreadsheet_title:
        selected_label = "AUTO"
        spreadsheet_id = None
        create_spreadsheet_if_missing = True
    else:
        st.error("Secrets에 스프레드시트 ID가 없습니다. BASE_SPREADSHEET_ID 등을 설정하거나, AUTO_CREATE_SPREADSHEET=true 와 SPREADSHEET_TITLE을 설정하세요.")
        st.stop()
else:
    # 기본값: Secrets 첫 번째 시트, 첫 시트 탭, 헤더 1행
    selected_label = list(spreadsheet_ids.keys())[0]
    spreadsheet_id = spreadsheet_ids[selected_label]
items_sheet_name = ""
# 헤더 행(1-based). 기본 1 = 1행이 머릿글. 2행이 헤더인 시트면 Secrets에 HEADER_ROW = 2. 자동감지는 HEADER_ROW = 0
_header_raw = st.secrets.get("HEADER_ROW")
if _header_raw is None or str(_header_raw).strip() == "":
    header_row = 0  # 1행이 헤더 (0-based)
elif str(_header_raw).strip().lower() in ("0", "auto", "자동"):
    header_row = -1  # 1~3행 중 '리터칭' 포함된 행 자동 선택
else:
    header_row = int(_header_raw) - 1  # 1-based → 0-based
snapshots_sheet_name = ""

if not gs_client:
    st.info("Streamlit Secrets에 **gcp_service_account** 또는 **google_service_account**를 설정해 주세요.")
    st.stop()

# API 429(Quota exceeded) 완화: 시트 ID만 있을 때 90초 캐시 사용 (header_row 자동감지(-1)일 땐 미사용)
use_cache = spreadsheet_id and not create_spreadsheet_if_missing and not spreadsheet_title and (header_row >= 0)
if use_cache:
    items_df = _cached_load_sheet(
        str(spreadsheet_id).strip(),
        items_sheet_name.strip() if items_sheet_name else "",
        int(header_row),
    )
else:
    items_df = load_sheet_as_dataframe(
        gs_client,
        spreadsheet_id,
        sheet_name=items_sheet_name if items_sheet_name.strip() else None,
        header_row=header_row,
        spreadsheet_title=spreadsheet_title,
        create_spreadsheet_if_missing=create_spreadsheet_if_missing,
    )
if items_df is None:
    st.stop()
if len(items_df) == 0:
    st.warning("시트에 데이터가 없습니다.")
    st.stop()

# 한글/다른 컬럼명을 필수 컬럼명으로 매핑
items_df = apply_column_aliases(items_df)

# 브랜드: 스타일코드(Now) 앞 2자리 → 매핑 테이블 한글명
if "styleCode" in items_df.columns:
    items_df["brand"] = items_df["styleCode"].apply(brand_from_style_code)

# 시트에서 읽은 값은 문자열이므로 숫자 컬럼 변환
# 리터칭 완료일 → isShot, 공홈등록일 → isRegistered: 날짜 문자열을 0/1로 변환 (날짜 있으면 1)
# 시트에 미완료일 때 '0' 넣는 경우가 있으므로 0/'0'은 무조건 '날짜 없음'(0)으로 처리. 구글 시트 날짜(엑셀 시리얼)도 인식
def _date_cell_to_01(ser):
    s = ser.astype(str).str.strip()
    num = pd.to_numeric(ser, errors="coerce")
    no_date = s.isin(("", "0", "0.0", "-", ".")) | (num == 0)
    parsed = pd.to_datetime(ser, errors="coerce")
    # 숫자만 있는데 10000~1000000 구간이면 엑셀/구글 시트 날짜 시리얼 → 유효한 날짜로 간주
    excel_date = num.notna() & (num > 10000) & (num < 1000000)
    if excel_date.any():
        parsed = parsed.fillna(pd.to_datetime(num[excel_date], unit="D", origin="1899-12-30"))
    return (parsed.notna() & ~no_date).astype(int)

if "isShot" in items_df.columns:
    items_df["isShot"] = _date_cell_to_01(items_df["isShot"])
if "isRegistered" in items_df.columns:
    items_df["isRegistered"] = _date_cell_to_01(items_df["isRegistered"])

numeric_cols = [
    "inboundQty", "outboundQty", "stockQty", "salesQty",
    "isShot", "isRegistered", "isOnSale"
]
for col in numeric_cols:
    if col in items_df.columns:
        items_df[col] = pd.to_numeric(items_df[col], errors="coerce").fillna(0).astype(int)

required_columns = [
    "brand", "yearSeason", "styleCode", "productName",
    "colorCode", "colorName", "sizeCode",
    "inboundQty", "outboundQty", "stockQty", "salesQty",
    "isShot", "isRegistered", "isOnSale"
]

missing = [col for col in required_columns if col not in items_df.columns]
if missing:
    items_df = fill_missing_required_columns(items_df, required_columns)

# ----------------------------
# 촬영·등록 여부: 브랜드별 시트(SP/MI/CV/RM/WH)에서만 읽어서 merge. BASE에서는 사용 안 함.
# ----------------------------
preferred_shot_date_col = (st.secrets.get("SHOT_DATE_COLUMN") or "").strip() or None
shot_date_column = None
items_df["__shot_done"] = 0
if "isRegistered" not in items_df.columns:
    items_df["isRegistered"] = 0

if gs_client and spreadsheet_ids and "styleCode" in items_df.columns and "brand" in items_df.columns:
    shot_reg_parts = []
    for brand_name, sheet_key in BRAND_TO_SHEET.items():
        sid = spreadsheet_ids.get(sheet_key)
        if not sid:
            continue
        try:
            _hr = int(header_row) if header_row >= 0 else 0
            b_df = _cached_load_sheet(
                str(sid).strip(),
                items_sheet_name.strip() if items_sheet_name else "",
                _hr,
            )
            if b_df is None or len(b_df) == 0:
                continue
            b_df.columns = [str(c).strip() for c in b_df.columns]
            sc = "styleCode" if "styleCode" in b_df.columns else ("스타일코드" if "스타일코드" in b_df.columns else None)
            if not sc:
                continue
            b_df["_styleCode"] = b_df[sc].apply(_normalize_style_code_for_merge)
            b_df["brand"] = brand_name

            shot_col = _find_photo_date_column(b_df, preferred_name=preferred_shot_date_col)
            if shot_col and shot_col in b_df.columns:
                # 클라비스는 업로드완료일 값 존재 여부만 체크
                if shot_col and shot_col in b_df.columns:
                    b_df["__shot_done"] = _date_cell_to_01(b_df[shot_col])
                    if shot_date_column is None:
                        shot_date_column = f"{sheet_key} 시트 · {shot_col}"
                else:
                    b_df["__shot_done"] = 0
            
                if shot_date_column is None:
                    shot_date_column = f"{sheet_key} 시트 · {shot_col}"
            else:
                b_df["__shot_done"] = 0

            reg_col = _find_registration_date_column(b_df)
            if reg_col and reg_col in b_df.columns:
                b_df["isRegistered"] = _date_cell_to_01(b_df[reg_col])
            else:
                b_df["isRegistered"] = 0

            by_style = b_df.groupby("_styleCode", dropna=False).agg({"__shot_done": "max", "isRegistered": "max"}).reset_index()
            by_style["brand"] = brand_name
            shot_reg_parts.append(by_style[["brand", "_styleCode", "__shot_done", "isRegistered"]])
        except Exception:
            continue

    if shot_reg_parts:
        shot_reg_df = pd.concat(shot_reg_parts, ignore_index=True)
        items_df["_styleCode"] = items_df["styleCode"].apply(_normalize_style_code_for_merge)
        merged = items_df[["_styleCode"]].merge(
            shot_reg_df.drop(columns=["brand"]),
            left_on="_styleCode",
            right_on="_styleCode",
            how="left",
        )
        items_df["__shot_done"] = merged["__shot_done"].fillna(0).astype(int)
        items_df["isRegistered"] = merged["isRegistered"].fillna(0).astype(int)
        items_df.drop(columns=["_styleCode"], inplace=True, errors="ignore")

# ----------------------------
# 단계상태 생성 (모든 스타일코드는 하나의 상태만 가짐)
# ----------------------------
items_df["단계상태"] = items_df.apply(compute_status, axis=1)

# 연도·시즌: 스타일코드 5번째(연도)·6번째(시즌) 자리로 파악. 예: sp23g1fh28 → 2026년, 1시즌 → 20261 시즌 상품
items_df["_year"] = items_df["styleCode"].apply(year_from_style_code)
_ys_from_style = items_df["styleCode"].apply(lambda x: year_season_from_style_code(x)[0])
if (_ys_from_style != "").any():
    items_df["yearSeason"] = items_df["yearSeason"].astype(str)
    items_df.loc[_ys_from_style != "", "yearSeason"] = _ys_from_style[_ys_from_style != ""]
empty_year = items_df["_year"] == ""
if empty_year.any():
    items_df.loc[empty_year, "_year"] = items_df.loc[empty_year, "yearSeason"].astype(str).str[:4]

# ----------------------------
# 필터 영역
# ----------------------------
col1, col2, col3, col4 = st.columns(4)
with col1:
    brand_options = sorted(items_df["brand"].unique())
    default_brand_idx = brand_options.index("스파오") if "스파오" in brand_options else 0
    brand = st.selectbox("브랜드", brand_options, index=default_brand_idx)
with col2:
    year = "2026"  # 연도 고정
    st.selectbox("연도", [year], key="year", disabled=True)
with col3:
    season_options = sorted(
        items_df.loc[items_df["_year"] == year, "yearSeason"].unique()
    )
    year_seasons = st.multiselect(
        "시즌",
        season_options,
        default=season_options if season_options else [],
        key="season",
    )
with col4:
    search = st.text_input(
        "스타일코드 검색",
        placeholder="스타일코드 또는 판정 상태 검색",
    )

if year is not None and year_seasons:
    filtered_df = items_df[
        (items_df["brand"] == brand)
        & (items_df["_year"] == year)
        & (items_df["yearSeason"].isin(year_seasons))
    ].copy()
else:
    filtered_df = items_df[(items_df["brand"] == brand)].copy()
    if year is not None:
        filtered_df = filtered_df[filtered_df["_year"] == year]
    if year_seasons:
        filtered_df = filtered_df[filtered_df["yearSeason"].isin(year_seasons)]

if search:
    filtered_df = filtered_df[
        filtered_df["styleCode"].astype(str).str.contains(search, case=False, na=False)
        | filtered_df["단계상태"].astype(str).str.contains(search, case=False, na=False)
    ]

# 발주 스타일 수(고유 styleCode), 입고/출고 등은 스타일 수로 집계
total_n = filtered_df["styleCode"].nunique()
if total_n == 0:
    st.info("선택한 조건에 맞는 데이터가 없습니다.")
    st.stop()

# 스냅샷 증감 (카드에 함께 표시용)
deltas = None
if snapshots_sheet_name and snapshots_sheet_name.strip():
    snapshots_df = load_sheet_as_dataframe(
        gs_client, spreadsheet_id, sheet_name=snapshots_sheet_name.strip()
    )
    if snapshots_df is not None and len(snapshots_df) >= 2:
        snap_cols = ["inboundDone", "outboundDone", "shotDone", "registeredDone", "onSaleDone"]
        for c in snap_cols:
            if c in snapshots_df.columns:
                snapshots_df[c] = pd.to_numeric(snapshots_df[c], errors="coerce").fillna(0).astype(int)
        deltas = compute_flow_deltas(snapshots_df)

# ----------------------------
# 흐름 집계 카드 (스타일 수 기준: 해당 단계 1건이라도 있으면 스타일 포함)
# ----------------------------
flow_types = ["입고", "출고", "촬영", "등록", "판매개시"]
# 흐름별 조건: 해당 조건을 만족하는 행이 하나라도 있는 스타일 수
_flow_conditions = {
    "입고": (filtered_df["inboundQty"] > 0),
    "출고": (filtered_df["outboundQty"] > 0),
    "촬영": (filtered_df["__shot_done"] == 1),
    "등록": (filtered_df["isRegistered"] == 1),
    "판매개시": (
        (pd.to_numeric(filtered_df["salesQty"], errors="coerce").fillna(0) > 0)
        | (filtered_df["isOnSale"] == 1)
        | (filtered_df["isRegistered"] == 1)
    ),
}
flow_counts = pd.Series({
    flow: filtered_df.loc[cond]["styleCode"].nunique()
    for flow, cond in _flow_conditions.items()
})

if "selected_flow" not in st.session_state:
    st.session_state.selected_flow = flow_types[0]

cols = st.columns(len(flow_types))
for i, flow in enumerate(flow_types):
    is_selected = st.session_state.selected_flow == flow
    count = int(flow_counts.get(flow, 0))
    delta_val = deltas.get(flow, 0) if deltas else None
    delta_str = f"▲{delta_val}" if (delta_val is not None and delta_val > 0) else (str(delta_val) if delta_val is not None else "")
    with cols[i]:
        btn_label = f"{flow}\n{count}/{total_n}"
        if delta_str:
            btn_label += f"  {delta_str}"
        if st.button(
            btn_label,
            type="primary" if is_selected else "secondary",
            use_container_width=True,
            key=f"flow_{flow}",
        ):
            if st.session_state.selected_flow != flow:
                st.session_state.selected_flow = flow
                st.rerun()

selected_flow = st.session_state.selected_flow

# 상세 테이블: 필터된 전체 스타일 사용 (선택한 flow 조건으로만 자르지 않음)
flow_df = filtered_df.copy()

# 스타일 단위: styleCode 기준 집계 (수량 합산, 촬영/등록/판매개시는 하나라도 1이면 1)
if len(flow_df) > 0:
    group_cols = ["brand", "yearSeason", "styleCode"]
    agg_dict = {
        "inboundQty": "sum",
        "outboundQty": "sum",
        "stockQty": "sum",
        "salesQty": "sum",
        "isShot": "max",
        "__shot_done": "max",
        "isRegistered": "max",
        "isOnSale": "max",
    }
    if "productName" in flow_df.columns:
        agg_dict["productName"] = "first"
    if "colorName" in flow_df.columns:
        agg_dict["colorName"] = lambda s: " / ".join(s.dropna().astype(str).unique()[:5])
    flow_df = flow_df.groupby(group_cols, dropna=False).agg(agg_dict).reset_index()

flow_df["단계상태"] = flow_df.apply(compute_status, axis=1)
flow_df["상태"] = flow_df["단계상태"]

# 버튼별 정렬: 해당 단계가 안 된 스타일을 먼저
order_list = FLOW_SORT_ORDER.get(
    selected_flow,
    list(BASE_SORT_ORDER.keys()),
)
order_map = {status: idx for idx, status in enumerate(order_list)}
flow_df["_정렬키"] = flow_df["단계상태"].map(order_map).fillna(99)
flow_df = flow_df.sort_values(by=["_정렬키", "styleCode"], ascending=[True, True])

# 표시용 컬럼: 촬영 O/X, 등록 O/X (판매 열 제거)
flow_df["_촬영"] = flow_df["__shot_done"].map(lambda x: "O" if (pd.notna(x) and int(x) == 1) else "X")
flow_df["_등록"] = flow_df["isRegistered"].map(lambda x: "O" if (pd.notna(x) and x == 1) else "X")

# ----------------------------
# 상세 테이블 (NO, 스타일코드, 상품명, 컬러, 입고/출고/재고, 촬영, 등록, 상태) — 판매 열 제거
# ----------------------------
st.subheader(f"상세 현황 · {selected_flow}")

display_df = flow_df.copy()
display_df.insert(0, "NO", range(1, len(display_df) + 1))
show_cols = ["NO", "styleCode", "productName", "inboundQty", "outboundQty", "stockQty", "_촬영", "_등록", "상태"]
show_cols = [c for c in show_cols if c in display_df.columns]
display_df = display_df[show_cols]
display_df = display_df.rename(columns={
    "styleCode": "스타일코드",
    "productName": "상품명",
    "colorName": "컬러",
    "inboundQty": "입고량",
    "outboundQty": "출고량",
    "stockQty": "재고량",
    "_촬영": "촬영",
    "_등록": "등록",
})

st.dataframe(display_df, use_container_width=True, hide_index=True)

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output) as writer:
        df.to_excel(writer, index=False, sheet_name="상세현황")
    return output.getvalue()

excel_data = to_excel(display_df)
st.download_button(
    label="Download",
    data=excel_data,
    file_name=f"상세현황_{selected_flow}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)



import pandas as pd

# 예시 데이터
data = {
    "스타일코드": ["MIABGG101G"],
    "공홈 등록일": ["2025-11-17"]  # 실제 값
}
df = pd.DataFrame(data)

# 원본 타입 확인
df["공홈 등록일 타입"] = df["공홈 등록일"].apply(lambda x: type(x))
print("원본 타입 확인:")
print(df[["스타일코드", "공홈 등록일", "공홈 등록일 타입"]])

# datetime으로 변환 시도
df["공홈 등록일_dt"] = pd.to_datetime(df["공홈 등록일"], errors="coerce")
df["등록일 변환 성공 여부"] = df["공홈 등록일_dt"].notna()
print("\n변환 후 확인:")
print(df[["스타일코드", "공홈 등록일_dt", "등록일 변환 성공 여부"]])
