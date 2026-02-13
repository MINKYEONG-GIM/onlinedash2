# -*- coding: utf-8 -*-
"""
브랜드별·시즌별 스타일 입고/출고/온라인등록 실시간 모니터링.
- 입출고: BASE 시트(전브랜드)
- 온라인등록: 각 브랜드별 스프레드시트
실행: streamlit run spao_style_dashboard.py
"""
from __future__ import annotations

import os
import html as html_lib
import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from google.oauth2.service_account import Credentials

# =====================================================
# 페이지 설정
# =====================================================
st.set_page_config(
    page_title="브랜드별 스타일 모니터링",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================
# Secrets / 시트 ID (deploy와 동일)
# =====================================================
def _secret(key, default=""):
    try:
        v = st.secrets.get(key, default) or default
        return str(v).strip() if v else default
    except Exception:
        return default

def _norm_sheet_id(val):
    return str(val).strip() if val else ""

_SPREADSHEET_SECRET_KEYS = [
    ("inout", "BASE_SPREADSHEET_ID"),
    ("spao", "SP_SPREADSHEET_ID"),
    ("whoau", "WH_SPREADSHEET_ID"),
    ("clavis", "CV_SPREADSHEET_ID"),
    ("mixxo", "MI_SPREADSHEET_ID"),
    ("roem", "RM_SPREADSHEET_ID"),
    ("shoopen", "HP_SPREADSHEET_ID"),
    ("eblin", "EB_SPREADSHEET_ID"),
]
GOOGLE_SPREADSHEET_IDS = {k: _norm_sheet_id(_secret(s)) for k, s in _SPREADSHEET_SECRET_KEYS}

# 브랜드·BU 그룹 (deploy와 동일)
brands_list = ["스파오", "뉴발란스", "뉴발란스키즈", "후아유", "슈펜", "미쏘", "로엠", "클라비스", "에블린"]
bu_groups = [
    ("캐쥬얼BU", ["스파오"]),
    ("스포츠BU", ["뉴발란스", "뉴발란스키즈", "후아유", "슈펜"]),
    ("여성BU", ["미쏘", "로엠", "클라비스", "에블린"]),
]
BRAND_TO_KEY = {
    "스파오": "spao", "후아유": "whoau", "클라비스": "clavis", "미쏘": "mixxo",
    "로엠": "roem", "슈펜": "shoopen", "에블린": "eblin",
}
# 상품등록 시트가 없는 브랜드 (온라인등록 스타일수/등록율/평균등록소요일수는 '-' 표시)
NO_REG_SHEET_BRANDS = {"뉴발란스", "뉴발란스키즈"}

# =====================================================
# Google 인증 / 시트 다운로드
# =====================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

def _get_google_credentials():
    import json
    try:
        raw = st.secrets.get("google_service_account") if hasattr(st.secrets, "get") else None
        if not raw:
            raw = _secret("google_service_account")
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

def _fetch_google_sheet_via_sheets_api(sid, creds):
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
                rng = f"'{title.replace(chr(39), chr(39)+chr(39))}'" if title else f"Sheet{idx+1}"
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
        downloader = MediaIoBaseDownload(fh, service.files().export_media(
            fileId=sheet_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ))
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.seek(0)
        return fh.read()
    except Exception:
        pass
    return _fetch_google_sheet_via_sheets_api(sheet_id, creds)

@st.cache_data(ttl=300)
def get_all_sources():
    return {k: (fetch_sheet_bytes(GOOGLE_SPREADSHEET_IDS.get(k)), k) for k in GOOGLE_SPREADSHEET_IDS}

# =====================================================
# 컬럼 탐지
# =====================================================
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

# =====================================================
# BASE 입출고 로드 (deploy와 유사)
# =====================================================
@st.cache_data(ttl=300)
def load_base_inout(io_bytes=None, _cache_key=None):
    if io_bytes is None or len(io_bytes) == 0:
        return pd.DataFrame()
    excel_file = pd.ExcelFile(BytesIO(io_bytes))
    sheet_candidates = [s for s in excel_file.sheet_names if not str(s).startswith("_")]
    sheet_name = sheet_candidates[0] if sheet_candidates else excel_file.sheet_names[-1]
    preview = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=None)
    header_keywords = ["브랜드", "스타일", "최초입고일", "입고", "출고", "판매"]
    best_row, best_score = None, 0
    for i in range(min(20, len(preview))):
        row = preview.iloc[i].astype(str)
        score = sum(any(k in cell for k in header_keywords) for cell in row)
        if score > best_score:
            best_score, best_row = score, i
    if best_row is not None and best_score > 0:
        df = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=best_row)
    else:
        df = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name)
    df.columns = [str(c).strip() for c in df.columns]
    style_col = find_col(["스타일코드", "스타일"], df=df)
    if style_col and style_col in df.columns:
        prefix = df[style_col].astype(str).str.strip().str.lower().str.slice(0, 2)
        df["브랜드"] = prefix.map({
            "sp": "스파오", "rm": "로엠", "mi": "미쏘", "wh": "후아유", "hp": "슈펜",
            "cv": "클라비스", "eb": "에블린", "nb": "뉴발란스", "nk": "뉴발란스키즈",
        })
    return df

# =====================================================
# BASE 스타일별 최초입고일 맵 (평균 등록 소요일 계산용, deploy와 동일)
# =====================================================
@st.cache_data(ttl=300)
def _base_style_to_first_in_map(io_bytes=None, _cache_key=None):
    """BASE 시트에서 스타일코드별 최초입고일(min) 맵. 반환: dict normalized_style -> datetime."""
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
        df.loc[excel_mask, "_first_in"] = pd.to_datetime(
            numeric[excel_mask], unit="d", origin="1899-12-30", errors="coerce"
        )
    df = df[df["_first_in"].notna() & (df["_style"].str.len() > 0)]
    if df.empty:
        return {}
    return df.groupby("_style")["_first_in"].min().to_dict()

def _norm_season_value(val):
    """시즌 값 정규화 (deploy와 동일)."""
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
    if len(s) >= 2 and s[0].isalpha():
        return s[1]
    return s[0]

# =====================================================
# 브랜드별 등록 시트 로드 (스타일코드, 시즌, 공홈등록일 → 온라인상품등록여부)
# =====================================================
def _normalize(v):
    return "".join(str(v).split()) if v is not None else ""

