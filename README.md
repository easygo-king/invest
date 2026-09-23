# 투자자별 수급 차트 (Streamlit)

개인·외국인의 **현물(KOSPI) · 선물 · 현선물 통합 순매수**를 누적/일별로 보고, **60일·120일 이동평균선**을 겹쳐 보는 대시보드입니다.
매일 데이터를 입력 창에서 추가하면 차트가 바로 갱신됩니다. 단위는 **억원**입니다.

- 진입 파일: **`streamlit_app.py`** (Streamlit Community Cloud 가 기본으로 찾는 이름)
- 차트: Plotly (마우스를 올리면 값 표시, 확대/이동 가능)
- 저장: 기본은 로컬 SQLite 파일, 웹 배포 시에는 PostgreSQL(`DATABASE_URL`)

## 폴더 구조

```
invest-flow-streamlit/
├─ streamlit_app.py       화면과 진입점 (차트 탭 / 데이터 입력 탭)
├─ core/
│   ├─ calc.py            누적·이동평균·기간·통합 계산 (pandas)
│   └─ db.py              저장소 (SQLite 기본, DATABASE_URL 이 있으면 PostgreSQL)
├─ seed_data.csv          PDF에서 옮긴 초기 데이터 (DB가 비어 있을 때 최초 1회 자동 입력)
├─ requirements.txt
├─ .streamlit/
│   ├─ config.toml
│   └─ secrets.toml.example   관리자 비밀번호 / DB 주소 예시
├─ tools/make_seed.py     seed_data.csv 생성 스크립트
├─ tests/                 자동 테스트 (계산, DB, 화면 흐름)
└─ .vscode/               VS Code 실행/디버그/테스트 설정
```

## 내 PC에서 실행 (VS Code)

1. VS Code에서 `File > Open Folder` 로 `invest-flow-streamlit` 폴더를 엽니다. Python 확장(ms-python.python)을 설치합니다.
2. 터미널을 열고(`Ctrl + ~`) 가상환경과 패키지를 설치합니다.
   ```bash
   python -m venv .venv
   # Windows PowerShell
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate

   pip install -r requirements.txt
   ```
3. 실행: `F5` (디버그) 또는 터미널에서 `streamlit run streamlit_app.py`
4. 브라우저가 자동으로 열리지 않으면 http://localhost:8501 에 접속합니다.

첫 실행 때 `data.db` 가 만들어지고 `seed_data.csv` 데이터가 들어갑니다.

## 웹에 배포하기 (Streamlit Community Cloud)

웹 호스팅은 앱이 재시작·재배포될 때 파일이 초기화되어 **SQLite 파일에 저장한 데이터가 사라집니다.**
그래서 웹에서는 PostgreSQL 같은 외부 DB를 함께 쓰는 것이 필수입니다.

1. **PostgreSQL 준비**: 무료 티어가 있는 관리형 PostgreSQL(예: Neon, Supabase)에서 DB를 하나 만들고 연결 문자열을 복사합니다. 형식은 다음과 같습니다. (서비스별 정책은 바뀔 수 있으니 확인하세요.)
   ```
   postgresql://사용자:비밀번호@호스트:5432/DB이름?sslmode=require
   ```
   테이블은 앱이 처음 접속할 때 자동으로 만들고, 비어 있으면 `seed_data.csv` 를 넣습니다.
2. **GitHub 저장소에 올리기**: 이 폴더 전체를 올립니다. `data.db` 와 `.streamlit/secrets.toml` 은 `.gitignore` 로 제외되어 있습니다.
3. https://share.streamlit.io 에서 **Create app** → 저장소와 브랜치를 고르고 **Main file path 에 `streamlit_app.py`** 를 입력합니다.
4. **Advanced settings > Secrets** 에 아래를 붙여넣습니다.
   ```toml
   ADMIN_PASSWORD = "내가-정한-비밀번호"
   DATABASE_URL = "postgresql://사용자:비밀번호@호스트:5432/DB이름?sslmode=require"
   ```
5. **Deploy**. 이후에는 웹 주소로 접속하면 됩니다. 데이터 입력 탭 위쪽에 "저장소: PostgreSQL" 이라고 표시되면 정상입니다.

**보안**
- `ADMIN_PASSWORD` 를 설정하면 조회는 누구나 가능하고, 저장·삭제·가져오기는 비밀번호가 있어야 합니다. 설정하지 않으면 주소를 아는 누구나 데이터를 바꿀 수 있습니다.
- 차트 조회까지 막으려면 호스팅의 앱 공유(접근 제한) 설정을 확인하세요. 이 앱의 비밀번호는 쓰기 보호용입니다.
- DB 연결에 실패하면 접속 정보(사용자, 비밀번호)는 화면에 표시하지 않고 안내 문구만 보여줍니다.

**자체 서버(VPS, 사무실 PC)에서 운영**: 파일이 유지되는 곳이라면 SQLite 그대로 써도 됩니다.
```bash
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```
비밀번호와 DB 주소는 `.streamlit/secrets.toml`(예시 파일 참고) 또는 환경변수 `ADMIN_PASSWORD`, `DATABASE_URL`, `DB_PATH` 로 지정합니다.

## 사용법

