# LabPlotter 0.5.1

FTIR, NanoDrop UV–Vis, ZetaSizer 데이터를 로컬에서 불러와 Origin 스타일로 플롯하고 비교하는 Windows 데스크톱 앱입니다. 측정 파일과 particle library는 외부 서버로 전송되지 않습니다.

## 현재 구현된 기능

### 언어와 클립보드

- 기본 UI 언어는 영어이며 상단 `Language` 선택 상자에서 `English`와 `한국어`를 즉시 전환
- 선택한 언어는 `%LOCALAPPDATA%\LabPlotter\settings.json`에 저장되어 다음 실행에도 유지
- 탭, 그래프 parameter, 선택 항목, 팝업, 오류 메시지, FTIR 도움말 및 그래프 기본 축 이름을 함께 전환
- Windows 64-bit 포인터 형식을 명시한 CF_DIB 이미지 클립보드 복사
- 다른 프로그램이 클립보드를 잠근 경우 짧게 재시도하며 실패 시 안전하게 메모리 해제
- 한글 축 제목이나 범례가 있으면 Windows의 `Malgun Gothic` 등 설치된 한글 지원 글꼴을 자동 선택
- 상단 `Contact…`에서 관리자 이름과 이메일, 피드백 안내 확인 및 이메일 복사

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

### Solid-state NMR

- Bruker/TopSpin 측정 폴더의 ZIP 파일을 압축 해제하지 않고 직접 import
- `acqus`, `procs`, raw `fid`에서 1D spectrum과 ppm 축 복원
- raw data byte order/type, digital group delay, 저장된 exponential window, zero filling 정보 반영
- 다음 위상 표시 방식 지원
  - Automatic phase: 해당 핵종 범위에서 분산형/음의 신호를 줄이는 자동 위상 보정
  - Saved TopSpin phase: `procs`의 PHC0/PHC1 사용
  - Magnitude: 위상과 무관한 크기 스펙트럼
  - No phase correction
- 추가 line broadening, P0/P1 미세조정, 양 끝 직선 baseline, 개별 spectrum 정규화
- 여러 ZIP과 여러 experiment overlay, 개별 표시/숨김·이름·색상, vertical offset, peak 표시
- experiment, nucleus, pulse program, title, scans, MAS rate, spectral width, saved LB 및 group delay 확인
- ZIP에 13C가 있으면 탄소 스펙트럼을 기본 표시하고 1H calibration 데이터는 목록에만 보존
- `ser` 기반 pseudo-2D/2D experiment는 현재 1D 탭에서 제외하고 import 결과에 사유 표시

제공된 `20260216_25mm_PDA.zip`에는 processed `1r` 파일이 없으므로 raw FID에서 spectrum을 다시 계산합니다. Experiment 3의 13C CP와 experiment 4의 13C multiCP는 기본 표시되고, experiment 1의 1H one-pulse는 숨김 상태로 import되며 experiment 2의 saturation-recovery pseudo-2D `ser`는 제외됩니다. Raw 재처리 결과는 저장된 TopSpin 처리 파라미터와 자동 위상 보정을 사용하지만, 논문용 최종 정량/위상 결과는 원래 TopSpin 처리 결과와 함께 확인하는 것이 좋습니다.

### ZetaSizer particle library

- 여러 sheet에서 DLS와 zeta-potential raw distribution 자동 구분
- A:B, C:D, E:F를 measurement 1–3으로 연결
- sheet 이름의 `Cell_N` 정보를 metadata로 저장
- particle 이름별로 DLS/Zeta triplicate를 로컬 SQLite library에 저장
- DLS와 zeta-potential 그래프를 좌우에 동시에 표시
- 여러 particle을 선택해 두 그래프에서 다음 방식으로 비교
  - Mean ± SD
  - Mean + replicate curves
  - Replicates only
