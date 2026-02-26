# -*- coding: utf-8 -*-
"""브랜드별·시즌별 스타일 입고/출고/온라인등록 실시간 모니터링. """
from __future__ import annotations

import os
import html as html_lib
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from google.oauth2.service_account import Credentials
from streamlit_cookies_manager import EncryptedCookieManager

st.set_page_config(page_title="전 브랜드 스타일 모니터링", layout="wide", initial_sidebar_state="expanded")


cookies = EncryptedCookieManager(
    prefix="style_dashboard",
    password="very-secret-password"  # 아무 문자열 가능
)

if not cookies.ready():
    st.stop()

# ---- 비밀번호 인증 (처음 접속 시) ----
def _get_expected_password():
    return _secret("DASHBOARD_PASSWORD") or os.environ.get("DASHBOARD_PASSWORD", "").strip()



def _check_auth():
    # 1. 세션 초기화
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    expected = _get_expected_password()
    if not expected:
        st.session_state.authenticated = True
        return

    # 2. 쿠키에 로그인 기록 있으면 자동 통과
    if cookies.get("logged_in") == "true":
        st.session_state.authenticated = True
        return

    # 3. 이미 인증된 경우
    if st.session_state.authenticated:
        return

    # 4. 로그인 UI
    st.markdown(
        "<div style='max-width:400px;margin:4rem auto;padding:2rem;"
        "background:#1e293b;border-radius:12px;border:1px solid #334155;'>",
        unsafe_allow_html=True
    )
    st.markdown("### 🔐 비밀번호를 입력하세요")

    pw = st.text_input(
        "비밀번호",
        type="password",
        key="auth_password",
        placeholder="비밀번호 입력"
    )

    if st.button("입장", key="auth_submit"):
        if pw.strip() == expected:
            st.session_state.authenticated = True

            # ✅ 쿠키 저장
            cookies["logged_in"] = "true"
            cookies.save()

            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다")

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# ---- 설정 ----
def _secret(key, default=""):
    try:
        v = st.secrets.get(key, default) or default
        return str(v).strip() if v else default
    except Exception:
        return default

# 입출고용: BASE_SPREADSHEET_ID / 온라인등록용: ONLINE_SPREADSHEET_ID 하나만 사용 (secrets에서 관리)
BASE_SPREADSHEET_ID = str(_secret("BASE_SPREADSHEET_ID")).strip() or ""
ONLINE_SPREADSHEET_ID = str(_secret("ONLINE_SPREADSHEET_ID")).strip() or ""
GOOGLE_SPREADSHEET_IDS = {"inout": BASE_SPREADSHEET_ID}
# 온라인 스프레드시트 내 워크시트 이름 = 브랜드명 (예: 스파오 시트에서 스파오 데이터)
BRAND_KEY_TO_SHEET_NAME = {"spao": "스파오", "whoau": "후아유", "clavis": "클라비스", "mixxo": "미쏘", "roem": "로엠", "shoopen": "슈펜", "eblin": "에블린"}
brands_list = ["스파오", "뉴발란스", "뉴발란스키즈", "후아유", "슈펜", "미쏘", "로엠", "클라비스", "에블린"]
bu_groups = [("캐쥬얼BU", ["스파오"]), ("스포츠BU", ["뉴발란스", "뉴발란스키즈", "후아유", "슈펜"]), ("여성BU", ["미쏘", "로엠", "클라비스", "에블린"])]
BRAND_TO_KEY = {"스파오": "spao", "후아유": "whoau", "클라비스": "clavis", "미쏘": "mixxo", "로엠": "roem", "슈펜": "shoopen", "에블린": "eblin"}
NO_REG_SHEET_BRANDS = {"뉴발란스", "뉴발란스키즈"}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly", "https://www.googleapis.com/auth/drive.readonly"]

# ---- Google 인증/시트 ----
def _get_google_credentials():
    import json
    try:
        raw = getattr(st.secrets, "get", lambda k, d=None: None)("google_service_account") or _secret("google_service_account")
        if raw:
            info = json.loads(raw) if isinstance(raw, str) else dict(raw)
            if "type" in info and "private_key" in info:
                return Credentials.from_service_account_info(info, scopes=GOOGLE_SCOPES)
    except Exception:
        pass
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path or not os.path.isfile(creds_path):
        for name in ("service_account.json", "credentials.json"):
            p = os.path.join(BASE_DIR, name)
            if os.path.isfile(p):
                creds_path = p
                break
    if not creds_path:
        return None
    try:
        return Credentials.from_service_account_file(creds_path, scopes=GOOGLE_SCOPES)
    except Exception:
        return None

def _fetch_sheet_via_api(sid, creds):
    try:
        from googleapiclient.discovery import build
        from openpyxl import Workbook
        svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
        meta = svc.spreadsheets().get(spreadsheetId=sid).execute()
        names = [s["properties"]["title"] for s in meta.get("sheets", [])]
        if not names:
            return None
        wb = Workbook()
        wb.remove(wb.active)
        for idx, title in enumerate(names):
            try:
                rng = f"'{title.replace(chr(39), chr(39)*2)}'" if title else f"Sheet{idx+1}"
                rows = svc.spreadsheets().values().get(spreadsheetId=sid, range=rng).execute().get("values", [])
            except Exception:
                rows = []
            ws = wb.create_sheet(title=(title[:31] if title else f"Sheet{idx+1}"), index=idx)
            for row in rows:
                ws.append(row)
        out = BytesIO()
        wb.save(out)
        out.seek(0)
        return out.read()
    except Exception:
        return None

@st.cache_data(ttl=300)
def fetch_sheet_bytes(sheet_id):
    if not sheet_id:
        return None
    creds = _get_google_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        fh = BytesIO()
        downloader = MediaIoBaseDownload(fh, service.files().export_media(fileId=sheet_id, mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        while True:
            _, done = downloader.next_chunk()
            if done:
                break
        fh.seek(0)
        return fh.read()
    except Exception:
        pass
    return _fetch_sheet_via_api(sheet_id, creds)

@st.cache_data(ttl=300)
def get_all_sources():
    out = {"inout": (fetch_sheet_bytes(BASE_SPREADSHEET_ID), "inout")}
    online_bytes = fetch_sheet_bytes(ONLINE_SPREADSHEET_ID) if ONLINE_SPREADSHEET_ID else None
    for brand_key in BRAND_KEY_TO_SHEET_NAME:
        out[brand_key] = (online_bytes, brand_key)
    return out

# ---- 컬럼/헤더 탐지 ----
def find_col(keys, df=None):
    if df is None or df.empty:
        return None
    cols = list(df.columns)
    for k in keys:
        for c in cols:
            if str(c).strip() == k:
                return c
    for k in keys:
        for c in cols:
            if k in str(c):
                return c
    return None

def _norm(v):
    return "".join(str(v).split()) if v is not None else ""

def _col_idx(header_vals, key):
    for i, v in enumerate(header_vals):
        if key in _norm(v):
            return i
    return None

def _find_register_header(df_raw):
    for i in range(min(30, len(df_raw))):
        row = df_raw.iloc[i].tolist()
        norm = [_norm(v) for v in row]
        if any("스타일코드" in v for v in norm) and any("공홈등록일" in v for v in norm):
            return i, norm
    return None, None

# ---- BASE 입출고 ----
# target_sheet_name: 지정 시 해당 워크시트 사용 (예: "물류입고스타일수", "온라인입고스타일수"). 미지정 시 기존처럼 첫 번째 비-_ 시트 사용.
@st.cache_data(ttl=300)
def load_base_inout(io_bytes=None, _cache_key=None, target_sheet_name=None):
    if io_bytes is None or len(io_bytes) == 0:
        return pd.DataFrame()
    excel_file = pd.ExcelFile(BytesIO(io_bytes))
    if target_sheet_name and str(target_sheet_name).strip() in excel_file.sheet_names:
        sheet_name = str(target_sheet_name).strip()
    else:
        sheet_candidates = [s for s in excel_file.sheet_names if not str(s).startswith("_")]
        sheet_name = sheet_candidates[0] if sheet_candidates else excel_file.sheet_names[-1]
    preview = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=None)
    kw = ["브랜드", "스타일", "최초입고일", "입고", "출고", "판매"]
    best_row, best_score = None, 0
    for i in range(min(20, len(preview))):
        row = preview.iloc[i].astype(str)
        score = sum(1 for cell in row if any(k in cell for k in kw))
        if score > best_score:
            best_score, best_row = score, i
    df = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=best_row if (best_row is not None and best_score > 0) else 0)
    df.columns = [str(c).strip() for c in df.columns]
    style_col = find_col(["스타일코드", "스타일"], df=df)
    if style_col and style_col in df.columns:
        prefix = df[style_col].astype(str).str.strip().str.lower().str.slice(0, 2)
        df["브랜드"] = prefix.map({"sp": "스파오", "rm": "로엠", "mi": "미쏘", "wh": "후아유", "hp": "슈펜", "cv": "클라비스", "eb": "에블린", "nb": "뉴발란스", "nk": "뉴발란스키즈"})
    return df



