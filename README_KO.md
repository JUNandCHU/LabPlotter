# LabPlotter 0.9.1

FTIR, NanoDrop UV–Vis, ssNMR, ZetaSizer, Lab DLS 및 TEM TIFF 데이터를 플롯하고 비교·분석하는 Windows 데스크톱 및 웹 앱입니다. 데스크톱의 측정 파일과 particle library는 외부 서버로 전송되지 않습니다.

## 0.8.1 웹 버전

- `web/streamlit_app.py`에서 실행되는 Streamlit UI 추가
- 데스크톱과 동일한 FTIR, NanoDrop, Bruker ssNMR, ZetaSizer 및 TEM 분석 코어 사용
- 브라우저에서 여러 파일 업로드, 데이터 선택, 색상·축·선 설정 및 PNG/SVG/CSV 다운로드
- 영어/한국어 전환과 한글 그래프용 Noto CJK 글꼴 지원
- 초기 웹 버전은 브라우저 세션 단위로 동작하며 공동 particle/TEM library를 서버에 영구 저장하지 않음
- 로컬 SQLite library, 편집형 OCR 검수, Windows 클립보드 복사 및 `.labpatch` 업데이트는 데스크톱 전용으로 유지

로컬에서 웹 UI를 미리 보려면 `python -m pip install -r web/requirements.txt`를 한 뒤 `python -m streamlit run web/streamlit_app.py`를 실행합니다. Streamlit Community Cloud에서는 이 GitHub 저장소를 선택하고 main file을 `web/streamlit_app.py`로 지정합니다.

## 현재 구현된 기능

### 언어와 클립보드

- 기본 UI 언어는 영어이며 상단 `Language` 선택 상자에서 `English`와 `한국어`를 즉시 전환
- 선택한 언어는 `%LOCALAPPDATA%\LabPlotter\settings.json`에 저장되어 다음 실행에도 유지
- 탭, 그래프 parameter, 선택 항목, 팝업, 오류 메시지, FTIR 도움말 및 그래프 기본 축 이름을 함께 전환
- Windows 64-bit 포인터 형식을 명시한 CF_DIB 이미지 클립보드 복사
- 다른 프로그램이 클립보드를 잠근 경우 짧게 재시도하며 실패 시 안전하게 메모리 해제
- 한글 축 제목이나 범례가 있으면 Windows의 `Malgun Gothic` 등 설치된 한글 지원 글꼴을 자동 선택
- 상단 `Contact…`에서 관리자 이름과 이메일, 피드백 안내 확인 및 이메일 복사

### 공통 그래프 비율과 기본 색상 (0.8.4)

- `Graph settings… → Graph ratio`에서 가로:세로를 고정할 수 있습니다. `Square (1:1)`은 정사각형, `Restore default ratio`는 창 크기에 맞추는 기본 모드입니다. 다른 설정을 바꾸지 않고 비율만 복원할 수 있습니다.
- 비율은 축 제목을 포함한 전체 그림에 적용되며, X/Y 데이터 단위나 축 범위를 바꾸지 않습니다. 미리보기·클립보드·PNG·SVG·PDF에 동일하게 적용하고 고정 비율에서는 자동 잘라내기로 비율이 바뀌지 않습니다. 가로/세로는 0.1~10 범위입니다.
- 웹도 그래프 설정의 가로/세로·정사각형·기본 비율 복원을 지원하며 미리보기와 다운로드의 비율이 같습니다.
- 기본 데이터 색상 순서는 RGB `(0,0,0)`, `(192,0,0)`, `(0,32,96)`, `(164,159,159)`, `(0,108,49)`, `(64,31,104)`, `(184,112,24)`입니다. 이후에는 추가 팔레트를 사용합니다. 사용자가 지정한 개별 색상도 지원합니다.

### FTIR

- CSV/TXT/TSV/XLSX 파일 여러 개 동시 import 및 한 그래프에 overlay
- 각 curve 표시/숨김과 이름 변경
- Baseline correction 토글 및 여섯 가지 방법
  - Linear endpoints: 양 끝 구간을 연결하는 대각선 baseline
  - Rubberband convex hull
  - Modified polynomial (ModPoly)
  - AsLS
  - arPLS
  - airPLS