- DLS log-X 토글
- 확대된 행 높이, 가로/세로 스크롤, 드래그 가능한 패널 구분선
- 이름·업데이트 시각·DLS/Zeta 측정 수·검수된 OCR 수·원본별 정렬 및 기본 정렬 복원
- 선택한 particle과 연결된 모든 측정값을 확인 후 library에서 삭제
- 각 replicate에 대응하는 embedded measurement-result table을 원본 픽셀, 창 맞춤, 50–300% 확대 및 스크롤로 열람
- 현재 measurement의 표 이미지를 로컬 RapidOCR로 읽어 `DLS_OCR`/`Zeta_OCR` 검수 탭 생성
- 검수 탭에서 원본 이미지를 왼쪽, 편집 가능한 OCR 표를 오른쪽에 나란히 표시
- OCR이 놓친 행을 추가하거나 마지막 행을 제거하고 모든 셀을 직접 수정 가능
- 사용자가 원본과 대조했다는 확인을 거친 결과만 particle library에 별도로 저장

OCR 결과는 편집을 돕는 초안입니다. 소수점·음수 부호·단위가 잘못 인식될 수 있으므로 저장 전에 반드시 왼쪽 원본 이미지와 대조해야 합니다. OCR은 외부 서버를 사용하지 않으며, 저장 전에는 라이브러리 데이터가 변경되지 않습니다. 이미지와 raw curve의 replicate 연결도 그대로 보존됩니다.

### 그래프와 custom format

- bottom/left major tick은 안쪽 방향
- top/right는 border line만 표시하고 tick은 표시하지 않음
- 모든 데이터 탭에서 이동 가능한 비모달 `Graph settings…` 창 사용
- `Lines and shapes…`는 그래프 바로 위에 항상 표시되며 별도 비모달 창으로 열림
- 그래프 설정에서 현재 데이터 탭의 기본 표시값으로 즉시 복원
- 실시간 미리보기 토글: 켜면 옵션 변경 즉시 반영, 끄면 `Apply`를 누를 때 반영
- X축 제목, Y축 제목, tick label, legend의 글꼴·크기·굵기·색상을 서로 독립적으로 조절
- curve/tick/frame 굵기, tick 길이, axis name/unit/range/spacing, X축 반전, legend 조절
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

## 0.3.0 이후 패치 업데이트

0.3.0은 한 번 새 폴더에 설치해야 합니다. 이후 일반적인 기능 추가와 UI 수정은 전체 폴더를 다시 받지 않고, 전달받은 `.labpatch` 파일만 적용할 수 있습니다.

이 패치 방식은 `run_labplotter.bat`로 실행하는 표준 설치본용입니다. 선택적으로 직접 만든 PyInstaller EXE 배포본은 실행 파일의 묶음 구조가 달라 별도의 전체 빌드로 갱신합니다.

1. LabPlotter 오른쪽 위의 `Updates…`를 누릅니다.
2. `Apply .labpatch…`에서 전달받은 패치 파일을 선택합니다.
3. 앱이 닫힌 뒤 설치 버전과 기존/신규 파일의 SHA-256을 검사합니다.
4. 변경 대상 파일을 `.updates\backups`에 백업한 다음 패치를 적용하고 실행 가능 여부를 검사합니다.
5. 성공하면 새 버전으로 자동 재실행됩니다. 실패하면 기존 버전을 자동 복원합니다.

`.labpatch`는 직접 압축 해제하지 않습니다. 패치는 지정된 LabPlotter 파일만 바꿀 수 있으며 측정 원본, particle library, custom format profile은 건드리지 않습니다. Python dependency가 바뀐 패치만 기존 `.venv`에 필요한 package를 추가/갱신하며, 변경 전 package 버전 목록도 롤백용으로 보존합니다. DB 구조 변경이 선언된 패치는 적용 전에 particle library도 함께 백업합니다.

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
- `format_profiles.json`: custom Excel format mappings

같은 workbook을 다시 import하면 같은 particle/measurement 항목을 업데이트하므로 중복이 누적되지 않습니다.

## 과학적 처리 관련 주의

- Baseline correction은 원자료를 덮어쓰지 않습니다. 토글을 끄면 즉시 raw spectrum으로 돌아갑니다.
- Baseline과 normalization은 화면 표시 및 export에만 적용됩니다.
- 자동 peak marking은 후보 위치를 찾는 보조 기능입니다. 작용기 assignment를 확정하지 않습니다.
- 서로 다른 X grid의 ZetaSizer triplicate는 공통 overlap 범위에 interpolation한 뒤 평균과 표준편차를 계산합니다.