@st.cache_data(ttl=1)
def _base_style_to_first_in_map(io_bytes=None, _cache_key=None):
    df = load_base_inout(io_bytes, _cache_key=_cache_key or "inout")
    if df.empty:
        return {}
    style_col = find_col(["스타일코드", "스타일"], df=df)
    first_col = find_col(["최초입고일", "입고일"], df=df)
    if not style_col or not first_col:
        return {}
    df = df.copy()
    df["_style"] = df[style_col].astype(str).str.strip().str.replace(" ", "", regex=False)
    numeric = pd.to_numeric(df[first_col], errors="coerce")
    excel_mask = numeric.between(1, 60000, inclusive="both")
    df["_first_in"] = pd.to_datetime(df[first_col], errors="coerce")
    if excel_mask.any():
        df.loc[excel_mask, "_first_in"] = pd.to_datetime(numeric[excel_mask], unit="d", origin="1899-12-30", errors="coerce")
    df = df[df["_first_in"].notna() & (df["_style"].str.len() > 0)]
    return df.groupby("_style")["_first_in"].min().to_dict() if not df.empty else {}

def _norm_season(val):
    if val is None or pd.isna(val):
        return ""
    try:
        v = int(val)
        if 1900 <= v <= 2100:
            return ""
        return str(v) if -100 < v < 100 else ""
    except Exception:
        pass
    s = str(val).strip().replace("시즌", "").replace(" ", "").strip()
    if s.endswith(".0") and len(s) >= 2 and s[:-2].replace("-", "").isdigit():
        return s[0] if s[0] != "-" else (s[1] if len(s) > 2 else "")
    if not s or (s.isdigit() and len(s) >= 3):
        return ""
    s = s.upper()
    return s[1] if len(s) >= 2 and s[0].isalpha() else s[0]

# ---- 브랜드 등록 시트 ----
@st.cache_data(ttl=120)
def load_brand_register_df(io_bytes=None, _cache_key=None, target_sheet_name=None):
    if io_bytes is None or len(io_bytes) == 0:
        return pd.DataFrame()
    try:
        excel_file = pd.ExcelFile(BytesIO(io_bytes))
    except Exception:
        return pd.DataFrame()
    sheet_names = ([target_sheet_name] if target_sheet_name and target_sheet_name in excel_file.sheet_names else
                   (excel_file.sheet_names if not target_sheet_name else []))
    for sheet_name in sheet_names:
        try:
            df_raw = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=None)
        except Exception:
            continue
        if df_raw is None or df_raw.empty:
            continue
        header_row_idx, header_vals = _find_register_header(df_raw)
        if header_row_idx is None:
            continue
        style_col = _col_idx(header_vals, "스타일코드") or _col_idx(header_vals, "스타일")
        regdate_col = _col_idx(header_vals, "공홈등록일")
        season_col = _col_idx(header_vals, "시즌")
        if style_col is None or regdate_col is None:
            continue
        data = df_raw.iloc[header_row_idx + 1:].copy()
        data.columns = range(data.shape[1])
        out = pd.DataFrame()
        out["스타일코드"] = data.iloc[:, style_col].astype(str).str.strip()
        out["시즌"] = data.iloc[:, season_col].astype(str).str.strip() if season_col is not None and season_col < data.shape[1] else ""
        reg_ok = pd.to_datetime(data.iloc[:, regdate_col], errors="coerce").notna()
        out["온라인상품등록여부"] = reg_ok.map({True: "등록", False: "미등록"})
        out = out[out["스타일코드"].str.len() > 0]
        out = out[out["스타일코드"] != "nan"]
        return out
    return pd.DataFrame()

def _parse_date_series(col_series):
    """컬럼 시리즈를 날짜 시리즈로 변환 (엑셀 숫자일 포함)."""
    s = col_series.replace(0, pd.NA).replace("0", pd.NA)
    numeric = pd.to_numeric(s, errors="coerce")
    excel_mask = numeric.between(1, 60000, inclusive="both")
    dt = pd.to_datetime(s, errors="coerce")
    if excel_mask.any():
        dt = dt.copy()
        dt.loc[excel_mask] = pd.to_datetime(numeric[excel_mask], unit="d", origin="1899-12-30", errors="coerce")
    return dt


@st.cache_data(ttl=10)
def load_brand_register_avg_days(reg_bytes=None, inout_bytes=None, _cache_key=None, _inout_cache_key=None, selected_seasons_tuple=None, target_sheet_name=None):
    """브랜드별 평균 소요일수 반환. dict 키: 평균전체등록소요일수, 포토인계소요일수, 포토소요일수, 상품등록소요일수."""
    if not reg_bytes or len(reg_bytes) == 0:
        return None
    base_map = _base_style_to_first_in_map(inout_bytes, _inout_cache_key or "inout") if inout_bytes else {}
    if not base_map:
        return None
    try:
        excel_file = pd.ExcelFile(BytesIO(reg_bytes))
    except Exception:
        return None
    sheet_names = ([target_sheet_name] if target_sheet_name and target_sheet_name in excel_file.sheet_names else
                   (excel_file.sheet_names if not target_sheet_name else []))
    for sheet_name in sheet_names:
        try:
            df_raw = pd.read_excel(BytesIO(reg_bytes), sheet_name=sheet_name, header=None)
        except Exception:
            continue
        if df_raw is None or df_raw.empty:
            continue
        header_row_idx, header_vals = _find_register_header(df_raw)
        if header_row_idx is None:
            continue
        style_col = _col_idx(header_vals, "스타일코드") or _col_idx(header_vals, "스타일")
        regdate_col = _col_idx(header_vals, "공홈등록일")
        season_col = _col_idx(header_vals, "시즌")
        photo_handover_col = _col_idx(header_vals, "포토인계일")
        retouch_done_col = _col_idx(header_vals, "리터칭완료일")
        if style_col is None or regdate_col is None:
            continue
        data = df_raw.iloc[header_row_idx + 1:].copy()
        data.columns = range(data.shape[1])
        if selected_seasons_tuple and season_col is not None and season_col < data.shape[1]:
            season_series = data.iloc[:, season_col].astype(str)
            norm_sel = [s for s in [_norm_season(x) for x in selected_seasons_tuple] if s]
            if norm_sel:
                mask_filter = season_series.map(_norm_season).isin(norm_sel)
                raw = season_series.str.strip().str.upper()
                mask_strict = pd.Series(False, index=data.index)
                for s in norm_sel:
                    mask_strict = mask_strict | raw.str.match(f"^G?{s}$", na=False)
                data = data.loc[mask_filter & mask_strict]
        if data.empty:
            continue
        style_series = data.iloc[:, style_col]
        reg_dt = _parse_date_series(data.iloc[:, regdate_col])
        photo_dt = _parse_date_series(data.iloc[:, photo_handover_col]) if photo_handover_col is not None and photo_handover_col < data.shape[1] else pd.Series(pd.NaT, index=data.index)
        retouch_dt = _parse_date_series(data.iloc[:, retouch_done_col]) if retouch_done_col is not None and retouch_done_col < data.shape[1] else pd.Series(pd.NaT, index=data.index)
        style_ok = style_series.astype(str).str.strip().replace(r"^\s*$", pd.NA, regex=True).notna()
        register_ok = reg_dt.notna()
        total_diffs = []
        photo_handover_diffs = []
        photo_diffs = []
        register_diffs = []
        for idx in data.index:
            if not (style_ok.loc[idx] and register_ok.loc[idx]):
                continue
            style_norm = "".join(str(style_series.loc[idx]).split())
            base_dt = base_map.get(style_norm)
            if base_dt is None or pd.isna(reg_dt.loc[idx]):
                continue
            total_days = (reg_dt.loc[idx] - base_dt).days
            total_diffs.append(max(0, total_days))
            if photo_dt.notna().loc[idx] and photo_handover_col is not None:
                d = (photo_dt.loc[idx] - base_dt).days
                photo_handover_diffs.append(max(0, d))
            if retouch_dt.notna().loc[idx] and photo_dt.notna().loc[idx] and retouch_done_col is not None:
                d = (retouch_dt.loc[idx] - photo_dt.loc[idx]).days
                photo_diffs.append(max(0, d))
            if retouch_dt.notna().loc[idx] and retouch_done_col is not None:
                d = (reg_dt.loc[idx] - retouch_dt.loc[idx]).days
                register_diffs.append(max(0, d))
        result = {
            "평균전체등록소요일수": float(sum(total_diffs)) / len(total_diffs) if total_diffs else None,
            "포토인계소요일수": float(sum(photo_handover_diffs)) / len(photo_handover_diffs) if photo_handover_diffs else None,
            "포토소요일수": float(sum(photo_diffs)) / len(photo_diffs) if photo_diffs else None,
            "상품등록소요일수": float(sum(register_diffs)) / len(register_diffs) if register_diffs else None,
        }
        return result
    return None