- Transmittance는 upper baseline으로 나눈 뒤 100을 곱하고, absorbance는 lower baseline을 뺌
- 각 방법 옆 `?`에 마우스를 올리면 계산 원리와 주의점 표시
- Min–max, maximum, vector normalization 토글
- trough peak 위치 자동 표시와 prominence 조절
- FTIR X축 반전 토글
- FTIR에서는 X축 반전이 기본으로 활성화됨

### NanoDrop UV–Vis

- Excel 2003 XML 및 XLSX의 여러 worksheet 자동 추출
- worksheet의 C2를 sample 이름으로 사용
- `Blank` 이름을 자동 감지해 기본적으로 제외
- 필요하면 첫 Blank 하나만 overlay
- 여러 파일과 여러 worksheet를 한 그래프에서 비교

NanoDrop의 `10mm Absorbance`는 10 mm optical path length로 환산된 absorbance입니다. Absorbance는 엄밀히 무차원이므로 기본 Y축 단위는 비워 두었습니다. 필요하면 그래프 설정에서 `a.u.`를 입력할 수 있습니다.

### Lab DLS (0.9.1)

기존 ZetaSizer와 별도 탭입니다. `Radius (nm), Meas 1, Meas 2, ...` CSV 여러 개를 가져오며, 빈칸은 해당 측정에 없는 좌표로 처리합니다. 입자 이름은 CSV 확장자를 제외한 파일명이고 왼쪽 목록에서 이름 변경·제거할 수 있습니다.

- 데이터 목록 오른쪽에는 선택 입자와 오버레이 그래프가 나란히 있습니다. 각 그래프 아래에 측정별 및 전체 측정 평균 반지름·직경·%PD 표를 표시합니다. 표와 그래프 사이 구분선을 드래그하여 공간을 조절할 수 있습니다.
- 기본 축은 PDF의 최종 조건인 **X = 0.01–1,000,000 nm (로그), Y = 0–20% Intensity**입니다. 개별 측정의 원본 점을 선으로 연결하며 smoothing/fitting은 적용하지 않습니다. 20%를 넘는 피크는 안내 문구와 `Fit Y axis` 버튼으로 전체 높이를 확인할 수 있습니다. 축 범위는 그래프 설정에서 변경합니다.
- `Save to library`는 선택 항목을 별도 `lab_dls_library.sqlite3`에 저장합니다. 라이브러리 창에서 재불러오기·이름 변경·삭제·위/아래 순서 이동을 지원합니다. 앱 업데이트 후에도 유지됩니다. 목록 제거와 라이브러리 삭제는 독립적입니다.
- `Register graph overlay`를 눌러야 오버레이에 등록됩니다. 등록 목록에서 선택하여 해제할 수 있습니다. 기본은 각 입자의 **대표 평균 곡선 하나**이고 `Show all measurements in overlay`로 모든 측정을 표시합니다. 입자 색상은 공통 7색 우선순위이며 모든 측정 모드에서는 같은 입자를 같은 색과 서로 다른 선 모양으로 구분합니다.
- 선택 그래프에는 평균 반지름의 수직선과 `mean R` 주석이 기본으로 켜져 있고, 오버레이에서는 기본으로 꺼져 있습니다. `Graph settings… → Lab DLS annotations`에서 각각 표시 여부, 선 모양·굵기, 글꼴·크기·굵게, 색상·투명도·자릿수를 변경합니다. 주석을 직접 잡아 드래그하면 위치가 저장됩니다. 일반 `Copy graph`도 **현재 보이는 주석과 배치 전체**를 그대로 복사합니다. 공통 비율 설정 및 정사각형/기본값 복원도 지원합니다.
- 선택 입자의 측정 표에는 `Hide`와 `Exclude` 체크가 있습니다. **Hide**는 개별 곡선만 숨기고 평균 계산에는 포함합니다. **Exclude**는 해당 측정을 평균 수치·대표 평균 곡선·오버레이 계산에서 즉시 제외합니다. 원본은 보존하며 체크 해제 시 복원됩니다. 모든 측정을 제외하면 평균은 `N/A`, 곡선은 표시하지 않습니다. 이 상태는 라이브러리 저장/불러오기와 JSON에 보존되며 결과 CSV에도 기록됩니다.
- `Average distribution only`를 켜면 선택 그래프에도 포함된 측정들의 대표 평균 곡선 하나와 그 곡선의 mean R/수직선을 표시합니다. 양쪽 그래프 바로 아래의 `Mean R labels`, `Mean lines`로 표시를 토글하고 `Reset mean R label positions`로 위치를 초기화합니다. 그래프 설정과 같은 옵션을 공유합니다.
- 오버레이 결과 표는 기본으로 입자별 **측정 평균 행 하나**만 표시합니다. 맨 왼쪽 `+`로 그 입자의 측정들을 펼치고 `-`로 접습니다. 제외된 측정은 회색 및 `[excluded]`로 구분합니다. 펼침 상태는 평균 재계산 후에도 유지됩니다.
- 데이터/오버레이/라이브러리/결과 표의 행 높이는 실제 UI 글꼴 높이 + 12px 이상으로 잡습니다. 가로·세로 스크롤도 지원합니다.