**차트 탭**
- 기간 검색: 조회 기간 칸에서 시작일~종료일을 직접 선택하거나, 1개월·3개월·6개월·1년·전체 버튼을 누릅니다.
  버튼을 선택한 상태에서는 새 데이터가 들어오면 기간이 최신 날짜까지 자동으로 늘어납니다.
- 누적 순매수 / 일별 순매수 전환, 60일선·120일선 켜고 끄기
- "조회 시작일을 0으로": 선택한 기간의 시작점부터 누적을 새로 셉니다 (누적 모드에서만)
- 각 차트 위 숫자: 당일, 누적, 60일선, 120일선 값과 현재 위치(60일선 위/아래)
- 차트 6개: 현물 개인/외국인, 선물 개인/외국인, 현·선물 통합 개인/외국인
- 조회는 최대 60초 캐시되고, 저장·삭제·가져오기 직후에는 즉시 갱신됩니다. 다른 곳에서 DB를 직접 고쳤다면 최대 1분 뒤 반영됩니다.

**데이터 입력 탭**
- 매일 장 마감 후 일자와 현물·선물의 개인·외국인 값을 입력하고 저장합니다.
- `+1,234` / `-1,234` 처럼 HTS 표기를 그대로 붙여넣어도 됩니다.
- 이미 있는 날짜를 고르면 저장된 값이 채워지고, 저장하면 덮어씁니다 (수정). 한쪽 시장만 입력해도 됩니다.
- 일자를 키보드로 입력했다면 다른 곳을 한 번 클릭해 화면이 갱신된 뒤에 값을 입력하세요.
- 여러 날짜는 CSV 붙여넣기/파일로 한 번에 넣을 수 있습니다 (`시장,날짜,개인,외국인`).
- 입력 내역 표에서 확인하고, "데이터 삭제"로 특정 날짜를 지울 수 있습니다.
- "CSV로 내보내기"로 백업할 수 있습니다.

## 현·선물 통합 차트와 이동평균

- 통합 일별 값 = 현물 순매수 + 선물 순매수 (억원끼리 단순 합산)
- 누적과 60일·120일선은 **합산한 시계열에서 새로 계산**합니다 (현물 이평선과 선물 이평선을 더한 값이 아닙니다).
- 현물과 선물 **둘 다 데이터가 있는 날만** 통합에 사용합니다. 한쪽이 빈 날을 0으로 채우면 누적이 왜곡되기 때문입니다.
- 선물 금액은 계약 명목금액 기준이라 현물 매매대금과 성격이 다릅니다. 통합 수치는 "같은 억원 단위로 더한 값"으로 해석하세요.
- 누적 순매수 = 데이터 시작일부터의 일별 순매수 합계, 이동평균은 그 누적(일별 모드에서는 일별 값)의 단순이동평균입니다.
- 이동평균은 항상 **전체 데이터로 먼저 계산**하고 조회 기간만 잘라 보여줍니다. 기간을 짧게 잡아도 값이 달라지지 않습니다.
- 60일/120일치 데이터가 쌓이기 전에는 해당 선이 그려지지 않습니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```
- `test_core.py`: 누적, 이동평균, 기간 자르기, 통합, 누락 구간 탐지, DB 저장/가져오기
- `test_app.py`: 화면 흐름 (기간 검색, 표시 전환, 입력·수정·삭제·가져오기, 비밀번호, secrets 연동, DB 연결 실패 시 접속 정보 비노출)

기본은 임시 SQLite 로 실행합니다. **PostgreSQL 에서도 같은 테스트를 돌리려면** 테스트용 빈 DB 주소를 지정하세요. 해당 DB의 `flows` 테이블은 테스트마다 지워지므로 운영 DB를 쓰지 마세요.
```bash
# macOS / Linux
TEST_DATABASE_URL="postgresql://사용자:비밀번호@localhost:5432/테스트DB" python -m unittest discover -s tests -v
# Windows PowerShell
$env:TEST_DATABASE_URL="postgresql://사용자:비밀번호@localhost:5432/테스트DB"; python -m unittest discover -s tests -v
```

## 데이터 유의사항

- `seed_data.csv` 는 PDF 캡처 이미지를 읽어 옮긴 것입니다. 각 줄에서 `개인 + 외국인 + 기관계 + 기타법인 ≈ 0` 이 되는지 대조해 오독을 잡았지만, 판독 오류가 남아 있을 수 있습니다. 아래 행은 HTS와 한 번 더 대조하세요.
  - 선물: 2026-06-02, 06-04, 06-05, 08-03
  - 현물: 2026-05-12, 06-04, 07-20
- **선물 데이터에 2026-04-06 ~ 2026-05-07 구간(22거래일)이 없습니다** (PDF에 포함되지 않음). 선물 누적·이동평균이 실제와 다르고, 통합 차트에서도 이 구간이 빠집니다. HTS에서 해당 기간을 내려받아 CSV 가져오기로 채우면 자동 반영되고 화면의 누락 경고도 사라집니다.
- 선물은 115일치라 120일선이 아직 그려지지 않습니다. 누락 구간을 채우면 표시됩니다.
- 초기 데이터(seed)는 DB가 **완전히 비어 있을 때만** 들어갑니다. 모든 데이터를 삭제한 뒤 앱을 재시작하면 seed 가 다시 들어가니 유의하세요.