# ---- 스타일 테이블 / 입출고 집계 ----
def build_style_table_all(sources):
    base_bytes = sources.get("inout", (None, None))[0]
    # 물류입고스타일수: base 스프레드시트의 "물류입고스타일수" 워크시트 사용
    df_base = load_base_inout(base_bytes, _cache_key="inout_물류", target_sheet_name="물류입고스타일수")
    if df_base.empty and base_bytes:
        df_base = load_base_inout(base_bytes, _cache_key="inout", target_sheet_name=None)
    if df_base.empty:
        return pd.DataFrame()
    style_col = find_col(["스타일코드", "스타일"], df=df_base)
    brand_col = "브랜드" if "브랜드" in df_base.columns else None
    season_col = find_col(["시즌", "season"], df=df_base)
    first_in_col = find_col(["최초입고일", "입고일"], df=df_base)
    out_amt_col = find_col(["출고액"], df=df_base)
    in_qty_col = find_col(["입고량"], df=df_base)
    in_amt_col = find_col(["누적입고액", "입고액"], df=df_base)
    if not style_col or not brand_col:
        return pd.DataFrame()
    df_base = df_base[df_base[style_col].astype(str).str.strip().str.len() > 0].copy()
    df_base["_style"] = df_base[style_col].astype(str).str.strip()
    df_base["_brand"] = df_base[brand_col].astype(str).str.strip()
    df_base["_season"] = df_base[season_col].astype(str).str.strip() if season_col and season_col in df_base.columns else ""
    first_vals = df_base[first_in_col] if first_in_col and first_in_col in df_base.columns else pd.Series(dtype=object)
    in_date = pd.to_datetime(first_vals, errors="coerce")
    in_date_ok = in_date.notna()
    if first_in_col and first_in_col in df_base.columns:
        num = pd.to_numeric(df_base[first_in_col], errors="coerce")
        in_date_ok = in_date_ok | num.between(1, 60000, inclusive="both")
    has_qty = pd.to_numeric(df_base[in_qty_col], errors="coerce").fillna(0) > 0 if in_qty_col and in_qty_col in df_base.columns else pd.Series(False, index=df_base.index)
    has_amt = pd.to_numeric(df_base[in_amt_col], errors="coerce").fillna(0) > 0 if in_amt_col and in_amt_col in df_base.columns else pd.Series(False, index=df_base.index)
    df_base["_입고"] = in_date_ok | has_qty | has_amt
    out_vals = df_base[out_amt_col] if out_amt_col and out_amt_col in df_base.columns else pd.Series(0, index=df_base.index)
    df_base["_출고"] = pd.to_numeric(out_vals, errors="coerce").fillna(0) > 0

    def pick_season(s, in_flag):
        s2 = s[in_flag]
        s2 = s2.dropna().astype(str).str.strip()
        return s2.iloc[0] if len(s2) else ""

    base_agg = (
        df_base.groupby(["_brand", "_style"])
        .apply(lambda g: pd.Series({
            "시즌": pick_season(g["_season"], g["_입고"]),
            "입고여부": g["_입고"].any(),
            "출고여부": g["_출고"].any(),
        }))
        .reset_index()
    )
    base_agg = base_agg.rename(columns={"_brand": "브랜드", "_style": "스타일코드"})
    rows = []
    for brand_name in base_agg["브랜드"].dropna().unique().tolist():
        b_agg = base_agg[base_agg["브랜드"] == brand_name]
        brand_key = BRAND_TO_KEY.get(brand_name)
        reg_status = "미등록"
        if brand_key:
            reg_bytes = sources.get(brand_key, (None, None))[0]
            df_reg = load_brand_register_df(reg_bytes, _cache_key=brand_key, target_sheet_name=BRAND_KEY_TO_SHEET_NAME.get(brand_key))
            if not df_reg.empty:
                df_reg = df_reg.copy()
                df_reg["스타일코드_norm"] = df_reg["스타일코드"].str.strip()
                merged = b_agg.merge(df_reg[["스타일코드_norm", "온라인상품등록여부"]], left_on="스타일코드", right_on="스타일코드_norm", how="left")
                for _, r in merged.iterrows():
                    reg = r.get("온라인상품등록여부", "미등록")
                    if pd.isna(reg) or str(reg).strip() == "":
                        reg = "미등록"
                    rows.append({"브랜드": brand_name, "스타일코드": r["스타일코드"], "시즌": r["시즌"], "입고 여부": "Y" if r["입고여부"] else "N", "출고 여부": "Y" if r["출고여부"] else "N", "온라인상품등록여부": reg})
                continue
        for _, r in b_agg.iterrows():
            rows.append({"브랜드": brand_name, "스타일코드": r["스타일코드"], "시즌": r["시즌"], "입고 여부": "Y" if r["입고여부"] else "N", "출고 여부": "Y" if r["출고여부"] else "N", "온라인상품등록여부": reg_status})
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def build_inout_aggregates(io_bytes):
    df = load_base_inout(io_bytes, _cache_key="base")
    if df.empty:
        return [], {}, pd.DataFrame()
    style_col = find_col(["스타일코드", "스타일"], df=df)
    brand_col = "브랜드" if "브랜드" in df.columns else None
    order_qty_col = find_col(["발주 STY", "발주수", "발주량"], df=df)
    order_amt_col = find_col(["발주액"], df=df)
    in_amt_col = find_col(["누적입고액", "입고액"], df=df)
    out_amt_col = find_col(["출고액"], df=df)
    sale_amt_col = find_col(["누적판매액", "판매액"], df=df)
    first_in_col = find_col(["최초입고일", "입고일"], df=df)
    in_qty_col = find_col(["입고량"], df=df)
    if not style_col or not brand_col:
        return [], {}, pd.DataFrame()
    season_col = find_col(["시즌", "season"], df=df)
    df["_style"] = df[style_col].astype(str).str.strip()
    df["_brand"] = df[brand_col].astype(str).str.strip()
    df["_season"] = df[season_col].astype(str).str.strip() if season_col and season_col in df.columns else ""
    in_date = pd.to_datetime(df[first_in_col], errors="coerce") if first_in_col and first_in_col in df.columns else pd.Series(pd.NaT, index=df.index)
    in_date_ok = in_date.notna()
    if first_in_col and first_in_col in df.columns:
        num = pd.to_numeric(df[first_in_col], errors="coerce")
        in_date_ok = in_date_ok | num.between(1, 60000, inclusive="both")
    has_qty = pd.to_numeric(df[in_qty_col], errors="coerce").fillna(0) > 0 if in_qty_col and in_qty_col in df.columns else pd.Series(False, index=df.index)
    has_amt = pd.to_numeric(df[in_amt_col], errors="coerce").fillna(0) > 0 if in_amt_col and in_amt_col in df.columns else pd.Series(False, index=df.index)
    df["_in"] = in_date_ok | has_qty | has_amt
    df["_out"] = pd.to_numeric(df[out_amt_col], errors="coerce").fillna(0) > 0 if out_amt_col else False
    df["_sale"] = pd.to_numeric(df[sale_amt_col], errors="coerce").fillna(0) > 0 if sale_amt_col else False

    def sum_amt(g, c):
        return pd.to_numeric(g[c], errors="coerce").fillna(0).sum() if c and c in g.columns else 0

    in_g = df[df["_in"]].groupby("_brand")
    out_g = df[df["_out"]].groupby("_brand")
    sale_g = df[df["_sale"]].groupby("_brand") if sale_amt_col else df.groupby("_brand")
    brand_in_qty = in_g["_style"].nunique().to_dict()
    brand_out_qty = out_g["_style"].nunique().to_dict()
    brand_sale_qty = sale_g["_style"].nunique().to_dict()
    brand_order_qty = df.groupby("_brand")["_style"].nunique().to_dict() if order_qty_col else {}
    brand_order_amt = df.groupby("_brand").apply(lambda g: sum_amt(g, order_amt_col)).to_dict() if order_amt_col else {}
    brand_in_amt = df[df["_in"]].groupby("_brand").apply(lambda g: sum_amt(g, in_amt_col)).to_dict() if in_amt_col else {}
    brand_out_amt = df[df["_out"]].groupby("_brand").apply(lambda g: sum_amt(g, out_amt_col)).to_dict() if out_amt_col else {}
    brand_sale_amt = df.groupby("_brand").apply(lambda g: sum_amt(g, sale_amt_col)).to_dict() if sale_amt_col else {}

    def fmt_num(v):
        return f"{int(v):,}" if pd.notna(v) and v != "" else "0"
    def fmt_eok(v):
        try:
            return f"{float(v) / 1e8:,.0f} 억 원"
        except Exception:
            return "0 억 원"

    rows = [{"브랜드": b, "발주 STY수": fmt_num(brand_order_qty.get(b, 0)), "발주액": fmt_eok(brand_order_amt.get(b, 0)), "입고 STY수": fmt_num(brand_in_qty.get(b, 0)), "입고액": fmt_eok(brand_in_amt.get(b, 0)), "출고 STY수": fmt_num(brand_out_qty.get(b, 0)), "출고액": fmt_eok(brand_out_amt.get(b, 0)), "판매 STY수": fmt_num(brand_sale_qty.get(b, 0)), "판매액": fmt_eok(brand_sale_amt.get(b, 0))} for _, bu_brands in bu_groups for b in bu_brands]
    g = df.groupby(["_brand", "_season"])
    bs_parts = []
    for (b, s), grp in g:
        in_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_in"]]
        out_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_out"]]
        sale_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_sale"]]
        bs_parts.append({"브랜드": b, "시즌": s, "발주 STY수": grp["_style"].nunique(), "발주액": sum_amt(grp, order_amt_col) if order_amt_col else 0, "입고 STY수": in_grp["_style"].nunique(), "입고액": sum_amt(in_grp, in_amt_col) if in_amt_col else 0, "출고 STY수": out_grp["_style"].nunique(), "출고액": sum_amt(out_grp, out_amt_col) if out_amt_col else 0, "판매 STY수": sale_grp["_style"].nunique(), "판매액": sum_amt(grp, sale_amt_col) if sale_amt_col else 0})
    return rows, {"brand_in_qty": brand_in_qty, "brand_out_qty": brand_out_qty, "brand_sale_qty": brand_sale_qty}, pd.DataFrame(bs_parts)

