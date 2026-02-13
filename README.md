# 온라인 상품등록 대시보드

브랜드별 입출고·상품등록 현황을 한눈에 볼 수 있는 Streamlit 대시보드입니다.

## 주요 기능

- **입출고 KPI**: 발주/입고/출고/판매 스타일 수, 금액 현황
- **브랜드별 상품등록 모니터링**: 등록스타일수, 등록율, 평균 등록 소요일
- **미등록 현황**: 미분배, 포토, 상품미등록 스타일 수
- **온라인 리드타임**: 촬영 → 인계 → 등록까지 소요일 시각화

## 지원 브랜드

- 캐쥬얼BU: 스파오
- 스포츠BU: 뉴발란스, 뉴발란스키즈, 후아유, 슈펜
- 여성BU: 미쏘, 로엠, 클라비스, 에블린

## 시작하기

### 요구 사항

- Python 3.9+
- 의존성: `requirements.txt` 참고

### 설치

```bash
# 저장소 클론
git clone https://github.com/YOUR_USERNAME/online-inventory-dashboard.git
cd online-inventory-dashboard

# 가상환경 생성 (권장)
python -m venv venv
venv\Scripts\activate   # Windows
# source venv/bin/activate  # macOS/Linux

# 의존성 설치
pip install -r requirements.txt
```

### 실행

```bash
streamlit run app_deploy.py
```

브라우저에서 `http://localhost:8501` 로 접속합니다.

## 데이터 파일

### 로컬 개발

`DB/` 폴더에 아래 엑셀 파일을 넣으면 자동으로 로드됩니다.

| 파일 | 용도 |
|------|------|
| 입출고 DB (260202 DB 등) | 발주/입고/출고/판매 데이터 |
| 스파오 상품등록 트래킹판 | 스파오 등록 현황 |
| 후아유 스타일판 촬영현황 | 후아유 촬영/등록 |
| 클라비스 스타일판 | 클라비스 등록 현황 |
| 미쏘 스타일판 | 미쏘 등록 현황 |
| 로엠 스타일판 | 로엠 등록 현황 |

자세한 파일 형식은 `DB/README.md` 참고.

### 배포 환경 (Streamlit Cloud 등)

사이드바에서 엑셀 파일을 업로드하면 메모리에서 바로 읽어 사용합니다.  
디스크 저장 없이 `pd.read_excel(uploaded_file)` 패턴으로 처리됩니다.

## 프로젝트 구조

```
inventory_dashboard/
├── app_deploy.py      # 메인 앱 (배포용)
├── app.py             # 개발/테스트용
├── requirements.txt
├── DB/                # 엑셀 데이터 (로컬용)
│   └── README.md      # 데이터 파일 설명
├── static/            # 정적 리소스
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── .streamlit/
    └── config.toml    # 테마 설정
```

## 기술 스택

- **Streamlit** - 대시보드 UI
- **Pandas** - 데이터 처리
- **openpyxl / xlrd** - 엑셀 읽기
- **Plotly** - 차트

## GitHub에 올리기

```bash
cd inventory_dashboard

# Git 초기화 (이미 되어 있으면 생략)
git init

# 원격 저장소 연결
git remote add origin https://github.com/YOUR_USERNAME/online-inventory-dashboard.git

# 추가 & 커밋 & 푸시
git add .
git status   # DB/*.xlsx 등이 제외되었는지 확인
git commit -m "Initial commit: 온라인 상품등록 대시보드"
git branch -M main
git push -u origin main
```

`.gitignore`에 의해 DB 폴더의 엑셀 파일은 자동으로 제외됩니다.

## 라이선스

MIT License