계산은 %Intensity를 **각 bin의 가중치**로 사용합니다. `mean R = Σ(I×R)/ΣI`, `mean D = 2×mean R`, `σR = √[Σ(I×(R−mean R)²)/ΣI]`, `%PD = 100×σR/mean R`입니다. 선형 반지름 간격으로 다시 적분하지 않으며, 그래프 확대·축 변경에도 전체 원본 bin을 계산에 사용합니다. 전체 측정 평균은 분석에서 제외하지 않은 각 측정 결과의 산술평균입니다. 0으로만 된 측정은 계산 불가(N/A)이며 평균에서 조용히 제외하지 않습니다.

대표 곡선은 원본의 가장 작은 대표 log 간격으로 공통 로그 격자를 만들고 각 곡선을 log(radius)에서 선형 보간한 후 동일 가중 평균합니다. 피크 정규화는 하지 않습니다. 0으로 끝나는 꼬리만 범위 밖을 0으로 확장하며, 측정 범위가 다른데 끝점이 0이 아니면 외삽하지 않고 모든 측정 모드를 사용하도록 안내합니다. 대표 곡선의 평균 R/%PD는 그 곡선에서 계산하므로 개별 측정 결과들의 산술평균과 다를 수 있습니다. 선택 그래프의 평균 모드 및 내보내기 CSV에는 대표 곡선 값을 별도 행으로 구분합니다. 오버레이 표의 요약은 측정 결과들의 산술평균이며, 그래프 주석은 대표 곡선 자체의 mean R입니다.