# ---- CSS (압축) ----
DARK_CSS = """<style>
.stApp,.block-container{background:#0f172a}.block-container{padding-top:2.5rem;padding-bottom:2rem}
.fashion-title{display:inline-block;background:#14b8a6;color:#0f172a;padding:0.65rem 1.2rem;border-radius:8px 8px 0 0;font-weight:700;font-size:1.25rem;margin:0.5rem 0 0}
.update-time{font-size:0.85rem;color:#94a3b8;margin-top:0.25rem}
.section-title{font-size:2.2rem;font-weight:700;color:#f1f5f9;margin:1rem 0 0.5rem 0}
.kpi-card-dark{background:#1e293b;color:#f1f5f9;border-radius:10px;padding:1rem 1.2rem;text-align:center;font-weight:600;min-height:100px;display:flex;flex-direction:column;justify-content:center;border:1px solid #334155}
.kpi-card-dark .label{font-size:1.1rem;margin-bottom:0.3rem;color:#cbd5e1}.kpi-card-dark .value{font-size:1rem;font-weight:700;color:#f1f5f9}
.monitor-table{width:100%;border-collapse:collapse;background:#1e293b;color:#f1f5f9}
.monitor-table th,.monitor-table td{border:none;padding:6px 8px;text-align:center;font-size:0.95rem}
.monitor-table thead th{background:#0f172a;color:#f1f5f9;font-weight:700}
.monitor-table thead th.col-emphasis{border:3px solid #fbbf24}
.monitor-table tr.bu-row td{background:#d9f7ee;color:#000;font-size:1.15rem;font-weight:700}
.monitor-table .rate-help,.monitor-table .avg-help,.monitor-table .sum-help{position:relative;display:inline-block;cursor:help}
.monitor-table .rate-help::after,.monitor-table .avg-help::after,.monitor-table .sum-help::after{content:"";position:absolute;opacity:0;pointer-events:none;left:50%;transform:translateX(-50%);bottom:calc(100% + 6px);white-space:pre-line;width:max-content;max-width:360px;background:#ffffff;color:#1e293b;padding:8px 12px;border-radius:6px;font-size:0.85rem;text-align:left;box-shadow:0 4px 12px rgba(0,0,0,0.2);border:1px solid #e2e8f0;z-index:20}
.monitor-table .rate-help:hover::after,.monitor-table .avg-help:hover::after,.monitor-table .sum-help:hover::after{content:attr(data-tooltip);opacity:1}
.monitor-table th.th-sort{white-space:nowrap;cursor:default}.monitor-table th.th-sort .sort-arrow{color:#94a3b8;text-decoration:none;margin-left:4px;font-size:0.75rem;cursor:pointer}.monitor-table th.th-sort .sort-arrow:hover{color:#f1f5f9}
.monitor-table .rate-cell,.monitor-table .avg-cell{display:inline-flex;align-items:center;gap:6px;justify-content:center;position:relative;cursor:help}
.monitor-table .rate-dot{width:16px;height:16px;border-radius:50%;display:inline-block}
.monitor-table .rate-red{background:#ef4444}.monitor-table .rate-yellow{background:#f59e0b}.monitor-table .rate-green{background:#22c55e}
.monitor-table .rate-cell::after,.monitor-table .avg-cell::after{content:"";position:absolute;opacity:0;pointer-events:none;left:50%;transform:translateX(-50%);bottom:calc(100% + 6px);white-space:pre-line;width:max-content;max-width:360px;background:#ffffff;color:#1e293b;padding:8px 12px;border-radius:6px;font-size:0.85rem;box-shadow:0 4px 12px rgba(0,0,0,0.2);border:1px solid #e2e8f0;z-index:20}
.monitor-table .rate-cell:hover::after,.monitor-table .avg-cell:hover::after{content:attr(data-tooltip);opacity:1}
.monitor-table thead th:hover{z-index:10}
.monitor-table .avg-help.tt-left::after{left:0;transform:translateX(0);bottom:calc(100% + 6px)}
.monitor-table td.col-emphasis,.monitor-table th.col-emphasis{font-size:1.045rem;color:#fbbf24}
.monitor-table td.col-small,.monitor-table th.col-small{font-size:0.855rem}
.monitor-table .th-sub{font-size:0.7rem;color:#f1f5f9;font-weight:normal;display:block;margin-top:2px}
.monitor-table{table-layout:fixed}
.monitor-table th.col-small,.monitor-table td.col-small{width:90px;min-width:90px;max-width:90px;box-sizing:border-box}
.monitor-table th.col-emphasis,.monitor-table td.col-emphasis{width:120px;min-width:120px;max-width:120px;box-sizing:border-box}
.monitor-table thead th.col-emphasis{border:3px solid #fbbf24}
.table-wrap.monitor-table-wrap{max-height:500px;overflow-y:auto;overflow-x:auto;border:1px solid #334155;border-radius:8px}
.inout-table{width:100%;border-collapse:collapse;background:#1e293b;color:#f1f5f9;border:1px solid #334155;border-radius:8px;overflow:hidden}
.inout-table th,.inout-table td{border:1px solid #334155;padding:6px 8px;text-align:center;font-size:0.95rem}
.inout-table thead th{background:#0f172a;color:#f1f5f9;font-weight:700}
.inout-table tr.bu-row td{background:#d9f7ee;color:#000;font-size:1.15rem;font-weight:700}.inout-table .brand-cell{text-align:left}
[data-testid='stSelectbox'] label,[data-testid='stMultiSelect'] label{color:#f1f5f9!important}
</style>"""