@st.cache_data(ttl=120)
def load_brand_register_df(io_bytes=None, _cache_key=None):
    if io_bytes is None or len(io_bytes) == 0:
        return pd.DataFrame()

    try:
        excel_file = pd.ExcelFile(BytesIO(io_bytes))
    except Exception:
        return pd.DataFrame()

    for sheet_name in excel_file.sheet_names:
        try:
            df_raw = pd.read_excel(BytesIO(io_bytes), sheet_name=sheet_name, header=None)
        except Exception:
            continue

        if df_raw is None or df_raw.empty:
            continue

        header_row_idx, header_vals = None, None

        for i in range(min(30, len(df_raw))):
            row = df_raw.iloc[i].tolist()
            norm = [_normalize(v) for v in row]
            if any("스타일코드" in v for v in norm) and any("공홈등록일" in v for v in norm):
                header_row_idx, header_vals = i, norm
                break

        if header_row_idx is None:
            continue

        def fi(key):
            for idx, v in enumerate(header_vals):
                if key in v:
                    return idx
            return None

        style_col = fi("스타일코드") or fi("스타일")
        season_col = fi("시즌") or fi("Season")
        regdate_col = fi("공홈등록일")

        if style_col is None or regdate_col is None:
            continue

        data = df_raw.iloc[header_row_idx + 1 :].copy()
        data.columns = range(data.shape[1])

        out = pd.DataFrame()
        out["스타일코드"] = data.iloc[:, style_col].astype(str).str.strip()
        out["시즌"] = (
            data.iloc[:, season_col].astype(str).str.strip()
            if season_col is not None and season_col < data.shape[1]
            else ""
        )

        # 핵심: 공홈등록일 기준으로 등록여부 생성
        reg_series = data.iloc[:, regdate_col]
        reg_ok = pd.to_datetime(reg_series, errors="coerce").notna()

        out["온라인상품등록여부"] = reg_ok.map({True: "등록", False: "미등록"})

        out = out[out["스타일코드"].str.len() > 0]
        out = out[out["스타일코드"] != "nan"]

        return out

    return pd.DataFrame()

# =====================================================
# 브랜드별 평균 등록 소요일 (공홈등록일 - 최초입고일, deploy와 동일)
# =====================================================
@st.cache_data(ttl=120)
def load_brand_register_avg_days(reg_bytes=None, inout_bytes=None, _cache_key=None, _inout_cache_key=None, selected_seasons_tuple=None):
    """등록 평균 소요일: 공홈등록일(브랜드 시트) - 최초입고일(BASE 시트). selected_seasons_tuple 있으면 시즌 필터."""
    if not reg_bytes or len(reg_bytes) == 0:
        return None
    base_map = _base_style_to_first_in_map(inout_bytes, _inout_cache_key or "inout") if inout_bytes else {}
    if not base_map:
        return None
    try:
        excel_file = pd.ExcelFile(BytesIO(reg_bytes))
    except Exception:
        return None

    def fi(header_vals, key):
        for idx, v in enumerate(header_vals):
            if key in _normalize(v):
                return idx
        return None

    for sheet_name in excel_file.sheet_names:
        try:
            df_raw = pd.read_excel(BytesIO(reg_bytes), sheet_name=sheet_name, header=None)
        except Exception:
            continue
        if df_raw is None or df_raw.empty:
            continue
        header_row_idx, header_vals = None, None
        for i in range(min(30, len(df_raw))):
            row = df_raw.iloc[i].tolist()
            norm = [_normalize(v) for v in row]
            if any("스타일코드" in v for v in norm) and any("공홈등록일" in v for v in norm):
                header_row_idx, header_vals = i, norm
                break
        if header_row_idx is None:
            continue
        style_col = fi(header_vals, "스타일코드") or fi(header_vals, "스타일")
        regdate_col = fi(header_vals, "공홈등록일")
        season_col = fi(header_vals, "시즌")
        if style_col is None or regdate_col is None:
            continue

        data = df_raw.iloc[header_row_idx + 1 :].copy()
        data.columns = range(data.shape[1])
        if selected_seasons_tuple and season_col is not None and season_col < data.shape[1]:
            season_series = data.iloc[:, season_col].astype(str)
            norm_season = season_series.map(_norm_season_value)
            norm_sel = [_norm_season_value(s) for s in selected_seasons_tuple]
            norm_sel = [s for s in norm_sel if s]
            mask_filter = norm_season.isin(norm_sel) if norm_sel else pd.Series(True, index=data.index)
            raw = season_series.str.strip().str.upper()
            mask_strict = pd.Series(False, index=data.index)
            for s in norm_sel:
                mask_strict = mask_strict | raw.str.match(f"^G?{s}$", na=False)
            mask = mask_filter & mask_strict if norm_sel else pd.Series(True, index=data.index)
            data = data.loc[mask]
        if data.empty:
            continue

        reg_series = data.iloc[:, regdate_col]
        style_series = data.iloc[:, style_col]

        def clean_date_series(series):
            s = series.replace(0, pd.NA).replace("0", pd.NA)
            numeric = pd.to_numeric(s, errors="coerce")
            excel_mask = numeric.between(1, 60000, inclusive="both")
            result = pd.to_datetime(s, errors="coerce")
            if excel_mask.any():
                result = result.copy()
                result.loc[excel_mask] = pd.to_datetime(numeric[excel_mask], unit="d", origin="1899-12-30", errors="coerce")
            return result

        reg_dt = clean_date_series(reg_series)
        style_ok = style_series.astype(str).str.strip().replace(r"^\s*$", pd.NA, regex=True).notna()
        register_ok = reg_dt.notna()
        diffs = []
        for idx in data.index:
            if not (style_ok.loc[idx] and register_ok.loc[idx]):
                continue
            style_norm = "".join(str(style_series.loc[idx]).split())
            base_dt = base_map.get(style_norm)
            if base_dt is None or pd.isna(reg_dt.loc[idx]):
                continue
            days = (reg_dt.loc[idx] - base_dt).days
            # 온라인상품등록일 - 최초입고일이 음수면 해당 스타일은 0일로 처리
            diffs.append(max(0, days))
        return float(sum(diffs)) / len(diffs) if diffs else None
    return None