**CSV 분포 통계는 장비의 cumulants Z-average/PDI 값이 아닙니다.** CSV에는 상관함수나 장비의 cumulants 결과가 없으므로 이를 복원했다고 표시하지 않습니다. 다중 피크도 전체 분포 계산에 포함되며 장비의 개별 피크 통계와 다를 수 있습니다. `Calculation method…`와 결과 CSV 내보내기를 제공합니다. 분석 방식의 차이는 [Wyatt의 DLS 설명](https://www.wyatt.com/library/theory/dynamic-light-scattering-theory.html)을 참고할 수 있습니다.

웹도 같은 CSV·계산·오버레이 코어를 사용합니다. 웹 라이브러리는 세션별이며 JSON으로 저장/불러오기합니다. 데스크톱의 주석 드래그 대신 웹에서는 주석 X/Y 비율 좌표를 지정하며, 다운로드에도 해당 위치를 적용합니다.

### Solid-state NMR (0.8.6)

`Import ASCII TXT…`로 TopSpin의 **4열 ASCII**를 가져옵니다. **4열 ppm / 2열 intensity**를 사용하며 첫 줄의 1열에 제목이 있어도 측정점은 보존합니다. 이름은 파일명에서 확장자를 제외한 값이고 언제든 변경할 수 있습니다. ZIP/FID 가져오기는 제거했습니다.

1. 왼쪽 목록에서 항목을 클릭하면 오른쪽에 해당 원본 스펙트럼이 표시됩니다.
2. `Save to library`는 선택한 원본 데이터를 별도 `ssnmr_library.sqlite3`에 저장합니다. 이 파일은 앱 설치 폴더 밖의 사용자 데이터 폴더에 있어 업데이트 후에도 유지됩니다.
3. `Open ssNMR library…`에서 저장 데이터를 재불러오기·이름 변경·삭제·순서 변경할 수 있습니다. 현재 목록에서 제거하는 동작과 라이브러리 삭제는 독립적입니다.
4. `Compare two spectra…` → 기준 A와 비교 B 선택 → 전처리 설정 → `Process and compare`를 누르면 별도 비교 창이 열립니다.
5. 비교 창의 ppm 범위와 적분 구간을 바꾸면 결과가 자동으로 갱신됩니다. `Calculate / update range`로 즉시 적용할 수도 있습니다. 전체 비교 구간·Aliphatic·Aromatic 각각의 R², r², r, N과 두 스펙트럼의 적분비가 **그래프 아래**에 표시됩니다. 두 검증 버튼은 세 구간의 계산 과정과 전처리 내역을 별도 창으로 엽니다.

`Aliphatic region` / `Aromatic region` / `Custom region` 버튼은 현재 입력된 해당 구간을 공통 ppm 최솟값·최댓값으로 지정하고, **원본 스펙트럼에서 전처리를 다시 실행**합니다. 자동 정렬과 정규화는 선택한 구간을 기준으로 다시 계산하고 그래프와 R²·r²를 갱신합니다. Custom의 기본값은 0–200 ppm이며 `Custom min/max`에서 수정합니다. 전처리 범위는 그래프 위에 표시되고 `Preprocessing settings…`에도 반영됩니다. 정렬 구간은 선택한 범위 전체를 사용하며, 격자 간격·baseline 사용 여부·Gaussian 폭·정규화 방식 등 나머지 옵션은 유지합니다. 반복 전환은 항상 원본에서 계산하므로 정규화나 smoothing이 누적되지 않습니다.

전처리 기본값:

- ppm 범위는 두 파일의 전체 범위를 포함합니다. 공통 격자 간격은 두 입력 중 더 거친 간격을 기준으로 하며, 정확한 양끝점을 포함하기 위해 실제 간격이 미세 조정될 수 있습니다. 범위 밖 값은 NaN으로 남기고 외삽하거나 0으로 채우지 않습니다.
- 실수 intensity만 있는 ASCII에는 허수 스펙트럼/FID가 없습니다. **내보낸 TopSpin 위상을 유지**하고 복소 위상 보정은 수행하지 않았음을 표시합니다.
- 각 원본 전체 범위의 양끝 3% 중앙값으로 직선 베이스라인을 구해 뺍니다. 구간 양끝에 실제 피크가 있다면 설정을 검토하거나 보정을 끌 수 있습니다.
- B에 최대 ±2 ppm의 일정한 이동을 적용해 기준 A와 정렬합니다. 전 구간 또는 지정 구간의 Pearson r을 최대화하며 이동량을 기록합니다. 형태를 늘이거나 부분적으로 왜곡하지 않습니다. 서로 다른 화학종의 피크 차이가 있는 경우 정렬 구간을 제한하거나 정렬을 끌 수 있습니다.
- 두 데이터에 동일한 추가 Gaussian FWHM 0.3 ppm을 적용합니다. 0으로 설정하면 끕니다. 기존 TopSpin broadening을 되돌리거나 서로 다른 원래 해상도를 같게 만드는 기능은 아닙니다.
- 공통 측정 범위의 최대 절대 intensity로 각각 정규화합니다. 전체 절대 면적 정규화 또는 정규화 없음도 가능합니다. 비교 창에서 통계 범위만 바꾸면 전처리는 바뀌지 않습니다.

계산 정의:

- 전체 비교 구간 통계는 현재 표시된 전처리 결과를 사용합니다. Aliphatic/Aromatic 통계는 각각의 구간에서 원본을 별도로 전처리·정규화한 결과를 사용하며, 경계값 수정 시 갱신됩니다. 구간별 전처리 범위·이동량·정규화 계수·각 단계의 측정점은 검증 내역에 기록됩니다.
- Aliphatic/aromatic **적분비**는 두 구간을 함께 포함한 공통 전처리 결과에서 계산합니다. 한 스펙트럼의 분자·분모에는 같은 이동량과 정규화 배율을 적용하여 구간별 정규화로 상대 신호량이 지워지지 않게 합니다. 표시 구간 버튼을 전환해도 이 적분 기준은 유지되며, 수동 전처리 설정 변경 시에는 새 설정을 반영합니다. 적분 검증 창의 전처리 탭에서 공통 처리 범위를 확인할 수 있습니다.

- **R² (직접 일치도)** = `1 − Σ(A−B)² / Σ(A−mean(A))²`. A가 기준이며 회귀로 B의 크기나 오프셋을 다시 맞추지 않습니다. 음수가 될 수 있습니다.
- **r²** = Pearson r의 제곱. r도 같이 표시하므로 양/음의 상관을 구별할 수 있습니다. 상수 스펙트럼은 정의되지 않는 값을 `Undefined`로 표시합니다.
- **적분비** = signed `I(0–50 ppm) / I(90–160 ppm)`가 기본이며 각 경계는 수정할 수 있습니다. ppm을 오름차순으로 놓고 정확한 경계점의 intensity를 선형 보간한 뒤 사다리꼴 면적을 합산합니다. 음의 값을 0으로 바꾸거나 절댓값 처리하지 않습니다. 영역 전체가 측정 범위에 들어와야 하며 분모가 거의 0이면 계산 불가입니다.
- 검증 창에는 적용한 설정, 입력 해시, 이동량, 정규화 계수, 처리 단계별 각 점, 평균·잔차·제곱합 및 모든 적분 조각과 누적 면적이 포함됩니다. 전체 내역 TXT 및 처리 스펙트럼 CSV를 저장할 수 있습니다.

웹도 동일한 계산 코어를 사용합니다. 웹 라이브러리는 브라우저 세션별이며 `Download library JSON`으로 원본·이름·순서를 저장하고 다음 접속 때 다시 가져옵니다. 다른 사용자와 공유하는 서버 DB는 만들지 않습니다.

### ZetaSizer particle library

- 여러 sheet에서 DLS와 zeta-potential raw distribution 자동 구분
- A:B, C:D, E:F를 measurement 1–3으로 연결
- sheet 이름의 `Cell_N` 정보를 metadata로 저장
- particle 이름별로 DLS/Zeta triplicate를 로컬 SQLite library에 저장
- 메인 탭 왼쪽은 현재 그래프에 포함된 particle 이름, 평균 Z-average, 평균 zeta potential만 표시하고 추가/제거에 사용
- 전체 라이브러리는 별도의 크기 조절 가능한 창에서 source, batch alias, DLS/Zeta replicate 수, OCR 자동/검수/실패 상태와 OCR 필드를 함께 확인
- DLS, zeta-potential, batch별 Z-average, batch별 평균 zeta potential을 2×2 대시보드로 동시에 표시
- 네 그래프 모두 전체 곡선/막대에 한 색상을 일괄 적용하거나 particle별 개별 색상을 지정
- 선택한 particle 색상을 replicate, mean, SD 영역, peak label과 batch bar에 일관되게 적용
- 여러 particle을 선택해 distribution 그래프에서 다음 방식으로 비교
  - Mean ± SD
  - Mean + replicate curves
  - Replicates only
- DLS log-X 토글
- 단일 particle에서는 DLS 최대 intensity의 diameter와 zeta 최대 count의 potential을 기본 표시하며, 여러 particle에서도 사용자가 명시적으로 활성화 가능
- 자동 peak 레이블은 저장/클립보드에서 annotation과 같은 방식으로 포함 여부를 선택
- 통합문서를 가져오면 embedded result table을 즉시 로컬 OCR로 읽고 라이브러리에 자동 초안으로 저장
- OCR의 Z-Average와 Zeta Potential 평균을 반복 측정별로 모아 batch bar chart의 mean/median, SD/SEM error bar를 계산
- `241101_JM10A_AMP`는 `JM10A`, `JM38B_Cell_No_6`은 `JM38B`로 자동 축약하고 각 bar graph 설정에서 source와 함께 batch 이름을 직접 편집
- 확대된 행 높이, 가로/세로 스크롤, 드래그 가능한 패널 구분선
- 메인 plot-selection 목록과 별도 particle-library 표의 열 너비를 자동 저장하고 재실행·업데이트 후 복원
- 이름·업데이트 시각·DLS/Zeta 측정 수·검수된 OCR 수·원본별 정렬 및 기본 정렬 복원
- 선택한 particle과 연결된 모든 측정값을 확인 후 library에서 삭제
- 각 replicate에 대응하는 embedded measurement-result table을 원본 픽셀, 창 맞춤, 50–300% 확대 및 스크롤로 열람
- 현재 measurement의 표 이미지를 로컬 RapidOCR로 읽어 `DLS_OCR`/`Zeta_OCR` 검수 탭 생성
- 검수 탭에서 원본 이미지를 왼쪽, 편집 가능한 OCR 표를 오른쪽에 나란히 표시
- OCR이 놓친 행을 추가하거나 마지막 행을 제거하고 모든 셀을 직접 수정 가능
- 자동 OCR 초안을 라이브러리에 먼저 저장하고, 사용자가 원본과 대조·수정한 결과는 `reviewed` 상태로 갱신

OCR 결과는 편집을 돕는 초안입니다. 소수점·음수 부호·단위가 잘못 인식될 수 있으므로 논문용 수치로 사용하기 전에 반드시 원본 이미지와 대조해야 합니다. OCR은 외부 서버를 사용하지 않으며 이미지, OCR 표와 raw curve의 replicate 연결을 그대로 보존합니다.

### TEM particle size

- 한 개 또는 여러 개의 `.tif`/`.tiff` 이미지를 동시에 가져와 파일명의 배치 이름별로 자동 정리
- `JM66_PDA_100000X_0003.tif`에서는 `JM66_PDA`를 배치, `100000×`를 배율, `0003`을 이미지 번호로 분리
- 독립 합성 배치 수, 포함 이미지 수와 검출 입자 수를 서로 분리해 표시
- TIFF의 SHA-256을 비교해 이름만 `(1)`처럼 달라진 완전히 동일한 이미지는 중복 계산하지 않음
- 정보량·밝기 분포·윤곽 밀도로 검은 빈 화면을 감지해 기본적으로 자동 제외
- Hitachi H-D2300/Gatan 이미지의 밝은 scale bar 길이와 파일명 배율로 표시 스케일을 자동 추정
- 자동 보정된 scale 값, bar pixel 길이와 nm/pixel 값을 이미지별로 직접 수정하고 재분석 가능
- 최소/최대 입자 직경, 최소 중심 간격, threshold factor 및 경계 입자 제외 여부 조절
- 자동 빈 화면을 사용자가 강제로 분석하거나, 각 이미지를 포함/제외 상태로 전환 가능
- 원본 TIFF 위에 검출된 등가 원을 겹쳐 보며 segmentation 결과 검수
- 선택한 배치의 equivalent particle diameter 분포와 중앙값을 Origin 스타일 그래프로 표시
- 선택 이미지 또는 전체 라이브러리의 개별 입자 직경을 CSV로 내보내기
- 원본 TIFF는 체크섬 이름으로 `%LOCALAPPDATA%\LabPlotter\tem_images`에 한 번만 복사하고, 분석 결과와 검수 설정은 별도 SQLite library에 저장

TEM 입자 크기는 자동 segmentation을 이용한 선별용 추정값입니다. 특히 입자가 겹치거나 응집된 영상에서는 검출 원을 반드시 검토하고 threshold 및 중심 간격을 조정해야 합니다. 서로 다른 배율의 이미지를 합치면 `N_image`와 `N_particle`은 증가하지만 독립적인 합성 배치 `N_batch`가 증가하는 것은 아닙니다.

### 그래프와 custom format

- bottom/left major tick은 안쪽 방향
- top/right는 border line만 표시하고 tick은 표시하지 않음
- 모든 데이터 탭에서 이동 가능한 비모달 `Graph settings…` 창 사용
- `Lines and shapes…`는 그래프 바로 위에 항상 표시되며 별도 비모달 창으로 열림
- 그래프 설정에서 현재 데이터 탭의 기본 표시값으로 즉시 복원
- 실시간 미리보기 토글: 켜면 옵션 변경 즉시 반영, 끄면 `Apply`를 누를 때 반영
- X축 제목, Y축 제목, tick label, legend의 글꼴·크기·굵기·색상을 서로 독립적으로 조절
- curve/tick/frame 굵기, tick 길이, axis name/unit/range/spacing, X축 반전, legend 조절
- 모든 데스크톱 그래프의 상단 탐색 도구에 `Legend` 표시 체크를 제공합니다. 범례만 켜고 끄므로 현재 확대 범위는 유지됩니다.
- 범례를 **한 번 클릭하면 편집이 활성화**됩니다. 이후 안쪽 드래그로 위치를 이동하고 네 모서리 손잡이를 드래그하면 가로·세로 크기와 항목 열 배치가 바뀝니다. 글자가 잘리지 않도록 최소 크기를 유지합니다. 바깥 클릭 또는 Esc로 편집을 마칩니다. 재그리기·복사·저장에도 배치를 유지하며 파란 편집 손잡이는 출력되지 않습니다. 그래프 기본값 복원으로 범례 배치도 초기화합니다.
- `cm^-1` 또는 `cm⁻¹`을 입력하면 축에서는 mathtext superscript로 렌더링
- 데이터 목록과 FTIR range 표에 확대된 행 높이와 스크롤 제공
- 흰색/어두운 배경
- 그래프 위를 직접 드래그해 실선·긴 점선·점선·일점쇄선과 원·타원·직사각형 배치
- PNG/SVG/PDF 저장을 `그래프만`과 `그래프 + 주석 도형`으로 분리
- Windows 300 dpi 클립보드 복사도 `그래프만`과 `그래프 + 주석 도형`으로 분리
- 처음 보는 workbook은 preview에서 sheet, header row, data start row, X/Y column을 지정해 custom format으로 저장
- 같은 구조의 workbook은 저장된 fingerprint로 custom format 자동 매칭

상단 navigation tab은 선택 상태를 짙은 파란색으로 표시하고, 큰 padding과 굵은 글꼴 및 hover 상태를 사용합니다. 각 탭의 클릭 영역과 경계를 키워 작은 기본 Tk tab보다 구분과 선택이 쉽도록 구성했습니다.

## 가장 쉬운 실행 방법

1. Windows 10/11에 Python 3.10 이상을 설치합니다. 설치 화면에서 `Add python.exe to PATH`를 선택합니다.
2. 이 폴더의 `run_labplotter.bat`를 더블클릭합니다. 여러 Python이 설치되어 있으면 호환성이 높은 3.12를 우선 선택하고, 3.13, 3.11, 3.10, 3.14 순으로 사용 가능한 버전을 찾습니다.
3. 첫 실행 때 필요한 패키지가 설치됩니다. 이후에는 같은 파일을 더블클릭하면 바로 실행됩니다.

0.5.1 업데이트에서는 로컬 OCR 엔진과 ONNX 실행 패키지가 한 번 추가 설치되므로 평소 패치보다 다운로드와 설치 시간이 더 걸릴 수 있습니다. 설치 뒤 OCR을 포함한 데이터 처리는 오프라인으로 실행됩니다.

인터넷은 첫 패키지 설치에만 필요합니다. 측정 데이터 처리와 library 사용은 완전히 로컬입니다.

## 누적 패치 업데이트

0.6.0부터는 format-2 누적 스냅샷을 지원합니다. 누적 패치 하나에 목표 버전의 관리 대상 파일과 Python dependency 정보가 모두 포함되므로, `version.json`이 없던 초기 설치본을 포함해 인식 가능한 구버전에서 중간 패치를 순서대로 설치하지 않고 최신 버전으로 이동할 수 있습니다.

이 패치 방식은 `run_labplotter.bat`로 실행하는 표준 설치본용입니다. 선택적으로 직접 만든 PyInstaller EXE 배포본은 실행 파일의 묶음 구조가 달라 별도의 전체 빌드로 갱신합니다.

1. LabPlotter 오른쪽 위의 `Updates…`를 누릅니다.
2. `Apply .labpatch…`에서 전달받은 패치 파일을 선택합니다.
3. 앱이 닫힌 뒤 설치 버전과 기존/신규 파일의 SHA-256을 검사합니다.
4. 변경 대상 파일을 `.updates\backups`에 백업한 다음 패치를 적용하고 실행 가능 여부를 검사합니다.
5. 성공하면 새 버전으로 자동 재실행됩니다. 실패하면 기존 버전을 자동 복원합니다.

`.labpatch`는 직접 압축 해제하지 않습니다. 패치는 지정된 LabPlotter 관리 파일만 바꿀 수 있으며 측정 원본, custom format profile과 사용자가 추가한 알 수 없는 파일은 건드리지 않습니다. Particle library는 일반 패치에서는 유지되고, 초기화가 명시된 특별 migration 패치에서만 백업 후 초기화됩니다. 누적 패치는 목표 버전의 dependency를 확인하고 기존 `.venv`에 필요한 package를 추가·갱신합니다. 변경 전 package 버전 목록과 DB 구조 변경 전 particle library도 롤백용으로 보존합니다.

0.7.0 패치는 새 자동 OCR 라이브러리 구조를 일관되게 만들기 위해 기존 `particle_library.sqlite3`를 백업한 뒤 초기화합니다. 기존 ZetaSizer workbook을 다시 가져오면 result table OCR까지 자동 수행됩니다. 업데이트 직전 상태로 롤백하면 백업된 기존 라이브러리도 함께 복원됩니다. 이 초기화는 0.7.0 전환에만 적용되는 일회성 작업입니다.

0.5.1 이하의 업데이트기는 format-2 누적 패치를 직접 읽을 수 없습니다. 이런 구버전에서는 GitHub에서 `update_to_latest.bat` 하나를 LabPlotter 폴더에 내려받아 실행합니다. 이 부트스트랩 실행기가 최신 업데이트기와 누적 패치를 받은 뒤 동일한 백업·검증·자동 롤백 절차로 최신 버전까지 한 번에 이동시킵니다. 0.6.0 이후에는 앱 내부 Update Center만 사용하면 됩니다.

앱이 열리지 않는 상태에서도 다음 보조 실행기를 사용할 수 있습니다.

- `apply_update.bat`: Update Center를 독립적으로 실행
- `rollback_last_update.bat`: 마지막으로 성공한 패치 직전 버전을 복원

업데이트 기록은 `.updates\update.log`에, 각 롤백 백업은 `.updates\backups`에 남습니다. Python 실행 기반 자체를 교체해야 하는 드문 경우에는 새 전체 설치본을 배포합니다.

## 독립 실행형 EXE 만들기

Windows PC에서 `build_windows.bat`를 더블클릭하면 build 전용 dependency를 별도 `.buildvenv`에 설치하고 다음 위치에 실행 폴더가 만들어집니다.

`dist\LabPlotter\LabPlotter.exe`

`dist\LabPlotter` 폴더 전체를 함께 옮겨야 합니다. EXE 빌드 후에는 대상 PC에 Python이 필요하지 않습니다.

## 데이터 저장 위치

Windows에서는 다음 폴더에 particle library와 custom format profile이 저장됩니다.

`%LOCALAPPDATA%\LabPlotter`

- `particle_library.sqlite3`: ZetaSizer raw curves와 result-table images
- `tem_particle_library.sqlite3`: TEM 이미지별 보정값, 분석 설정 및 입자 크기 결과
- `tem_images`: 중복 제거된 로컬 TIFF 원본
- `format_profiles.json`: custom Excel format mappings

같은 workbook을 다시 import하면 같은 particle/measurement 항목을 업데이트하므로 중복이 누적되지 않습니다.

## 과학적 처리 관련 주의

- Baseline correction은 원자료를 덮어쓰지 않습니다. 토글을 끄면 즉시 raw spectrum으로 돌아갑니다.
- Baseline과 normalization은 화면 표시 및 export에만 적용됩니다.
- 자동 peak marking은 후보 위치를 찾는 보조 기능입니다. 작용기 assignment를 확정하지 않습니다.
- 서로 다른 X grid의 ZetaSizer triplicate는 공통 overlap 범위에 interpolation한 뒤 평균과 표준편차를 계산합니다.
- TEM 입자 분할은 등가 직경의 자동 추정이며, 겹친 입자·응집체·낮은 대비 영상에서는 원본 오버레이 검수가 필요합니다.
- TEM 통계는 `N_batch`, `N_image`, `N_particle`을 구분하며 개별 입자를 독립 합성 replicate처럼 해석하지 않습니다.