# 접속 전 비밀번호 확인 (반드시 대시보드 렌더링 전에 호출)
_check_auth()

update_time = datetime.now()
sources = get_all_sources()

base_bytes = sources.get("inout", (None, None))[0]
df_style_all = build_style_table_all(sources)
st.markdown(DARK_CSS, unsafe_allow_html=True)

col_head_left, col_head_right = st.columns([2, 3])
with col_head_left:
    st.markdown('<div class="fashion-title">온라인 리드타임 대시보드</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="update-time">업데이트시간 {update_time.strftime("%Y-%m-%d %H:%M")}</div>', unsafe_allow_html=True)
with col_head_right:
    col_yr, col_season, col_brand = st.columns([1, 2, 2])
    with col_yr:
        st.markdown('<div style="font-size:0.875rem;color:#f1f5f9;margin-bottom:0.25rem;">연도</div>', unsafe_allow_html=True)
        st.markdown('<div style="font-weight:600;color:#f8fafc;">2026년</div>', unsafe_allow_html=True)
    
    with col_season:
        seasons = ["1", "2", "A", "S", "F"]
        selected_seasons = st.multiselect("시즌", seasons, default=seasons, key="season_filter")

    with col_brand:
        brands_list = ["스파오", "미쏘", "후아유", "로엠", "뉴발란스", "뉴발란스키즈", "슈펜", "에블린", "클라비스"]
        selected_brand = st.selectbox("브랜드", brands_list, index=brands_list.index("후아유"), key="brand_filter")
    

def _season_matches(season_series, selected_list):
    if not selected_list:
        return pd.Series(True, index=season_series.index)
    s = season_series.astype(str).str.strip()
    mask = pd.Series(False, index=season_series.index)
    for sel in selected_list:
        sel = str(sel).strip()
        mask = mask | (s == sel) | (s.str.startswith(sel) & (s.str.len() == len(sel) | ~s.str.slice(len(sel), len(sel) + 1).str.isalnum().fillna(True)))
    return mask

df_style = df_style_all.copy()
if selected_seasons and set(selected_seasons) != set(seasons):
    df_style = df_style[_season_matches(df_style["시즌"], selected_seasons)]
if selected_brand and selected_brand != "브랜드 전체":
    df_style = df_style[df_style["브랜드"] == selected_brand]

inout_rows, inout_agg, brand_season_df = build_inout_aggregates(base_bytes)
df_base = load_base_inout(base_bytes, _cache_key="base")
if selected_brand and selected_brand != "브랜드 전체" and "브랜드" in df_base.columns:
    df_base = df_base[df_base["브랜드"].astype(str).str.strip() == selected_brand].copy()
df_kpi = df_base.copy()
season_col = find_col(["시즌", "season"], df=df_base)
if selected_seasons and set(selected_seasons) != set(seasons) and season_col and season_col in df_base.columns:
    df_kpi = df_base[_season_matches(df_base[season_col], selected_seasons)].copy()

in_amt_col = find_col(["누적입고액", "입고액"], df=df_base)
out_amt_col = find_col(["출고액"], df=df_base)
sale_amt_col = find_col(["누적 판매액[외형매출]", "누적판매액", "판매액"], df=df_base)
first_in_col = find_col(["최초입고일", "입고일"], df=df_base)
in_qty_col = find_col(["입고량"], df=df_base)
style_col = find_col(["스타일코드", "스타일"], df=df_base)
total_in_amt = pd.to_numeric(df_kpi[in_amt_col], errors="coerce").sum() if in_amt_col and in_amt_col in df_kpi.columns else 0
total_out_amt = pd.to_numeric(df_kpi[out_amt_col], errors="coerce").sum() if out_amt_col and out_amt_col in df_kpi.columns else 0
total_sale_amt = pd.to_numeric(df_kpi[sale_amt_col], errors="coerce").sum() if sale_amt_col and sale_amt_col in df_kpi.columns else 0

if not df_kpi.empty and style_col and style_col in df_kpi.columns:
    df_kpi = df_kpi.copy()
    df_kpi["_style"] = df_kpi[style_col].astype(str).str.strip()
    first_vals_kpi = df_kpi[first_in_col] if first_in_col and first_in_col in df_kpi.columns else pd.Series(dtype=object)
    in_date = pd.to_datetime(first_vals_kpi, errors="coerce")
    in_date_ok = in_date.notna()
    if first_in_col and first_in_col in df_kpi.columns:
        num = pd.to_numeric(df_kpi[first_in_col], errors="coerce")
        in_date_ok = in_date_ok | num.between(1, 60000, inclusive="both")
    has_qty = pd.to_numeric(df_kpi[in_qty_col], errors="coerce").fillna(0) > 0 if in_qty_col and in_qty_col in df_kpi.columns else pd.Series(False, index=df_kpi.index)
    has_amt = pd.to_numeric(df_kpi[in_amt_col], errors="coerce").fillna(0) > 0 if in_amt_col and in_amt_col in df_kpi.columns else pd.Series(False, index=df_kpi.index)
    df_kpi["_in"] = in_date_ok | has_qty | has_amt
    df_kpi["_out"] = pd.to_numeric(df_kpi[out_amt_col], errors="coerce").fillna(0) > 0 if out_amt_col else False
    df_kpi["_sale"] = pd.to_numeric(df_kpi[sale_amt_col], errors="coerce").fillna(0) > 0 if sale_amt_col else False
    total_in_sty = df_kpi[df_kpi["_in"]]["_style"].nunique()
    total_out_sty = df_kpi[df_kpi["_out"]]["_style"].nunique()
    total_sale_sty = df_kpi[df_kpi["_sale"]]["_style"].nunique()