# =====================================================
# 전체 스타일 테이블 (BASE + 각 브랜드 시트 병합)
# =====================================================
def build_style_table_all(sources):
    base_bytes = sources.get("inout", (None, None))[0]
    df_base = load_base_inout(base_bytes, _cache_key="inout")
    if df_base.empty:
        return pd.DataFrame()
    style_col = find_col(["스타일코드", "스타일"], df=df_base)
    brand_col = "브랜드" if "브랜드" in df_base.columns else None
    season_col = find_col(["시즌", "season"], df=df_base)
    first_in_col = find_col(["최초입고일", "입고일"], df=df_base)
    out_amt_col = find_col(["출고액"], df=df_base)
    if not style_col or not brand_col:
        return pd.DataFrame()
    df_base = df_base[df_base[style_col].astype(str).str.strip().str.len() > 0].copy()
    df_base["_style"] = df_base[style_col].astype(str).str.strip()
    df_base["_brand"] = df_base[brand_col].astype(str).str.strip()
    df_base["_season"] = df_base[season_col].astype(str).str.strip() if season_col and season_col in df_base.columns else ""
    first_vals = df_base[first_in_col] if first_in_col and first_in_col in df_base.columns else pd.Series(dtype=object)
    df_base["_입고"] = pd.to_datetime(first_vals, errors="coerce").notna()
    if first_in_col and first_in_col in df_base.columns:
        num = pd.to_numeric(df_base[first_in_col], errors="coerce")
        df_base.loc[num.between(1, 60000, inclusive="both"), "_입고"] = True
    out_vals = df_base[out_amt_col] if out_amt_col and out_amt_col in df_base.columns else pd.Series(0, index=df_base.index)
    df_base["_출고"] = pd.to_numeric(out_vals, errors="coerce").fillna(0) > 0
    base_agg = df_base.groupby(["_brand", "_style"]).agg(
        _season=("_season", lambda s: s.dropna().astype(str).str.strip().iloc[0] if len(s.dropna()) else ""),
        입고여부=("_입고", "any"),
        출고여부=("_출고", "any"),
    ).reset_index()
    base_agg = base_agg.rename(columns={"_brand": "브랜드", "_style": "스타일코드", "_season": "시즌"})
    rows = []
    all_brands = base_agg["브랜드"].dropna().unique().tolist()
    for brand_name in all_brands:
        brand_key = BRAND_TO_KEY.get(brand_name)
        b_agg = base_agg[base_agg["브랜드"] == brand_name]
        if b_agg.empty:
            continue
        if brand_key is None:
            for _, r in b_agg.iterrows():
                rows.append({
                    "브랜드": brand_name,
                    "스타일코드": r["스타일코드"],
                    "시즌": r["시즌"],
                    "입고 여부": "Y" if r["입고여부"] else "N",
                    "출고 여부": "Y" if r["출고여부"] else "N",
                    "온라인상품등록여부": "미등록",
                })
            continue
        reg_bytes = sources.get(brand_key, (None, None))[0]
        df_reg = load_brand_register_df(reg_bytes, _cache_key=brand_key)
        if df_reg.empty:
            for _, r in b_agg.iterrows():
                rows.append({
                    "브랜드": brand_name,
                    "스타일코드": r["스타일코드"],
                    "시즌": r["시즌"],
                    "입고 여부": "Y" if r["입고여부"] else "N",
                    "출고 여부": "Y" if r["출고여부"] else "N",
                    "온라인상품등록여부": "미등록",
                })
            continue
        df_reg["스타일코드_norm"] = df_reg["스타일코드"].str.strip()
        merged = b_agg.merge(
            df_reg[["스타일코드_norm", "온라인상품등록여부"]],
            left_on="스타일코드",
            right_on="스타일코드_norm",
            how="left",
        )
        for _, r in merged.iterrows():
            reg = r.get("온라인상품등록여부", "미등록")
            if pd.isna(reg) or str(reg).strip() == "":
                reg = "미등록"

            rows.append({
                "브랜드": brand_name,
                "스타일코드": r["스타일코드"],
                "시즌": r["시즌"],
                "입고 여부": "Y" if r["입고여부"] else "N",
                "출고 여부": "Y" if r["출고여부"] else "N",
                "온라인상품등록여부": reg,
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)

# =====================================================
# 브랜드별 입출고 집계 (발주/입고/출고/판매 STY·액)
# =====================================================
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
    if not style_col or not brand_col:
        return [], {}, pd.DataFrame()
    season_col = find_col(["시즌", "season"], df=df)
    df["_style"] = df[style_col].astype(str).str.strip()
    df["_brand"] = df[brand_col].astype(str).str.strip()
    df["_season"] = df[season_col].astype(str).str.strip() if season_col and season_col in df.columns else ""
    in_ok = pd.Series(False, index=df.index)
    if first_in_col:
        in_ok = pd.to_datetime(df[first_in_col], errors="coerce").notna()
        num = pd.to_numeric(df[first_in_col], errors="coerce")
        in_ok = in_ok | num.between(1, 60000, inclusive="both")
    df["_in"] = in_ok
    df["_out"] = pd.to_numeric(df[out_amt_col], errors="coerce").fillna(0) > 0 if out_amt_col else False
    df["_sale"] = pd.to_numeric(df[sale_amt_col], errors="coerce").fillna(0) > 0 if sale_amt_col else False
    def cnt_unique(g, col="_style"):
        return g[col].nunique()
    def sum_amt(g, c):
        return pd.to_numeric(g[c], errors="coerce").fillna(0).sum() if c and c in g.columns else 0
    order_g = df.groupby("_brand") if order_qty_col else None
    in_g = df[df["_in"]].groupby("_brand")
    out_g = df[df["_out"]].groupby("_brand")
    sale_g = df[df["_sale"]].groupby("_brand") if sale_amt_col else df.groupby("_brand")
    brands = df["_brand"].dropna().unique().tolist()
    brand_order_qty = order_g["_style"].nunique().to_dict() if order_g is not None else {}
    brand_order_amt = df.groupby("_brand").apply(lambda g: sum_amt(g, order_amt_col)).to_dict() if order_amt_col else {}
    brand_in_qty = in_g["_style"].nunique().to_dict()
    brand_in_amt = df[df["_in"]].groupby("_brand").apply(lambda g: sum_amt(g, in_amt_col)).to_dict() if in_amt_col else {}
    brand_out_qty = out_g["_style"].nunique().to_dict()
    brand_out_amt = df[df["_out"]].groupby("_brand").apply(lambda g: sum_amt(g, out_amt_col)).to_dict() if out_amt_col else {}
    brand_sale_qty = sale_g["_style"].nunique().to_dict()
    brand_sale_amt = df.groupby("_brand").apply(lambda g: sum_amt(g, sale_amt_col)).to_dict() if sale_amt_col else {}
    def fmt_num(v):
        return f"{int(v):,}" if pd.notna(v) and v != "" else "0"
    def fmt_eok(v):
        try:
            return f"{float(v) / 1e8:,.0f} 억 원"
        except Exception:
            return "0 억 원"
    rows = []
    for _, bu_brands in bu_groups:
        for b in bu_brands:
            rows.append({
                "브랜드": b,
                "발주 STY수": fmt_num(brand_order_qty.get(b, 0)),
                "발주액": fmt_eok(brand_order_amt.get(b, 0)),
                "입고 STY수": fmt_num(brand_in_qty.get(b, 0)),
                "입고액": fmt_eok(brand_in_amt.get(b, 0)),
                "출고 STY수": fmt_num(brand_out_qty.get(b, 0)),
                "출고액": fmt_eok(brand_out_amt.get(b, 0)),
                "판매 STY수": fmt_num(brand_sale_qty.get(b, 0)),
                "판매액": fmt_eok(brand_sale_amt.get(b, 0)),
            })
    # 브랜드·시즌 집계 (expander용)
    g = df.groupby(["_brand", "_season"])
    bs_parts = []
    for (b, s), grp in g:
        in_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_in"]]
        out_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_out"]]
        sale_grp = df[(df["_brand"] == b) & (df["_season"] == s) & df["_sale"]]
        bs_parts.append({
            "브랜드": b, "시즌": s,
            "발주 STY수": grp["_style"].nunique(),
            "발주액": sum_amt(grp, order_amt_col) if order_amt_col else 0,
            "입고 STY수": in_grp["_style"].nunique(),
            "입고액": sum_amt(in_grp, in_amt_col) if in_amt_col else 0,
            "출고 STY수": out_grp["_style"].nunique(),
            "출고액": sum_amt(out_grp, out_amt_col) if out_amt_col else 0,
            "판매 STY수": sale_grp["_style"].nunique(),
            "판매액": sum_amt(grp, sale_amt_col) if sale_amt_col else 0,
        })
    brand_season_df = pd.DataFrame(bs_parts)
    return rows, {"brand_in_qty": brand_in_qty, "brand_out_qty": brand_out_qty, "brand_sale_qty": brand_sale_qty}, brand_season_df

# =====================================================
# 다크 테마 CSS (deploy와 동일)
# =====================================================
DARK_CSS = """
<style>
    .stApp { background: #0f172a; }
    .block-container { background: #0f172a; padding-top: 2.5rem; padding-bottom: 2rem; }
    .fashion-title {
        display: inline-block;
        background: #14b8a6;
        color: #0f172a;
        padding: 0.65rem 1.2rem 0.5rem 1.2rem;
        border-radius: 8px 8px 0 0;
        font-weight: 700;
        font-size: 1.25rem;
        margin-bottom: 0;
        margin-top: 0.5rem;
    }
    .update-time { font-size: 0.85rem; color: #94a3b8; margin-top: 0.25rem; }
    .section-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #f1f5f9;
        margin: 1rem 0 0.5rem 0;
    }
    .kpi-card-dark {
        background: #1e293b;
        color: #f1f5f9;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        text-align: center;
        font-weight: 600;
        min-height: 100px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        border: 1px solid #334155;
    }
    .kpi-card-dark .label { font-size: 1.1rem; margin-bottom: 0.3rem; color: #cbd5e1; }
    .kpi-card-dark .value { font-size: 1rem; font-weight: 700; color: #f1f5f9; }
    .monitor-table {
        width: 100%;
        border-collapse: collapse;
        background: #1e293b;
        color: #f1f5f9;
        border: 1px solid #334155;
    }
    .monitor-table th, .monitor-table td {
        border: 1px solid #334155;
        padding: 6px 8px;
        text-align: center;
        font-size: 0.95rem;
    }
    .monitor-table thead th {
        background: #0f172a;
        color: #f1f5f9;
        font-weight: 700;
    }
    .monitor-table .group-head { background: #111827; color: #f1f5f9; font-size: 1rem; }
    .monitor-table tr.bu-row td {
        background-color: #d9f7ee;
        color: #000000;
        font-size: 1.15rem;
        font-weight: 700;
    }
    .monitor-table .rate-help, .monitor-table .avg-help, .monitor-table .sum-help {
        position: relative;
        display: inline-block;
        cursor: help;
    }
    .monitor-table .rate-help::after, .monitor-table .avg-help::after, .monitor-table .sum-help::after {
        content: "";
        position: absolute;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease-in-out;
        left: 50%;
        transform: translateX(-50%);
        bottom: calc(100% + 6px);
        white-space: pre;
        word-break: keep-all;
        width: max-content;
        max-width: 280px;
        background: #111827;
        color: #f1f5f9;
        padding: 6px 8px;
        border-radius: 6px;
        font-size: 0.85rem;
        text-align: left;
        box-shadow: 0 4px 12px rgba(0,0,0,0.35);
        z-index: 20;
    }
    .monitor-table .rate-help:hover::after { content: attr(data-tooltip); opacity: 1; }
    .monitor-table .avg-help:hover::after { content: attr(data-tooltip); opacity: 1; }
    .monitor-table .sum-help:hover::after { content: attr(data-tooltip); opacity: 1; }
    .monitor-table th.th-sort { white-space: nowrap; cursor: default; }
    .monitor-table th.th-sort .sort-arrow { color: #94a3b8; text-decoration: none; margin-left: 4px; font-size: 0.75rem; cursor: pointer; }
    .monitor-table th.th-sort .sort-arrow:hover { color: #f1f5f9; }
    .monitor-table .rate-cell, .monitor-table .avg-cell {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        justify-content: center;
        position: relative;
        cursor: help;
    }
    .monitor-table .rate-dot {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        display: inline-block;
    }
    .monitor-table .rate-red { background: #ef4444; }
    .monitor-table .rate-yellow { background: #f59e0b; }
    .monitor-table .rate-green { background: #22c55e; }
    .monitor-table .rate-cell::after, .monitor-table .avg-cell::after {
        content: "";
        position: absolute;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.15s ease-in-out;
        left: 50%;
        transform: translateX(-50%);
        bottom: calc(100% + 6px);
        white-space: pre;
        word-break: keep-all;
        width: max-content;
        max-width: 280px;
        background: #111827;
        color: #f1f5f9;
        padding: 6px 8px;
        border-radius: 6px;
        font-size: 0.85rem;
        text-align: left;
        box-shadow: 0 4px 12px rgba(0,0,0,0.35);
        z-index: 20;
    }
    .monitor-table .rate-cell:hover::after, .monitor-table .avg-cell:hover::after {
        content: attr(data-tooltip);
        opacity: 1;
    }
    .inout-table {
        width: 100%;
        border-collapse: collapse;
        background: #1e293b;
        color: #f1f5f9;
        border: 1px solid #334155;
        border-radius: 8px;
        overflow: hidden;
    }
    .inout-table th, .inout-table td {
        border: 1px solid #334155;
        padding: 6px 8px;
        text-align: center;
        font-size: 0.95rem;
    }
    .inout-table thead th { background: #0f172a; color: #f1f5f9; font-weight: 700; }
    .inout-table tr.bu-row td {
        background-color: #d9f7ee;
        color: #000000;
        font-size: 1.15rem;
        font-weight: 700;
    }
    .inout-table .brand-cell { text-align: left; }
    [data-testid='stSelectbox'] label, [data-testid='stMultiSelect'] label { color: #f1f5f9 !important; }
</style>
"""

# =====================================================
# UI
# =====================================================
update_time = datetime.now()
sources = get_all_sources()
base_bytes = sources.get("inout", (None, None))[0]
df_style_all = build_style_table_all(sources)

st.markdown(DARK_CSS, unsafe_allow_html=True)

# 상단: 타이틀 + 업데이트 시각
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
        selected_seasons = st.multiselect("시즌", seasons, default=["2"], key="season_filter")
    with col_brand:
        brand_options = ["브랜드 전체"] + brands_list
        selected_brand = st.selectbox("브랜드", brand_options, key="brand_filter", index=0)

def _season_matches(season_series, selected_list):
    """시즌(Now)이 '2', '2!', '2#', '2!#' 등일 때 '2' 선택 시 모두 포함"""
    if not selected_list:
        return pd.Series(True, index=season_series.index)
    s = season_series.astype(str).str.strip()
    mask = pd.Series(False, index=season_series.index)
    for sel in selected_list:
        sel = str(sel).strip()
        mask = mask | (s == sel) | (s.str.startswith(sel) & (s.str.len() == len(sel) | ~s.str.slice(len(sel), len(sel) + 1).str.isalnum().fillna(True)))
    return mask

# 필터 적용
df_style = df_style_all.copy()
if selected_seasons and set(selected_seasons) != set(seasons):
    df_style = df_style[_season_matches(df_style["시즌"], selected_seasons)]
if selected_brand and selected_brand != "브랜드 전체":
    df_style = df_style[df_style["브랜드"] == selected_brand]

# KPI 카드 (BASE 기준 집계, 필터 선택 브랜드 반영)
inout_rows, inout_agg, brand_season_df = build_inout_aggregates(base_bytes)
df_base = load_base_inout(base_bytes, _cache_key="base")

# 브랜드 필터 적용: 특정 브랜드 선택 시 해당 브랜드만 KPI에 반영
brand_col_base = "브랜드" if "브랜드" in df_base.columns else None
if selected_brand and selected_brand != "브랜드 전체" and brand_col_base:
    df_base = df_base[df_base[brand_col_base].astype(str).str.strip() == selected_brand].copy()

# KPI용: 시즌 필터 적용 (선택 시즌만 반영)
df_kpi = df_base.copy()
season_col = find_col(["시즌", "season"], df=df_base)
if selected_seasons and set(selected_seasons) != set(seasons) and season_col and season_col in df_base.columns:
    df_kpi = df_base[_season_matches(df_base[season_col], selected_seasons)].copy()

in_amt_col = find_col(["누적입고액", "입고액"], df=df_base)
out_amt_col = find_col(["출고액"], df=df_base)
sale_amt_col = find_col(["누적 판매액[외형매출]", "누적판매액", "판매액"], df=df_base)
first_in_col = find_col(["최초입고일", "입고일"], df=df_base)
style_col = find_col(["스타일코드", "스타일"], df=df_base)

total_in_amt = pd.to_numeric(df_kpi[in_amt_col], errors="coerce").sum() if in_amt_col and in_amt_col in df_kpi.columns else 0
total_out_amt = pd.to_numeric(df_kpi[out_amt_col], errors="coerce").sum() if out_amt_col and out_amt_col in df_kpi.columns else 0
total_sale_amt = pd.to_numeric(df_kpi[sale_amt_col], errors="coerce").sum() if sale_amt_col and sale_amt_col in df_kpi.columns else 0

# STY 수: 시즌 필터된 df_kpi 기준 입고/출고/판매 여부로 집계
if not df_kpi.empty and style_col and style_col in df_kpi.columns:
    df_kpi = df_kpi.copy()
    df_kpi["_style"] = df_kpi[style_col].astype(str).str.strip()
    in_ok = pd.Series(False, index=df_kpi.index)
    if first_in_col and first_in_col in df_kpi.columns:
        in_ok = pd.to_datetime(df_kpi[first_in_col], errors="coerce").notna()
        num = pd.to_numeric(df_kpi[first_in_col], errors="coerce")
        in_ok = in_ok | num.between(1, 60000, inclusive="both")
    df_kpi["_in"] = in_ok
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
with k1:
    st.markdown(
        f'<div class="kpi-card-dark"><span class="label">입고</span>'
        f'<span class="value">{_eok(total_in_amt)} 억원 / {int(total_in_sty):,}STY</span></div>',
        unsafe_allow_html=True
    )
with k2:
    st.markdown(
        f'<div class="kpi-card-dark"><span class="label">출고</span>'
        f'<span class="value">{_eok(total_out_amt)} 억원 / {int(total_out_sty):,}STY</span></div>',
        unsafe_allow_html=True
    )
with k3:
    st.markdown(
        f'<div class="kpi-card-dark"><span class="label">전체 판매</span>'
        f'<span class="value">{_eok(total_sale_amt)} 억원 / {int(total_sale_sty):,}STY</span></div>',
        unsafe_allow_html=True
    )

# 브랜드별 상품등록 모니터링
st.markdown("<div style='margin-top:80px;'></div>", unsafe_allow_html=True)
st.markdown("---")
st.markdown('<div class="section-title">브랜드별 상품등록 모니터링</div>', unsafe_allow_html=True)

# 표: 브랜드는 항상 전체, 수치는 시즌 필터만 반영
all_brands = sorted(df_style_all["브랜드"].unique())
df_for_table = df_style_all.copy()
if selected_seasons and set(selected_seasons) != set(seasons):
    df_for_table = df_for_table[_season_matches(df_for_table["시즌"], selected_seasons)]
df_style_unique = df_for_table.drop_duplicates(subset=["브랜드", "시즌", "스타일코드"])
# 입고된 스타일만(최초입고일 있음) → 그 중 온라인 등록된 스타일만 카운트
df_in = df_style_unique[df_style_unique["입고 여부"] == "Y"]
in_count_all = df_in.groupby("브랜드")["스타일코드"].nunique()
reg_count_all = df_in[df_in["온라인상품등록여부"] == "등록"].groupby("브랜드")["스타일코드"].nunique()
table_df = pd.DataFrame({"브랜드": all_brands})
table_df["입고스타일수"] = table_df["브랜드"].map(in_count_all).fillna(0).astype(int)
table_df["온라인등록스타일수"] = table_df["브랜드"].map(reg_count_all).fillna(0).astype(int)
table_df["온라인등록율"] = (table_df["온라인등록스타일수"] / table_df["입고스타일수"].replace(0, 1)).round(2)
table_df["전체 미등록스타일"] = table_df["입고스타일수"] - table_df["온라인등록스타일수"]
table_df["등록수"] = table_df["온라인등록스타일수"]
table_df["평균 등록 소요일수"] = "-"
table_df["미분배(분배팀)"] = "-"
# 평균 등록 소요일수: 공홈등록일 - 최초입고일 (deploy와 동일)
base_bytes = sources.get("inout", (None, None))[0]
_season_tuple = tuple(selected_seasons) if selected_seasons else None
for brand_name in table_df["브랜드"].unique():
    if brand_name in NO_REG_SHEET_BRANDS:
        continue
    brand_key = BRAND_TO_KEY.get(brand_name)
    if not brand_key:
        continue
    reg_bytes = sources.get(brand_key, (None, None))[0]
    if not reg_bytes:
        continue
    avg_days = load_brand_register_avg_days(
        reg_bytes, base_bytes,
        _cache_key=brand_key, _inout_cache_key="inout",
        selected_seasons_tuple=_season_tuple,
    )
    if avg_days is not None:
        table_df.loc[table_df["브랜드"] == brand_name, "평균 등록 소요일수"] = f"{avg_days:.1f}"
# 상품등록 시트 없는 브랜드: 등록 관련 수치는 표시용 '-' (정렬 시 하단으로)
for b in NO_REG_SHEET_BRANDS:
    if b in table_df["브랜드"].values:
        table_df.loc[table_df["브랜드"] == b, "온라인등록스타일수"] = -1
        table_df.loc[table_df["브랜드"] == b, "온라인등록율"] = -1.0
bu_labels = {label for label, _ in bu_groups}
monitor_df = table_df.copy()
monitor_df["_등록율"] = monitor_df.apply(
    lambda r: "-" if r["브랜드"] in NO_REG_SHEET_BRANDS else (int(r["온라인등록율"] * 100) if r["온라인등록율"] >= 0 else 0).__str__() + "%",
    axis=1,
)
monitor_df["_미등록"] = monitor_df["전체 미등록스타일"].astype(int)

# 초기 정렬만 적용 (이후 정렬은 클라이언트에서 화살표 클릭 시 JS로 처리, 새로고침 없음)
monitor_df = monitor_df.sort_values("입고스타일수", ascending=False).reset_index(drop=True)

def safe_cell(v):
    s = html_lib.escape(str(v)) if v is not None and str(v) != "nan" else ""
    return s

def build_rate_cell(rate_val, rate_text):
    """등록율 셀: 빨/노/초 동그라미 + 호버 시 툴팁"""
    rate_str = safe_cell(rate_text) if rate_text not in (None, "") else "&nbsp;"
    if rate_val is None or pd.isna(rate_val):
        return rate_str
    try:
        v = float(rate_val)
        if v <= 0.8:
            dot_class = "rate-red"
        elif v <= 0.9:
            dot_class = "rate-yellow"
        else:
            dot_class = "rate-green"
    except Exception:
        return rate_str
    tooltip = "(초록불) 90% 초과&#10;(노란불) 80% 초과&#10;(빨간불) 80% 이하"
    return f"<span class='rate-cell' data-tooltip='{tooltip}'><span class='rate-dot {dot_class}'></span>{rate_str}</span>"

def build_avg_days_cell(value_text):
    """평균 등록 소요일수 셀: 빨/노/초 동그라미 + 호버 시 툴팁"""
    tooltip = "(초록불) 3일 이하&#10;(노란불) 5일 이하&#10;(빨간불) 5일 초과"
    dot_class = ""
    try:
        raw = str(value_text).replace(",", "").strip()
        if raw in ("", "-", "nan"):
            return f"<span class='avg-cell' data-tooltip='{tooltip}'>{safe_cell(value_text)}</span>"
        num_val = float(raw)
        if num_val <= 3:
            dot_class = "rate-green"
        elif num_val <= 5:
            dot_class = "rate-yellow"
        else:
            dot_class = "rate-red"
    except Exception:
        return f"<span class='avg-cell' data-tooltip='{tooltip}'>{safe_cell(value_text)}</span>"
    dot_html = f"<span class='rate-dot {dot_class}'></span>"
    return f"<span class='avg-cell' data-tooltip='{tooltip}'>{dot_html}{safe_cell(value_text)}</span>"

rate_tip = "(초록불) 90% 초과&#10;(노란불) 80% 초과&#10;(빨간불) 80% 이하"
avg_tip = "(초록불) 3일 이하&#10;(노란불) 5일 이하&#10;(빨간불) 5일 초과"
# 호버 시 툴팁 노출용 (iframe에서 CSS 툴팁이 동작하지 않아 title 사용)
rate_tip_title = "(초록불) 90% 초과\n(노란불) 80% 초과\n(빨간불) 80% 이하"
avg_tip_title = "(초록불) 3일 이하\n(노란불) 5일 이하\n(빨간불) 5일 초과"

def _th_sort(label, col_index):
    """col_index: 1=입고스타일수, 2=온라인등록스타일수, 3=온라인등록율. 클릭 시 JS에서 정렬(새로고침 없음)."""
    inner = label + f"<a class='sort-arrow' href='javascript:void(0)' role='button' data-col='{col_index}' title='정렬'>↕</a>"
    return f"<th class='th-sort' data-col-index='{col_index}' data-order='desc'>{inner}</th>"

_th_rate = (
    "<th class='th-sort' data-col-index='3' data-order='desc'>"
    "<span class='rate-help' title='" + html_lib.escape(rate_tip_title, quote=True).replace("\n", "&#10;") + "'>온라인<br>등록율</span>"
    + "<a class='sort-arrow' href='javascript:void(0)' role='button' data-col='3' title='정렬'>↕</a>"
    + "</th>"
)
header_monitor = (
    "<tr>"
    "<th>브랜드</th>"
    + _th_sort("입고스타일수", 1)
    + _th_sort("온라인등록<br>스타일수", 2)
    + _th_rate
    + f"<th><span class='avg-help' title='{html_lib.escape(avg_tip_title, quote=True).replace(chr(10), '&#10;')}'>평균 등록 소요일수<br><span style='font-size:0.8rem;font-weight:500;color:#94a3b8;'>온라인상품등록일 - 최초입고일</span></span></th>"
    "</tr>"
)
def _fmt(n):
    return f"{int(n):,}"
def _row_monitor(r):
    no_reg = r["브랜드"] in NO_REG_SHEET_BRANDS
    reg_sty_display = "-" if no_reg else _fmt(r["온라인등록스타일수"])
    rate_cell = safe_cell("-") if no_reg else build_rate_cell(r.get("온라인등록율"), r.get("_등록율"))
    avg_cell = safe_cell("-") if no_reg else build_avg_days_cell(r.get("평균 등록 소요일수"))
    return (
        f"<td>{safe_cell(r['브랜드'])}</td>"
        f"<td>{safe_cell(_fmt(r['입고스타일수']))}</td>"
        f"<td>{safe_cell(reg_sty_display)}</td>"
        f"<td>{rate_cell}</td>"
        f"<td>{avg_cell}</td>"
    )
body_monitor = "".join(
    ("<tr class='bu-row'>" if r["브랜드"] in bu_labels else "<tr>") + _row_monitor(r) + "</tr>"
    for _, r in monitor_df.iterrows()
)
# 테이블 + 클라이언트 정렬 스크립트 (새로고침/새 창 없이 JS로만 정렬)
_monitor_table_html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body {{ margin:0; background:#0f172a; color:#f1f5f9; font-family:inherit; }}
.monitor-table {{ width:100%; border-collapse:collapse; background:#1e293b; color:#f1f5f9; border:1px solid #334155; }}
.monitor-table th, .monitor-table td {{ border:1px solid #334155; padding:6px 8px; text-align:center; font-size:0.95rem; }}
.monitor-table thead th {{ background:#0f172a; color:#f1f5f9; font-weight:700; }}
.monitor-table tr.bu-row td {{ background-color:#d9f7ee; color:#000; font-size:1.15rem; font-weight:700; }}
.monitor-table th.th-sort {{ white-space:nowrap; cursor:default; }}
.monitor-table th.th-sort .sort-arrow {{ color:#94a3b8; text-decoration:none; margin-left:4px; font-size:0.75rem; cursor:pointer; }}
.monitor-table th.th-sort .sort-arrow:hover {{ color:#f1f5f9; }}
.monitor-table .rate-cell, .monitor-table .avg-cell {{ display:inline-flex; align-items:center; gap:6px; justify-content:center; }}
.monitor-table .rate-dot {{ width:16px; height:16px; border-radius:50%; display:inline-block; }}
.monitor-table .rate-red {{ background:#ef4444; }} .monitor-table .rate-yellow {{ background:#f59e0b; }} .monitor-table .rate-green {{ background:#22c55e; }}
.monitor-table .rate-help, .monitor-table .avg-help {{ position:relative; display:inline-block; cursor:help; }}
.monitor-table .rate-help::after, .monitor-table .avg-help::after {{ content:""; position:absolute; opacity:0; pointer-events:none; transition:opacity 0.15s ease-in-out; left:50%; transform:translateX(-50%); bottom:calc(100% + 6px); white-space:pre-line; word-break:keep-all; width:max-content; max-width:280px; background:#111827; color:#f1f5f9; padding:6px 8px; border-radius:6px; font-size:0.85rem; text-align:left; box-shadow:0 4px 12px rgba(0,0,0,0.35); z-index:20; }}
.monitor-table .rate-help:hover::after {{ content:attr(data-tooltip); opacity:1; }}
.monitor-table .avg-help:hover::after {{ content:attr(data-tooltip); opacity:1; }}
</style></head><body>
<table class="monitor-table" id="monitor-table-register">
<thead>{header_monitor}</thead>
<tbody>{body_monitor}</tbody>
</table>
<script>
(function(){{
  var table = document.getElementById("monitor-table-register");
  if (!table) return;
  function getCellValue(td) {{
    var t = (td && td.textContent || "").trim().replace(/[,%]/g, "");
    if (t === "" || t === "-") return null;
    var n = parseFloat(t);
    return isNaN(n) ? t : n;
  }}
  function sortRows(tbody, colIndex, order) {{
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    rows.sort(function(a, b) {{
      var cellA = a.cells[colIndex], cellB = b.cells[colIndex];
      var valA = getCellValue(cellA), valB = getCellValue(cellB);
      if (valA === null) valA = order === "desc" ? -Infinity : Infinity;
      if (valB === null) valB = order === "desc" ? -Infinity : Infinity;
      if (typeof valA === "number" && typeof valB === "number")
        return order === "desc" ? valB - valA : valA - valB;
      var sA = String(valA), sB = String(valB);
      if (sA < sB) return order === "desc" ? 1 : -1;
      if (sA > sB) return order === "desc" ? -1 : 1;
      return 0;
    }});
    rows.forEach(function(r) {{ tbody.appendChild(r); }});
  }}
  function updateArrows(activeCol, order) {{
    var ths = table.querySelectorAll("thead th.th-sort");
    ths.forEach(function(th) {{
      var idx = th.getAttribute("data-col-index");
      var a = th.querySelector("a.sort-arrow");
      if (!a) return;
      if (idx === String(activeCol)) {{ th.setAttribute("data-order", order); a.textContent = order === "desc" ? "▼" : "▲"; }}
      else {{ th.setAttribute("data-order", "desc"); a.textContent = "↕"; }}
    }});
  }}
  table.addEventListener("click", function(e) {{
    var a = e.target.closest("a.sort-arrow");
    if (!a) return;
    e.preventDefault();
    var th = a.closest("th.th-sort");
    if (!th) return;
    var colIndex = parseInt(th.getAttribute("data-col-index"), 10);
    var order = th.getAttribute("data-order") === "desc" ? "asc" : "desc";
    th.setAttribute("data-order", order);
    updateArrows(colIndex, order);
    var tbody = table.querySelector("tbody");
    if (tbody) sortRows(tbody, colIndex, order);
  }});
}})();
</script></body></html>
"""
try:
    import streamlit.components.v1 as components
    nrows = len(monitor_df)
    components.html(_monitor_table_html, height=min(600, 120 + nrows * 28), scrolling=False)
except Exception:
    st.markdown(f"<div class='monitor-table'><table class='monitor-table' id='monitor-table-register'><thead>{header_monitor}</thead><tbody>{body_monitor}</tbody></table></div>", unsafe_allow_html=True)

# 브랜드별 입출고 모니터링 (deploy와 동일: HTML 테이블 + 브랜드 클릭 시 시즌 토글)
TABLE_COLS = ["발주 STY수", "발주액", "입고 STY수", "입고액", "출고 STY수", "출고액", "판매 STY수", "판매액"]

def _fmt_table_num(v):
    if v is None or pd.isna(v):
        return "0"
    try:
        return f"{int(round(float(v))):,}"
    except Exception:
        return "0"

def _fmt_eok_table(v):
    if v is None or pd.isna(v):
        return "0 억 원"
    try:
        return f"{float(v) / 1e8:,.0f} 억 원"
    except Exception:
        return "0 억 원"

def _get_season_rows(brand):
    df = brand_season_df[brand_season_df["브랜드"] == brand].sort_values("시즌")
    if df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "시즌": str(r["시즌"]).strip(),
            "발주 STY수": _fmt_table_num(r["발주 STY수"]),
            "발주액": _fmt_eok_table(r["발주액"]),
            "입고 STY수": _fmt_table_num(r["입고 STY수"]),
            "입고액": _fmt_eok_table(r["입고액"]),
            "출고 STY수": _fmt_table_num(r["출고 STY수"]),
            "출고액": _fmt_eok_table(r["출고액"]),
            "판매 STY수": _fmt_table_num(r["판매 STY수"]),
            "판매액": _fmt_eok_table(r["판매액"]),
        })
    return rows

def _build_inout_table_html(display_df):
    cols = ["브랜드"] + TABLE_COLS
    header_cells = "".join(f"<th>{html_lib.escape(str(c))}</th>" for c in cols)
    body_rows = []
    for _, row in display_df.iterrows():
        brand_name = str(row.get("브랜드", "")).strip()
        brand_id = f"brand-{abs(hash(brand_name))}"
        brand_cell = (
            "<td class='brand-cell'>"
            f"<button type='button' class='brand-toggle' data-target='{brand_id}' aria-expanded='false'>"
            f"<span class='label'>{html_lib.escape(brand_name)}</span>"
            "<span class='caret'>▽</span>"
            "</button>"
            "</td>"
        )
        other_cells = "".join(
            f"<td>{html_lib.escape(str(row.get(c, '')))}</td>" for c in TABLE_COLS
        )
        body_rows.append(f"<tr class='brand-row'>{brand_cell}{other_cells}</tr>")
        for srow in _get_season_rows(brand_name):
            season_cells = (
                f"<td>└ {html_lib.escape(str(srow['시즌']))}</td>"
                + "".join(f"<td>{html_lib.escape(str(srow.get(c, '')))}</td>" for c in TABLE_COLS)
            )
            body_rows.append(f"<tr class='season-row' data-parent='{brand_id}'>{season_cells}</tr>")
    html = f"""
<style>
.brand-expand-table {{ width:100%; border:1px solid #334155; border-radius:8px; overflow:hidden; background:#1e293b; color:#f1f5f9; margin-top:0.5rem; }}
.brand-expand-table table {{ width:100%; border-collapse:collapse; }}
.brand-expand-table th, .brand-expand-table td {{ border:1px solid #334155; padding:6px 8px; text-align:center; font-size:0.95rem; }}
.brand-expand-table thead th {{ background:#0f172a; color:#f1f5f9; font-weight:700; font-size:1rem; }}
.brand-expand-table .brand-row {{ background:#111827; }}
.brand-expand-table .brand-cell {{ text-align:left; }}
.brand-expand-table .brand-toggle {{ all:unset; cursor:pointer; display:inline-flex; align-items:center; gap:6px; font-weight:700; color:#f1f5f9; }}
.brand-expand-table .brand-toggle .caret {{ display:inline-block; transition:transform 0.15s ease-in-out; color:#94a3b8; font-size:0.9rem; }}
.brand-expand-table .brand-toggle[aria-expanded="true"] .caret {{ transform:rotate(90deg); }}
.brand-expand-table .season-row td {{ background:#0f172a; font-size:0.9rem; color:#cbd5e1; }}
.brand-expand-table .season-row td:first-child {{ text-align:left; padding-left:18px; }}
</style>
<div class="brand-expand-table"><table><thead><tr>{header_cells}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>
<script>
(function(){{
  document.querySelectorAll(".season-row").forEach(function(r){{ r.style.display = "none"; }});
  document.querySelectorAll(".brand-toggle").forEach(function(btn){{
    btn.addEventListener("click", function(){{
      var target = btn.getAttribute("data-target");
      var expanded = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", expanded ? "false" : "true");
      document.querySelectorAll(".season-row[data-parent='" + target + "']").forEach(function(r){{
        r.style.display = expanded ? "none" : "table-row";
      }});
    }});
  }});
}})();
</script>
"""
    return html, len(body_rows)

st.markdown('<div style="height:40px;"></div>', unsafe_allow_html=True)
st.markdown('<div class="section-title">브랜드별 입출고 모니터링</div>', unsafe_allow_html=True)
st.markdown('<div style="font-size:1.1rem;color:#cbd5e1;margin-bottom:0.5rem;">STY 기준 통계</div>', unsafe_allow_html=True)
display_df = pd.DataFrame(inout_rows)[["브랜드"] + TABLE_COLS]
st.caption("브랜드명을 클릭하면 시즌별 수치를 보실 수 있습니다")
try:
    import streamlit.components.v1 as components
    inout_html, row_count = _build_inout_table_html(display_df)
    components.html(inout_html, height=min(600, 120 + row_count * 28), scrolling=True)
except Exception:
    inout_html, _ = _build_inout_table_html(display_df)
    st.markdown(inout_html, unsafe_allow_html=True)