else:
    if selected_brand and selected_brand != "브랜드 전체":
        total_in_sty = inout_agg.get("brand_in_qty", {}).get(selected_brand, 0)
        total_out_sty = inout_agg.get("brand_out_qty", {}).get(selected_brand, 0)
        total_sale_sty = inout_agg.get("brand_sale_qty", {}).get(selected_brand, 0)
    else:
        total_in_sty = sum(inout_agg.get("brand_in_qty", {}).values())
        total_out_sty = sum(inout_agg.get("brand_out_qty", {}).values())
        total_sale_sty = sum(inout_agg.get("brand_sale_qty", {}).values())

def _eok(x):
    try:
        return f"{float(x) / 1e8:,.2f}"
    except Exception:
        return "0"

st.markdown("<div style='margin-top:1rem;'></div>", unsafe_allow_html=True)
k1, k2, k3 = st.columns(3)
for col, label, amt, sty in [(k1, "입고", total_in_amt, total_in_sty), (k2, "출고", total_out_amt, total_out_sty), (k3, "전체 판매", total_sale_amt, total_sale_sty)]:
    with col:
        st.markdown(f'<div class="kpi-card-dark"><span class="label">{label}</span><span class="value">{_eok(amt)} 억원 / {int(sty):,}STY</span></div>', unsafe_allow_html=True)

st.markdown("<div style='margin-top:80px;'></div>", unsafe_allow_html=True)
st.markdown("---")
st.markdown('<div class="section-title">(온라인) 상품등록 모니터링</div>', unsafe_allow_html=True)
st.markdown('<div style="font-size:0.8rem;color:#cbd5e1;margin-bottom:0.5rem;">가등록한 스타일은 등록으로 인정되지 않습니다 </div>', unsafe_allow_html=True)

df_for_table = df_style_all.copy()
if selected_seasons and set(selected_seasons) != set(seasons):
    df_for_table = df_for_table[_season_matches(df_for_table["시즌"], selected_seasons)]
df_style_unique = df_for_table.drop_duplicates(subset=["브랜드", "시즌", "스타일코드"])
df_in = df_style_unique[df_style_unique["입고 여부"] == "Y"]
all_brands = sorted(df_style_all["브랜드"].unique())
table_df = pd.DataFrame({"브랜드": all_brands})
# 물류입고스타일수: base 스프레드시트 "물류입고스타일수" 시트 기준 (df_in은 이미 해당 시트에서 생성됨)
table_df["물류입고스타일수"] = table_df["브랜드"].map(df_in.groupby("브랜드")["스타일코드"].nunique()).fillna(0).astype(int)
# 온라인입고스타일수: base 스프레드시트 "온라인입고스타일수" 시트에서 브랜드별 스타일 수
base_bytes = sources.get("inout", (None, None))[0]
df_online_in = load_base_inout(base_bytes, _cache_key="inout_온라인입고", target_sheet_name="온라인입고스타일수") if base_bytes else pd.DataFrame()
if not df_online_in.empty:
    style_col_oi = find_col(["스타일코드", "스타일"], df=df_online_in)
    brand_col_oi = "브랜드" if "브랜드" in df_online_in.columns else None
    if style_col_oi and brand_col_oi:
        table_df["온라인입고스타일수"] = table_df["브랜드"].map(df_online_in.groupby("브랜드")[style_col_oi].nunique()).fillna(0).astype(int)
    else:
        table_df["온라인입고스타일수"] = 0
else:
    table_df["온라인입고스타일수"] = 0
table_df["온라인등록스타일수"] = table_df["브랜드"].map(df_in[df_in["온라인상품등록여부"] == "등록"].groupby("브랜드")["스타일코드"].nunique()).fillna(0).astype(int)
# 온라인등록율 = 브랜드별 (온라인등록스타일수 / 온라인입고스타일수), 단위 %
denom = table_df["온라인입고스타일수"].replace(0, pd.NA)
table_df["온라인등록율"] = (table_df["온라인등록스타일수"] / denom).fillna(0).round(2)
table_df["전체 미등록스타일"] = table_df["물류입고스타일수"] - table_df["온라인등록스타일수"]
table_df["등록수"] = table_df["온라인등록스타일수"]
table_df["평균전체등록소요일수"] = "-"
table_df["포토인계소요일수"] = "-"
table_df["포토 소요일수"] = "-"
table_df["상품등록소요일수"] = "-"
table_df["미분배(분배팀)"] = "-"
_season_tuple = tuple(selected_seasons) if selected_seasons else None
for brand_name in table_df["브랜드"].unique():
    if brand_name in NO_REG_SHEET_BRANDS or not BRAND_TO_KEY.get(brand_name):
        continue
    reg_bytes = sources.get(BRAND_TO_KEY[brand_name], (None, None))[0]
    if not reg_bytes:
        continue
    avg_days = load_brand_register_avg_days(reg_bytes, base_bytes, _cache_key=BRAND_TO_KEY[brand_name], _inout_cache_key="inout", selected_seasons_tuple=_season_tuple, target_sheet_name=BRAND_KEY_TO_SHEET_NAME.get(BRAND_TO_KEY[brand_name]))
    if avg_days is not None:
        for key, col in [("평균전체등록소요일수", "평균전체등록소요일수"), ("포토인계소요일수", "포토인계소요일수"), ("포토소요일수", "포토 소요일수"), ("상품등록소요일수", "상품등록소요일수")]:
            v = avg_days.get(key)
            if v is not None:
                table_df.loc[table_df["브랜드"] == brand_name, col] = f"{v:.1f}"
for b in NO_REG_SHEET_BRANDS:
    if b in table_df["브랜드"].values:
        table_df.loc[table_df["브랜드"] == b, "온라인등록스타일수"] = -1
        table_df.loc[table_df["브랜드"] == b, "온라인등록율"] = -1.0

bu_labels = {label for label, _ in bu_groups}
monitor_df = table_df.copy()
monitor_df["_등록율"] = monitor_df.apply(lambda r: "-" if r["브랜드"] in NO_REG_SHEET_BRANDS else str(int(r["온라인등록율"] * 100) if r["온라인등록율"] >= 0 else 0) + "%", axis=1)
monitor_df = monitor_df.sort_values("물류입고스타일수", ascending=False).reset_index(drop=True)

TOOLTIP_RATE = "(초록불) 90% 초과&#10;(노란불) 80% 초과&#10;(빨간불) 80% 이하"
TOOLTIP_AVG = "(초록불) 3일 이하&#10;(노란불) 5일 이하&#10;(빨간불) 5일 초과"
rate_tooltip = TOOLTIP_RATE
avg_tooltip = TOOLTIP_AVG

def safe_cell(v):
    return html_lib.escape(str(v)) if v is not None and str(v) != "nan" else ""

def build_rate_cell(rate_val, rate_text):
    rate_str = safe_cell(rate_text) if rate_text not in (None, "") else "&nbsp;"
    if rate_val is None or pd.isna(rate_val):
        return rate_str
    try:
        v = float(rate_val)
        dot_class = "rate-red" if v <= 0.8 else ("rate-yellow" if v <= 0.9 else "rate-green")
    except Exception:
        return rate_str
    return f"<span class='rate-cell tt-follow' data-tooltip='{TOOLTIP_RATE}'><span class='rate-dot {dot_class}'></span>{rate_str}</span>"

def build_avg_days_cell(value_text):
    raw = str(value_text).replace(",", "").strip()
    if raw in ("", "-", "nan"):
        return f"<span class='avg-cell tt-follow' data-tooltip='{TOOLTIP_AVG}'>{safe_cell(value_text)}</span>"
    try:
        num_val = float(raw)
        dot_class = "rate-green" if num_val <= 3 else ("rate-yellow" if num_val <= 5 else "rate-red")
        return f"<span class='avg-cell tt-follow' data-tooltip='{TOOLTIP_AVG}'><span class='rate-dot {dot_class}'></span>{safe_cell(value_text)}</span>"
    except Exception:
        return f"<span class='avg-cell tt-follow' data-tooltip='{TOOLTIP_AVG}'>{safe_cell(value_text)}</span>"

def _th_sort(label, col_index):
    inner = label + f"<a class='sort-arrow' href='javascript:void(0)' role='button' data-col='{col_index}' title='정렬'>↕</a>"
    return f"<th class='th-sort col-small' data-col-index='{col_index}' data-order='desc'>{inner}</th>"

th_rate = f'<th class="th-sort col-emphasis" data-col-index="4" data-order="desc"><span class="rate-help tt-follow" data-tooltip="{rate_tooltip}">온라인등록율</span><br><span class="th-sub">온라인등록 스타일수 / 온라인상품 입고스타일</span><a class="sort-arrow" href="javascript:void(0)" role="button" data-col="4" title="정렬">↕</a></th>'
th_avg_total = f'<th class="th-sort col-emphasis"><span class="avg-help tt-follow" data-tooltip="{avg_tooltip}">전체 온라인등록 &#10;소요일</span></th>'
th_photo_handover = '<th class="th-sort col-small"><span class="avg-help" data-tooltip="최초입고 ~&#10; 포토팀수령 소요일">포토인계소요일</span></th>'
th_photo = '<th class="th-sort col-small"><span class="avg-help" data-tooltip="촬영샘플 수령 ~&#10;제품컷완성 소요일">포토 소요일</span></th>'
th_register = '<th class="th-sort col-small"><span class="avg-help" data-tooltip="제품컷 완성 ~&#10;온라인등록 소요일">상품등록소요일</span></th>'
th_online_in = '<th class="th-sort col-small" data-col-index="2" data-order="desc"><span class="avg-help tt-left" data-tooltip="일부 QR 등 온라인 미판매 스타일을 제외한 입고스타일수">온라인상품<br>입고스타일</span><a class="sort-arrow" href="javascript:void(0)" role="button" data-col="2" title="정렬">↕</a></th>'
header_monitor = "<tr><th class='col-small'>브랜드</th>" + _th_sort("물류입고<br>스타일수", 1) + th_online_in + _th_sort("온라인등록<br>스타일수", 3) + th_rate + th_photo_handover + th_photo + th_register + th_avg_total + "</tr>"

def _fmt(n):
    return f"{int(n):,}"


def _row_monitor(r):
    no_reg = r["브랜드"] in NO_REG_SHEET_BRANDS

    reg_sty_display = "-" if no_reg else _fmt(r["온라인등록스타일수"])
    rate_cell = safe_cell("-") if no_reg else build_rate_cell(
        r.get("온라인등록율"),
        r.get("_등록율")
    )

    avg_total = safe_cell("-") if no_reg else build_avg_days_cell(
        r.get("평균전체등록소요일수")
    )
    # 포토인계·포토·상품등록 소요일수 셀은 값만 표시 (초록불 툴팁/색점 없음)
    avg_photo_handover = safe_cell("-") if no_reg else safe_cell(r.get("포토인계소요일수"))
    avg_photo = safe_cell("-") if no_reg else safe_cell(r.get("포토 소요일수"))
    avg_register = safe_cell("-") if no_reg else safe_cell(r.get("상품등록소요일수"))

    return (
        f"<td class='col-small'>{safe_cell(r['브랜드'])}</td>"
        f"<td class='col-small'>{_fmt(r['물류입고스타일수'])}</td>"
        f"<td class='col-small'>{_fmt(r.get('온라인입고스타일수', 0))}</td>"
        f"<td class='col-small'>{reg_sty_display}</td>"
        f"<td class='col-emphasis'>{rate_cell}</td>"
        f"<td class='col-small'>{avg_photo_handover}</td>"
        f"<td class='col-small'>{avg_photo}</td>"
        f"<td class='col-small'>{avg_register}</td>"
        f"<td class='col-emphasis'>{avg_total}</td>"
    )


body_monitor = "".join(("<tr class='bu-row'>" if r["브랜드"] in bu_labels else "<tr>") + _row_monitor(r) + "</tr>" for _, r in monitor_df.iterrows())

MONITOR_TABLE_HTML = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#0f172a;color:#f1f5f9;font-family:inherit}}
.monitor-table{{width:100%;border-collapse:collapse;background:#1e293b;color:#f1f5f9}}
.monitor-table th,.monitor-table td{{border:none;padding:6px 8px;text-align:center;font-size:0.95rem}}
.monitor-table thead th{{background:#0f172a;color:#f1f5f9;font-weight:700}}
.monitor-table thead th.col-emphasis{{border:3px solid #fbbf24}}
.monitor-table tr.bu-row td{{background:#d9f7ee;color:#000;font-size:1.15rem;font-weight:700}}
.monitor-table th.th-sort{{white-space:nowrap;cursor:default}}
.monitor-table th.th-sort .sort-arrow{{color:#94a3b8;text-decoration:none;margin-left:4px;font-size:0.75rem;cursor:pointer}}
.monitor-table .rate-cell,.monitor-table .avg-cell{{display:inline-flex;align-items:center;gap:6px;justify-content:center}}
.monitor-table .rate-dot{{width:16px;height:16px;border-radius:50%;display:inline-block}}
.monitor-table .rate-red{{background:#ef4444}}.monitor-table .rate-yellow{{background:#f59e0b}}.monitor-table .rate-green{{background:#22c55e}}
.monitor-table .rate-help,.monitor-table .avg-help{{position:relative;display:inline-block;cursor:help}}
.monitor-table .rate-help::after,.monitor-table .avg-help::after,.monitor-table .rate-cell::after,.monitor-table .avg-cell::after{{content:"";position:absolute;opacity:0;pointer-events:none;left:50%;transform:translateX(-50%);bottom:calc(100%+6px);white-space:pre-line;width:max-content;max-width:360px;background:#ffffff;color:#1e293b;padding:8px 12px;border-radius:6px;font-size:0.85rem;box-shadow:0 4px 12px rgba(0,0,0,0.2);border:1px solid #e2e8f0;z-index:20}}
.monitor-table .rate-help:hover::after,.monitor-table .avg-help:hover::after,.monitor-table .rate-cell:hover::after,.monitor-table .avg-cell:hover::after{{content:attr(data-tooltip);opacity:1}}
.monitor-table thead th:hover{{z-index:10}}
.monitor-table .avg-help.tt-left::after{{left:0;transform:translateX(0);bottom:calc(100%+6px)}}
.monitor-table .tt-follow::after{{content:none!important;display:none!important}}
.monitor-table td.col-emphasis,.monitor-table th.col-emphasis{{font-size:1.045rem;color:#fbbf24}}
.monitor-table td.col-small,.monitor-table th.col-small{{font-size:0.855rem}}
.monitor-table .th-sub{{font-size:0.7rem;color:#f1f5f9;font-weight:normal;display:block;margin-top:2px}}
.monitor-table{{table-layout:fixed}}
.monitor-table th.col-small,.monitor-table td.col-small{{width:90px;min-width:90px;max-width:90px;box-sizing:border-box}}
.monitor-table th.col-emphasis,.monitor-table td.col-emphasis{{width:120px;min-width:120px;max-width:120px;box-sizing:border-box}}
.monitor-table thead th.col-emphasis{{border:3px solid #fbbf24}}
#tooltip-follow{{position:fixed;display:none;white-space:pre-line;width:max-content;max-width:360px;background:#ffffff;color:#1e293b;padding:8px 12px;border-radius:6px;font-size:0.85rem;box-shadow:0 4px 12px rgba(0,0,0,0.2);border:1px solid #e2e8f0;z-index:9999;pointer-events:none}}
html,body{{height:100%;margin:0;overflow:hidden}}
.table-wrap{{height:100%;max-height:100%;overflow-y:auto;overflow-x:auto;-webkit-overflow-scrolling:touch}}
.monitor-table thead th{{position:sticky;top:0;z-index:5;background:#0f172a}}
</style></head><body><div id="tooltip-follow"></div><div class="table-wrap"><table class="monitor-table" id="monitor-table-register"><thead>{header_monitor}</thead><tbody>{body_monitor}</tbody></table></div>
<script>(function(){{
var t=document.getElementById("monitor-table-register");if(!t)return;
function g(td){{var v=(td&&td.textContent||"").trim().replace(/[,%]/g,"");if(v===""||v==="-")return null;var n=parseFloat(v);return isNaN(n)?v:n}}
function sort(tbody,ci,ord){{
var rows=Array.prototype.slice.call(tbody.querySelectorAll("tr"));
rows.sort(function(a,b){{var va=g(a.cells[ci]),vb=g(b.cells[ci]);if(va===null)va=ord==="desc"?-Infinity:Infinity;if(vb===null)vb=ord==="desc"?-Infinity:Infinity;
if(typeof va==="number"&&typeof vb==="number")return ord==="desc"?vb-va:va-vb;var sa=String(va),sb=String(vb);if(sa<sb)return ord==="desc"?1:-1;if(sa>sb)return ord==="desc"?-1:1;return 0}});
rows.forEach(function(r){{tbody.appendChild(r)}});
}}
t.addEventListener("click",function(e){{var a=e.target.closest("a.sort-arrow");if(!a)return;e.preventDefault();var th=a.closest("th.th-sort");if(!th)return;
var ci=parseInt(th.getAttribute("data-col-index"),10),ord=th.getAttribute("data-order")==="desc"?"asc":"desc";th.setAttribute("data-order",ord);
t.querySelectorAll("thead th.th-sort").forEach(function(h){{var i=h.getAttribute("data-col-index"),x=h.querySelector("a.sort-arrow");if(!x)return;if(i===String(ci)){{h.setAttribute("data-order",ord);x.textContent=ord==="desc"?"▼":"▲"}}else{{h.setAttribute("data-order","desc");x.textContent="↕"}}}});
var tb=t.querySelector("tbody");if(tb)sort(tb,ci,ord);
}});
var tip=document.getElementById("tooltip-follow");var offset=12;
function showTip(e,text){{if(!text)return;tip.textContent=text.replace(/&#10;/g,"\\n");tip.style.display="block";tip.style.left=(e.clientX+offset)+"px";tip.style.top=(e.clientY+offset)+"px";}}
function moveTip(e){{tip.style.left=(e.clientX+offset)+"px";tip.style.top=(e.clientY+offset)+"px";}}
function hideTip(){{tip.style.display="none";}}
document.querySelectorAll(".tt-follow").forEach(function(el){{var text=el.getAttribute("data-tooltip");if(!text)return;el.addEventListener("mouseenter",function(e){{showTip(e,text);}});el.addEventListener("mousemove",moveTip);el.addEventListener("mouseleave",hideTip);}});
}})();</script></body></html>"""
try:
    import streamlit.components.v1 as components
    components.html(MONITOR_TABLE_HTML, height=600, scrolling=True)
except Exception:
    st.markdown(f"<div class='table-wrap monitor-table-wrap'><table class='monitor-table'><thead>{header_monitor}</thead><tbody>{body_monitor}</tbody></table></div>", unsafe_allow_html=True)

# 브랜드별 입출고 모니터링
TABLE_COLS = ["발주 STY수", "발주액", "입고 STY수", "입고액", "출고 STY수", "출고액", "판매 STY수", "판매액"]
def _fmt_table_num(v):
    return f"{int(round(float(v))):,}" if v is not None and pd.notna(v) else "0"
def _fmt_eok_table(v):
    try:
        return f"{float(v) / 1e8:,.0f} 억 원" if v is not None and pd.notna(v) else "0 억 원"
    except Exception:
        return "0 억 원"
def _get_season_rows(brand):
    df = brand_season_df[brand_season_df["브랜드"] == brand].sort_values("시즌")
    if df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        row = {"시즌": str(r["시즌"]).strip()}
        for c in TABLE_COLS:
            row[c] = _fmt_eok_table(r.get(c)) if "액" in c else _fmt_table_num(r.get(c))
        rows.append(row)
    return rows
def _build_inout_table_html(display_df):
    cols = ["브랜드"] + TABLE_COLS
    header_cells = "".join(f"<th>{html_lib.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for _, row in display_df.iterrows():
        brand_name = str(row.get("브랜드", "")).strip()
        brand_id = f"brand-{abs(hash(brand_name))}"
        brand_cell = f"<td class='brand-cell'><button type='button' class='brand-toggle' data-target='{brand_id}' aria-expanded='false'><span class='label'>{html_lib.escape(brand_name)}</span><span class='caret'>▽</span></button></td>"
        other_cells = "".join(f"<td>{html_lib.escape(str(row.get(c,'')))}</td>" for c in TABLE_COLS)
        body_rows.append(f"<tr class='brand-row'>{brand_cell}{other_cells}</tr>")
        for srow in _get_season_rows(brand_name):
            season_cells = f"<td>└ {html_lib.escape(str(srow['시즌']))}</td>" + "".join(f"<td>{html_lib.escape(str(srow.get(c,'')))}</td>" for c in TABLE_COLS)
            body_rows.append(f"<tr class='season-row {brand_id}' style='display:none'>{season_cells}</tr>")
    html = f"""<style>.brand-expand-table{{width:100%;border:1px solid #334155;border-radius:8px;overflow:hidden;background:#1e293b;color:#f1f5f9;margin-top:0.5rem}}.brand-expand-table table{{width:100%;border-collapse:collapse}}.brand-expand-table th,.brand-expand-table td{{border:1px solid #334155;padding:6px 8px;text-align:center;font-size:0.95rem}}.brand-expand-table thead th{{background:#0f172a;color:#f1f5f9;font-weight:700}}.brand-expand-table .brand-row{{background:#111827}}.brand-expand-table .brand-cell{{text-align:left}}.brand-expand-table .brand-toggle{{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-weight:700;color:#f1f5f9}}.brand-expand-table .brand-toggle .caret{{display:inline-block;transition:transform 0.15s;color:#94a3b8;font-size:0.9rem}}.brand-expand-table .brand-toggle[aria-expanded="true"] .caret{{transform:rotate(90deg)}}.brand-expand-table .season-row{{display:none}}.brand-expand-table .season-row td{{background:#0f172a;font-size:0.9rem;color:#cbd5e1}}.brand-expand-table .season-row td:first-child{{text-align:left;padding-left:18px}}</style><div class="brand-expand-table"><table><thead><tr>{header_cells}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div><script>document.addEventListener("click",function(e){{var btn=e.target.closest(".brand-toggle");if(!btn)return;var target=btn.dataset.target;var rows=document.querySelectorAll("tr."+target);var caret=btn.querySelector(".caret");var isOpen=btn.getAttribute("aria-expanded")==="true";rows.forEach(function(row){{row.style.display=isOpen?"none":"table-row"}});btn.setAttribute("aria-expanded",String(!isOpen));caret.textContent=isOpen?"▽":"△";}});</script>"""
    return html, len(body_rows)

st.markdown('<div style="height:40px;"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">(온/오프 전체) 입출고 현황</div>', unsafe_allow_html=True)
st.markdown('<div style="font-size:1.1rem;color:#cbd5e1;margin-bottom:0.5rem;">STY 기준 통계</div>', unsafe_allow_html=True)
display_df = pd.DataFrame(inout_rows)[["브랜드"] + TABLE_COLS]
st.markdown('<div style="font-size:0.8rem;color:#cbd5e1;margin-bottom:0.5rem;">브랜드명을 클릭하면 시즌별 수치를 보실 수 있습니다</div>', unsafe_allow_html=True)
try:
    import streamlit.components.v1 as components
    inout_html, row_count = _build_inout_table_html(display_df)
    components.html(inout_html, height=min(600, 120 + row_count * 28), scrolling=True)
except Exception:
    inout_html, _ = _build_inout_table_html(display_df)
    st.markdown(inout_html, unsafe_allow_html=True)
