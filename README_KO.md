# LabPlotter 0.10.8

## 0.10.9: 새 모델2와 간결한 H NMR 결과표

- **Decomposition 또는 Quantitative analysis → model Ver2**를 선택하면 ANP 보고서의 `broad_core3` 모델을 사용합니다. 기존 **model Ver1이 기본값**입니다. 0.10.7–0.10.8에서 저장한 모델2는 `Legacy core template`이라는 이름으로 그대로 열립니다.
- 새 모델2는 **aliphatic / aromatic / 넓은 미배정 성분**과 각 위성 피크를 분리합니다. 실제부·허수부를 함께 사용하여 PH0/PH1과 복소 선형 배경을 적합합니다. 각 ±위성 높이는 독립적이며, 미배정 면적을 aliphatic 또는 aromatic에 넣지 않습니다. 기본 중심 범위는 −0.5–3.5 / 5.5–9 / 2–9 ppm, FWHM 범위는 0.3–15 / 0.3–15 / 14–50 ppm입니다.
- 기본 복소 fitting 범위는 −170–180 ppm, 성분 적분 범위는 −145–155 ppm입니다. 실제 공통 데이터 범위 안에서만 적합하며, 20 kHz / 400 MHz에서 위성 간격은 50 ppm입니다. PH0 ±30°, PH1 ±180°의 경계는 수정할 수 있습니다. phase/baseline을 끄면 해당 보정도 꺼지고, 수동 phase는 고정됩니다. 허수 데이터가 없거나 smoothing을 적용했다면 현재 처리된 실제부로 분해하고 이를 기록합니다.
- **Quantitative analysis → Aromatic correction**: `On — aromatic reference`는 기존 aromatic 정규화 계산, `Off — entered masses`는 입력한 두 시료 질량을 반영한 core aliphatic 차감입니다. 기존 저장 설정과 기본 On 설정을 유지합니다. Off에서 알려진 core 질량이 비어 있으면 시료 전체 질량을 core 질량 근사로 사용합니다.
- 그래프 아래에는 **Sample / Aromatic / Aliphatic / Ligand coverage**만 표시합니다. `Area display`에서 **µmol H/mg ↔ Raw integral (intensity·ppm)**을 전환할 수 있습니다. µmol H/mg 열은 aromatic 정규화 **전**의 시료 값입니다. coverage만 선택한 보정법을 반영합니다. 분석하지 않은 행은 빈값으로 표시됩니다.
- coverage 범위는 기존 Schiff/Michael H-count 가정의 두 경계입니다. 기본 C–H 기반 단일 추정값과 양쪽 경계, 미배정 면적, 정규화 인자, 각 위성 면적, 모든 가정과 경고는 **More info**에 있습니다. 음수 또는 100% 초과를 숨기거나 0–100%로 자르지 않습니다. 숫자 드래그 복사와 표 전체 복사를 지원합니다.
- 실제 ANP 5종의 보고서 적분값 재현 오차는 0.001% 미만입니다. 이는 구현 일치 확인이며, 분해의 화학적 유일성이나 coverage 정확도를 확정하지 않습니다. 특히 Plus/Arg의 phase 경계 도달과 미배정 성분의 불확실성은 추가 정보에 남깁니다.
- 누적 `.labpatch`는 **0.10.0 또는 0.10.8에서 0.10.9로 바로 적용**할 수 있습니다. 프로그램의 업데이트 패치 적용 메뉴에서 파일을 선택합니다. 라이브러리와 개인 파라미터는 초기화하지 않으며, 기존 코드 백업과 원복 기능을 유지합니다.

아래 0.10.7–0.10.8 설명의 ‘Ver2 core template’은 이제 **Legacy core template**을 의미합니다.

FTIR, NanoDrop UV–Vis, ssNMR, ZetaSizer, Lab DLS 및 TEM TIFF 데이터를 플롯하고 비교·분석하는 Windows 데스크톱 및 웹 앱입니다. 데스크톱의 측정 파일과 particle library는 외부 서버로 전송되지 않습니다.

## 0.10.8 Ver2 정량 계산 오류 수정

- `Confirm parameters and calculate`에서 발생하던 **`'float' object cannot be interpreted as an integer`** 오류를 수정했습니다. 입력창의 위성 차수 `2`가 `2.0`으로 전달될 때, Ver2에서 검증된 정수 값을 유지하지 못한 문제였습니다.
- ANP 자신의 blank 검사, 수정 시료, 공통 전처리 적용/미적용, 저장된 설정과 batch 계산 경로에 적용됩니다. 2.5 같은 소수 차수는 정수로 반올림하지 않고 올바른 입력을 요구합니다. 기존 피팅 조건·질량·H 수·coverage 식은 유지합니다.
- **`LabPlotter_Any_to_0.10.8.labpatch`를 적용하고 재시작한 뒤 같은 조건으로 다시 계산**하세요. 원본을 다시 export하거나 파라미터를 바꿀 필요가 없습니다. 0.10.7 및 이전 0.10.x에서 누적 적용할 수 있고 개인 라이브러리는 초기화하지 않습니다.
- 이번 회귀 검증은 화면 없이도 실제 데스크톱 입력값 변환을 실행하여 정수/소수 자료형 문제가 재발하는지 확인합니다. Windows 창의 시각적 배치는 별도 검증 대상입니다.

## 0.10.7 H NMR 모델 선택 / 결합 방식별 coverage 범위

**적용:** `LabPlotter_Any_to_0.10.7.labpatch`를 앱 패치 메뉴 또는 `apply_update.bat`로 적용하고 재시작합니다. 이전 0.10.x에서 누적 적용할 수 있으며 개인 라이브러리는 초기화하지 않습니다. 저장된 결과는 자동 재계산하지 않습니다.

1. 수정 시료와 해당 pristine **PDA 또는 ANP**를 불러오고 **Preprocessing**에서 함께 공통 조건을 적용합니다. intensity 정규화는 하지 않습니다.
2. **Decomposition… → Decomposition model** 또는 **Quantitative analysis → Sample and core → Decomposition model**에서 **model Ver1 / model Ver2**를 선택합니다. 새 데이터와 기존 모델 기록의 기본값은 **Ver1**입니다. 선택한 모델은 데이터별로 저장되며 라이브러리에서 복원됩니다.
3. **Ver1**은 기존 aliphatic/aromatic envelope와 위성 피크를 분해합니다. 기존 aromatic-reference 정량식과 명목 coverage를 유지합니다. **Ver2**는 `시료 = a × 실측 pristine core + 추가 ligand 성분 [+ 미배정 성분]`을 피팅합니다. Ver2 reference에서 해당 pristine 데이터를 선택하세요. core 전체를 aromatic이라고 재명명하지 않습니다.
4. Ver2 기본 추가 성분 중심은 **−0.5~3 ppm**, FWHM **0.3~15 ppm**, core shift **±0.3 ppm**, 추가 core broadening **0**입니다. 모두 편집 가능하며 core 쪽은 측정된 모양을 사용합니다. Ver2에서는 `Additional ligand G fraction`으로 추가 ligand 성분의 G 비율을 설정하며 aromatic G 값은 사용하지 않습니다. 기본 넓은 데이터 조건은 기존과 같은 **400 MHz / 20 kHz, 50 ppm 간격, 양쪽 2차 위성**, 피팅 범위 −145~155 ppm입니다. fit 범위와 허용 shift 전체를 덮는 reference 데이터가 필요합니다.
5. **Fit and preview → Apply decomposition** 후 **Quantitative analysis**에서 질량·표준·H 수·최대 loading을 확인하고 계산합니다. Ver2 `core_reference`는 `loading = (추가 ligand 면적/a) × reference response × (표준 μmol H/표준 면적) / (H 수 × reference 질량)`입니다. `coverage = loading / 최대 loading × 100`입니다. 시료 질량은 이 coverage 식에서 소거되고 **reference 질량은 남습니다**. `mass` 모드는 독립적으로 아는 core 질량으로 a를 고정합니다. a 자체를 측정 질량비로 취급하지 않습니다.
6. 하단 표에 두 모델 모두 **Schiff coverage, Michael coverage, coverage lower/upper**, 실제 사용한 두 H 수를 표시합니다. **Michael scenario includes one linkage N-H (if captured)**이 기본 켜짐이므로 C6는 **13/14**, C18은 **37/38**입니다. 끄면 C–H만 적분한다는 가정으로 두 H 수와 경계가 같아집니다. **Schiff/Michael H override**를 입력하면 해당 값을 우선 적용합니다. 개별 설정은 spectrum library, 공통 리간드 기본값은 parameter library에 저장합니다. Lys의 미확정 H 수는 임의로 채우지 않습니다.

H 수 비교는 **중성·단일 결합 primary amine**에 대한 구조적 가정입니다. alkyl C–H는 Schiff와 Michael에서 같고 차이는 연결 N–H(0/1)가 실제 적분에 잡히는지입니다. N–H 교환·protonation·다중 결합·core H 변화는 이 두 경계로 자동 설명되지 않습니다. 따라서 표시 범위는 **H 수 가정별 시나리오 범위**이며 신뢰구간이나 실제 반응 비율이 아닙니다. 반응 경로의 근거와 한계는 [Yang et al., PLOS One 2016](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0166490)의 catechol/primary amine 연구를 참고했습니다. 현재 ANP/PDA의 실제 결합 경로를 확인한 것으로 간주하지 않습니다.

두 모델 모두 component/sum/residual overlay, 색·굵기·선 모양·면적 음영, 현재 화면 이미지/클립보드, CSV, 계산 상세 기록, batch, library, model/phase sensitivity를 사용합니다. Ver2는 template snapshot과 reference 식별/처리 정보를 저장하므로 수정 시료 하나만 재불러와도 저장된 곡선을 그릴 수 있습니다. **새 재계산/위상 민감도 검토에는 원본 pristine reference도 불러와야 합니다.** Phase sensitivity는 시료/reference PH0를 독립적으로 바꾸는 9가지 조합이며 현재 저장 결과는 바꾸지 않습니다.

Ver2의 추가 신호가 전부 결합 ligand라는 가정과 core 신호/mg 불변 가정은 검증 대상입니다. 미결합 ligand, core 변화, OH/물/background도 추가 신호에 기여할 수 있습니다. 양의 추가 면적, 높은 R² 또는 pristine 자신을 뺀 0%만으로 grafting이 검증되지는 않습니다. bounds·위성 local residual·전처리 간격 불일치 등 검토 항목을 유지하면서 잠정 수치는 계속 표시합니다.

## 0.10.6 C / H NMR 가져오기 수정

- 이전에는 C NMR 탭의 `Import ASCII TXT…`에 복소수 H NMR 파일을 넣으면 `At least three numeric four-column data rows are required` 오류가 발생했습니다. 파일 손상이 아니라 서로 다른 가져오기 경로의 문제입니다. 0.10.5에서도 **ssNMR → H NMR → Import H NMR ASCII...**로 해당 파일을 가져올 수 있습니다.
- 이제 **C / H 어느 탭의 가져오기 버튼을 눌러도** `LEFT / RIGHT / SIZE` 복소수 export, `ppm real imag` 표, 기존 4열 ASCII 형식을 구분하여 해당 탭에 추가하고 그 탭을 표시합니다. 파일명으로 C/H를 추측하지 않습니다. 서로 다른 형식의 파일을 함께 선택해도 각각 분리합니다.
- 일부 파일에 문제가 있어도 정상 파일은 가져오며 오류 파일은 한 번에 안내합니다. 실제 데이터 수와 SIZE가 다른 경우에는 해당 오류를 그대로 보여줍니다.
- 0.10.5의 위상/베이스라인 보정, 분해, 정량식, 저장 데이터와 그래프 설정은 유지합니다.

**적용:** `LabPlotter_Any_to_0.10.6.labpatch`를 앱 패치 메뉴 또는 `apply_update.bat`로 적용하고 재시작합니다. 0.10.5에 바로 적용할 수 있으며 개인 라이브러리는 초기화하지 않습니다.

## 0.10.5 aromatic 기준 coverage / 결과 복사

- 계산 기본값은 사용자가 제시한 **aromatic 정규화 → pristine core의 aliphatic 차감**입니다. Quantitative analysis → Sample and core → `aromatic_reference`가 기본이며, 비교용 `mass` 방식도 선택할 수 있습니다. 전처리/분해 그래프의 intensity는 바꾸지 않고 정량 계산 단계에만 정규화를 적용합니다.
- **표준 42565812.55 intensity×ppm = 1.861273386 μmol H**를 기본 가정으로 사용합니다. 입력창/라이브러리/CSV/계산 기록도 μmol로 통일했습니다. C6=13 H입니다. ANP 기본 질량은 38.38 mg, ANP-DMEN(+)는 55.18 mg으로 갱신했으며 나머지는 같습니다. 질량·표준량은 파라미터 라이브러리나 계산 확인창에서 바꿀 수 있습니다.
- 기존 파일의 정확히 일치하는 **미검증 표준 기본값**은 새 μmol 해석으로 이동합니다. 사용자 지정/검증된 mmol 값은 물리량을 유지하도록 ×1000하여 μmol로 변환합니다. 이전 ANP 기본 질량과 정확히 일치할 때만 새 기본 질량을 적용하고 임의로 수정한 값은 유지합니다. 오래된 계산 기록은 재계산 전까지 새로운 결과로 간주하지 않습니다.
- 하단 결과표의 **Value를 클릭한 뒤 드래그**하여 텍스트를 선택하고 Ctrl+C로 복사합니다. **Copy value / Copy results table**도 지원합니다. 전체 표는 탭 구분으로 복사되어 Excel에 붙여넣을 수 있습니다. 읽기 전용이므로 선택 중 원래 결과는 수정되지 않습니다.
- 분해 오버레이의 **residual은 기본 끔**, **aliphatic/aromatic은 실선**입니다. Graph settings → H NMR decomposition에서 다시 켜거나 선 모양을 바꿀 수 있습니다. 이미 저장한 사용자 지정 스타일은 유지하며 해당 페이지의 기본값 복원으로 새 기본값을 적용합니다.
- Y축 위의 `1e7` 대신 **Intensity (×10⁷ a.u.)**처럼 축 제목에 배율을 표시합니다. 원본 배열/적분/축 한계는 그대로이며 `plain` 또는 `scientific` 표시도 선택할 수 있습니다. 그래프 복사와 이미지 저장에도 같은 표기를 사용합니다.
- **Model sensitivity... → Run model comparison**에서 동일한 보정 데이터에 Gaussian / Lorentzian / pseudo-Voigt / 미배정 overlap 모델을 비교합니다. 표와 원자료 감사 기록을 복사·저장할 수 있습니다. 현재 분해는 자동으로 바꾸지 않습니다. R² 개선이나 원하는 coverage만으로 모델을 선택하지 마세요. PH0 민감도는 기존 **Phase sensitivity...**에서 별도로 확인합니다.
- ANP의 넓은 aliphatic 성분이 다른 피크의 꼬리를 흡수할 가능성을 보기 위해 중심/FWHM/G 비율을 결과표에 추가했습니다. 중심 간격에 비해 매우 넓은 aliphatic 성분에는 검토 메시지를 표시합니다. 이는 과대평가의 확정 판정이 아닙니다.

위 변경은 현재 0.10.8 누적 패치에도 포함되어 있습니다. PDA/ANP pristine 기준과 수정 시료를 불러온 뒤 Quantitative analysis에서 `aromatic_reference`와 `1.861273386 umol H`를 확인하고 재계산하세요. 저장된 개별 계산값은 개별 확인창에서, 공통 기본값은 파라미터 라이브러리에서 수정합니다.

## 이전 0.10.4의 잠정 coverage와 전체 시료 계산

- **Withheld 대신 잠정 결과를 기본 표시**합니다. 입력/피팅이 계산 가능한 한 coverage, ligand umol, loading을 하단 표 맨 위에 보여줍니다. 음수·100% 초과 값도 그대로 유지합니다. 미확인 체크를 자동으로 승인하거나 값을 0~100%로 자르지 않습니다.
- 0.10.4의 표준량은 mmol로 해석했지만 **현재 0.10.5의 제공 기본값은 위의 μmol 해석으로 대체**되었습니다. 시료·pristine 기준의 표준 대비 응답 배율은 각각 **1**로 시작하며 Quantitative analysis → Calibration에서 수정할 수 있습니다.
- **Calculate all (provisional)... → Confirm and calculate all**: 로드된 시료마다 맞는 pristine PDA/ANP와 질량·리간드 프리셋을 확인한 뒤 일괄 계산합니다. 결과 CSV에는 단위·응답 배율·H 수·최대 loading·모든 파라미터·미해결 항목도 들어갑니다. 같은 pristine 시료·질량·응답의 self-reference는 0입니다. 이름을 통해 기준을 선택하지만 피팅 목적함수에 시료명이나 기대 순서는 넣지 않습니다.
- 개별 **Quantitative analysis...**도 같은 방식입니다. **Calibration → Show provisional coverage despite unresolved checks**를 끄면 이전의 검토 완료 항목만 표시하는 모드입니다. 네 검증 체크는 실제 확인 전까지 미확인으로 유지하세요. 수치가 정의되지 않는 경우(표준 0, 질량/H 수 미입력, 기준 스펙트럼 없음)는 원인을 표시하며 만들어내지 않습니다. 기존 제공 10개 시료는 모두 계산에 필요한 기본 숫자가 있습니다. Lys는 이전처럼 MW만 있고 H 수·질량을 입력해야 합니다.
- **Refine phase / baseline**: 큰 중앙 신호가 약한 위성 신호의 위상 오류를 가리지 않도록 검출된 ±1/±2 envelope의 국소 음수 에너지를 추가 고려합니다. 전역 PH0 ±5°, PH1 ±60° 이내에서 기존 해를 개선하는 후보만 검토하고 중앙 envelope 면적 변화 ±10%/음수 증가 조건을 확인합니다. 이는 개발한 경험적 보정안이며 DMfit/TopSpin의 알고리즘을 복제한 것이 아닙니다. 좌우 같은 높이, 개별 peak별 위상 회전, 절댓값 변환, 음수 잘라내기는 사용하지 않습니다.
- 새 넓은 H NMR import는 위성 보정 검토를 기본 시도합니다. Preprocessing의 **Refine phase using resolved sidebands**로 끌 수 있습니다. 개선이 작거나 noise 수준의 약한 peak만 있으면 기존 PH0/PH1을 유지합니다. 각 후보·채택 여부는 **Phase / baseline QC → complete QC record**에 보존됩니다. 기존 라이브러리의 저장 위상은 유지되므로 원할 때 재보정 버튼을 사용하세요. 수동 위상 override는 자동으로 덮어쓰지 않습니다.
- 함께 전처리한 그룹에서 재보정하면 현재 로드된 같은 그룹을 함께 갱신하고 오래된 분해/정량 결과를 지웁니다. 계산 후 **Save to library**로 수정한 조건을 저장하세요. 그래프 레이어/색/굵기, copy/export 및 C NMR/DLS 기능은 그대로 지원합니다.

**패치 적용:** `LabPlotter_Any_to_0.10.4.labpatch`를 앱 패치 메뉴 또는 `apply_update.bat`로 적용하고 재시작합니다. 0.10.0~0.10.3에서 누적 적용할 수 있고 개인 라이브러리를 초기화하지 않습니다.

현재 복소 ASCII만으로 보정 후보는 시험할 수 있습니다. 남는 음수 성분이 위상·baseline, pulse/dead-time, background 중 무엇 때문인지 분리하려면 원래 Bruker FID와 `acqus`/`procs`(pulse program, pulse length, delays, NS/RG, scaling 포함)가 도움이 됩니다. 수치 표시를 위해 이를 먼저 요구하지는 않습니다.

근거: [Bruker phase/baseline correction 기술자료](https://www.bruker.com/pt/products-and-solutions/mr/nmr-software/topspin/_jcr_content/root/sections/more_information/sectionpar/linklist/contentpar-1/calltoaction.download-asset.pdf/links/item0/BS-100119_improving_phase_and_baseline_correction.pdf)는 동시 위상/기저선 개선과 solid-state/negative-peak 처리를 설명합니다. [Ravera 2021](https://doi.org/10.1016/j.jmro.2021.100022)은 넓은 paramagnetic 스펙트럼에서 finite pulse와 dead time에 의한 위상/기저선 왜곡 및 magnitude 처리의 정량 한계를 보여줍니다. 후자는 현재 시료의 원인 진단이 아니라 보정의 한계에 대한 참고입니다.

## 0.10.3의 분해·그래프 기능

- 새로 가져오는 넓은 H NMR의 **편집 가능한 랩 설정은 400.0 MHz / 20,000 Hz**, 따라서 sideband 간격은 **50 ppm**입니다. ASCII에서 읽은 장비 메타데이터가 아니며 실제 측정값이 다르면 바꿔야 합니다. 둘 다 0이면 기존 데이터 기반 간격 추정을 사용합니다. ppm 축 자체를 늘이거나 이동하지 않습니다.
- 기존 라이브러리 항목: **Preprocessing → Get preprocessing condition → 400 MHz / 20 kHz preset → Apply**, 이어서 **Decompose spectrum → MAS sideband defaults → Fit and preview → Apply**. 사용자 지정 위상값과 이전 설정은 자동 삭제되지 않습니다. 위상을 다시 자동으로 찾으려면 Phase override에서 두 값을 비웁니다.
- DMfit `ss band`처럼 각 sideband의 **폭과 G/L을 해당 중앙 peak에 연결**하는 것이 기본입니다. 각 family의 G fraction을 고정할 수 있으며 `0=Lorentzian, 1=Gaussian, 빈칸=최적화`입니다. 고정 G는 pseudo_voigt MAS 모델에서 사용합니다. 위상이나 예상 시료 순서를 이용해 강제로 적분값을 맞추지 않습니다.
- **Component integrals...**에서 중앙/±1/±2 등의 면적, 중심, 폭, G 비율, 합계를 봅니다. Finite area는 실제 fit 범위 적분, Full-profile area는 무한 꼬리까지 외삽한 비교값입니다. 표준과의 단위·배율 일치가 확인되지 않으면 절대 적분값을 직접 비교하면 안 됩니다.
- **Signed satellite heights**는 작은 음수 피팅을 살펴보는 진단 옵션입니다. 음수 면적을 양수나 0으로 숨기지 않으며, 음수 성분이 있으면 경고하며, 검토 완료 모드에서는 coverage를 보류합니다. 약한 peak를 좌우 복제하지 않습니다.
- **Phase sensitivity...**는 선택한 시료와 pristine 기준에 PH0 ±2°(변경 가능)를 독립 적용하고 PH1을 고정한 채 baseline과 분해를 다시 계산합니다. 질량·응답 배율을 확인합니다. aliphatic/mg 및 신호 분율의 범위가 겹치면 순서가 위상에 민감한 것으로 표시합니다. 이 범위는 통계적 신뢰구간이 아닙니다. 현재 보정/분해/원본은 바꾸지 않습니다.
- coverage 보류 문구를 짧게 표시해 **하단 적분 결과표가 가려지지 않도록** 수정했습니다. 전체 사유는 Calculation details에서 확인합니다. 중심/폭 경계, 강한 상관 또는 비슷한 잔차의 서로 다른 해가 있으면 모호한 분해를 별도로 표시합니다. 0.10.4 기본 모드에서는 잠정 수치도 표시합니다.

400 MHz / 20 kHz와 측정 envelope 간격이 잘 맞지 않거나 외곽 satellite 잔차가 크면 실제 acquisition 조건, ppm 기준, 위상/baseline과 모델을 재확인해야 합니다. 높은 전체 R²나 기대한 PDA-C6 > PDA 순서만으로 올바른 분해를 증명하지 않습니다. DMfit 결과를 정확히 재현하려면 적분표뿐 아니라 peak별 중심·폭·G/L·고정 여부와 위상값이 필요합니다.

## H NMR: MAS sideband 포함 분해·적분

이번 satellite 모델은 **MAS spinning sideband**입니다. aliphatic/aromatic 각각의 피크 위치를 `delta_family + n × spacing`으로 연결합니다. 실제 측정의 MAS 속도(Hz)와 **1H** 주파수(MHz)를 모두 입력하면 `spacing(ppm) = Hz / MHz`로 고정합니다. 둘 다 0이면 데이터에서 추정·피팅하며, 측정 조건이 확인된 것으로 간주하지 않습니다. 13C 측정 조건을 H NMR에 자동 대입하지 않습니다.

- 넓은 MAS 데이터는 기본 **-200~210 ppm 안의 측정된 공통 범위**에서 전처리합니다. 분해/적분은 **-145~155 ppm**, **±1·±2차**부터 시작하며 최대 ±4차까지 선택할 수 있습니다. 차수를 늘리면 전처리/fit 범위도 늘려야 합니다. 좁은 데이터와 이전 저장 설정은 유지합니다.
- 제한된 자동 **PH0/PH1**을 사용합니다. PH1이 탐색 상한 근처에 도달하면 0차 보정으로 돌아가고 경고합니다. **Phase override...**의 PH0/PH1과 기준 pivot/span은 저장되므로 전처리 범위 변경 후에도 같은 위상 기울기를 유지합니다. PH1은 현재 전처리 폭 전체에 걸친 각도이며 장비의 PHC1과 그대로 동일한 숫자라고 가정하면 안 됩니다.
- baseline은 중심 4.5 ppm에서 기본 145 ppm 이상 떨어진 바깥 후보를 사용하고 주기적인 피크 영역을 제외합니다. 기본 robust linear이며 0~2차를 선택할 수 있습니다. 실제 신호가 앵커에 포함되면 제외 폭/거리/차수를 조절해야 합니다. 자동 보정은 검토할 제안입니다.
- **Phase / baseline QC...**에서 원래 실수, 위상 보정 후, baseline 제거 후, 뺀 baseline을 비교합니다. 차수별 검출 상태·peak ppm·prominence/noise·음의 신호 비율을 표시합니다. **Main peak / Full sidebands**는 표시 범위만 바꾸며 재정규화하지 않습니다.
- **Decompose spectrum... → MAS sideband defaults**는 새 모델의 시작값을 불러옵니다. 이전 라이브러리의 좁은 전처리는 **Preprocessing → Get preprocessing condition → Apply**로 다시 준비해야 넓은 fit이 가능합니다. 저장된 모델을 조용히 덮어쓰지 않습니다.
- 중심·폭·Gaussian/Lorentzian 혼합률을 sideband에 연결하되 **좌우 높이는 독립 변수**입니다. 폭 배율 1 + `Fit common sideband-width multiplier` 끔은 DMfit ssb의 동일 폭 연결입니다. 0.10.3 기본은 끔입니다. 켜면 공통 폭 배율을 추가 피팅하는 경험적 확장입니다. CSA/dipolar 물리 시뮬레이션이나 DMfit 파일 호환 기능은 아닙니다.
- 각 가족의 곡선/면적은 중심과 선택한 모든 차수의 합입니다. `중심 면적 × 5`로 대신하지 않습니다. 결과에 중심/sideband/총면적, CSV에 차수별 곡선, 계산 기록에 차수별 면적·위치·폭·검출 상태를 제공합니다. 적분은 유한 측정 범위 안의 겹치는 꼬리까지 포함하며 정량에 누락된 무한 꼬리를 외삽하지 않습니다. 별도의 full-profile 면적 열은 DMfit 비교를 위한 무한 꼬리 외삽값입니다.
- 약한 ±2차를 복제하거나 강제로 0으로 만들지 않습니다. **검출된 envelope**와 **모델로 추정한 성분**을 구분합니다. 기본 SNR 5 및 중앙 높이 대비 prominence 하한은 검출 진단 기준이며 화학적 배정의 증명은 아닙니다. 검출된 sideband의 RMSE/피크 높이 >25%처럼 전체 R²에 가려진 문제도 검사합니다.
- 표준 `42565812.55 = 1.861273386 mmol H`는 **모든 sideband 포함**으로 기록하고 숫자/단위를 바꾸지 않습니다. 시료·표준의 포함 여부가 다르면 경고하며, 검토 완료 모드에서 coverage를 보류합니다. 포함 차수·약한 피크·위상/baseline 검토란도 추가됩니다. 표준 단위/응답, 정량 측정, 성분 배정 검증은 여전히 필요합니다. 확인란이 측정이나 화학적 배정을 증명하지는 않습니다.

공식 근거: [DMfit linked ssb](https://nmr.cemhti.cnrs-orleans.fr/Dmfit/Howto/1D_ssb.aspx), [DMfit models](https://nmr.cemhti.cnrs-orleans.fr/Dmfit/help/Models/Default.aspx), [CSA MAS tutorial](https://nmr.cemhti.cnrs-orleans.fr/dmfit/Howto/CSA/CSA_MAS.aspx), [위상/baseline·모델 불일치의 정량 영향](https://mr.copernicus.org/articles/1/141/2020/). 좌우 높이를 강제로 같게 만드는 대신 위치 간격·흡수형 모양·음의 로브·잔차를 함께 봅니다.

**현재 업데이트:** `LabPlotter_Any_to_0.10.8.labpatch`를 앱의 패치 적용 메뉴 또는 `apply_update.bat`로 적용하고 재시작하세요. 이전 0.10.x 버전에서 누적 적용할 수 있습니다. 개인 데이터/라이브러리는 유지하고 실패 시 updater rollback을 사용할 수 있습니다. 기존 라이브러리의 저장 조건은 자동으로 바꾸지 않으므로 아래 새 설정 적용 순서를 확인하세요.

### 공통 분해·정량 기능

ssNMR 안의 **C NMR / H NMR**에서 선택합니다. 기존 C NMR 기능은 유지됩니다. 0.10.0 기본 계산은 분해 전 고정 영역을 직접 적분했습니다. 현재는 분해 성분의 전체 적분을 이용하고, 정량 단계에서 선택한 aromatic 정규화 또는 질량 기준 차감을 수행합니다. 0.10.0의 약 10,000% 결과는 검증된 표면 coverage가 아닙니다.

1. **Import H NMR ASCII...**에서 `LEFT / RIGHT / SIZE` 헤더와 `실수+허수i` 값이 있는 TopSpin TXT/ASC 또는 `ppm real imag` 표를 가져옵니다. 원본 복소수는 유지합니다. 위상/베이스라인 체크박스와 **Phase override...**로 보정을 확인합니다.
2. **Preprocessing...**에서 수정 시료와 대응하는 미변형 PDA/ANP를 함께 준비합니다. 첨부 파일은 위의 넓은 MAS 조건과 약 0.0381753723 ppm grid로 시작합니다. 좁은 파일의 기본값은 -40~50 ppm 안의 공통 범위·0차 위상·edge baseline입니다. 최대값/면적 normalization을 하지 않습니다. 정렬 및 broadening은 기본 끔입니다. 자동 위상과 baseline 후보가 올바른지 직접 확인해야 합니다.
3. **Decompose spectrum... → Fit and preview**로 실제 분해를 수행합니다. 원본(보정된 실수 스펙트럼), aliphatic 성분, aromatic 성분, 합산 fit, 잔차(data − fit)를 비교합니다. **Apply decomposition to spectrum**으로 메인 그래프에 적용합니다. 변경한 조건은 다시 피팅해야 적용됩니다.
4. 분해 기본 모델은 **pseudo-Voigt**(동일 중심·FWHM의 Gaussian/Lorentzian 혼합)이며 Gaussian, Lorentzian으로 바꿀 수 있습니다. 초기 **피크 중심 제약**은 aliphatic 0~4.5 ppm, aromatic 5.5~9 ppm입니다. 이는 주신 넓은 스펙트럼을 분해하기 위한 조정 가능한 가정으로, 해당 범위만 잘라 적분한다는 의미가 아닙니다. 예시 스크린샷의 9 ppm 피크 위치를 가져온 것이 아닙니다.
5. **fit/성분 적분 범위**는 MAS 모드에서 -145~155 ppm, 중앙 피크 모드에서 -20~25 ppm입니다. 이 전체 범위 안에서 각 분해 성분의 겹치는 꼬리까지 **해석적으로 적분**합니다. 측정되지 않은 범위로 외삽하지 않습니다. 전처리 범위를 줄였다면 fit 범위도 조절해야 합니다. 피크 중심/FWHM 범위와 모델은 변경할 수 있고, 두 중심 범위 사이에 **unassigned overlap** 성분을 추가할 수 있습니다. 이 성분은 리간드 면적에서 제외합니다.
6. **Quantitative analysis...**에서 pristine 기준, core/리간드/질량/검량계수와 분해 조건을 확인한 뒤 계산합니다. 시료와 기준은 같은 분해 모델을 사용합니다. 공통 전처리 체크가 켜졌으면 동일 준비 그룹이어야 하며, 꺼졌으면 현재 시료의 보정 토글을 반영한 공통 기본 조건으로 둘 다 다시 처리합니다.
7. 그래프 아래에 분해 성분별 적분, aliphatic/aromatic 비, aliphatic 수소 신호 분율, fit R²/RMSE 및 정량 결과를 표시합니다. **신호 분율은 surface coverage가 아닙니다.** 단순 ppm-window 적분도 진단 항목으로만 제공하며 정량에는 쓰지 않습니다. **Calculation details... / Export processed CSV...**에서 모든 입력값, 공식, 피팅 중심·폭·혼합률, 면적 범위, 기준 스펙트럼 fit, 잔차를 검증할 수 있습니다.
8. **Show decomposition**으로 분해 주석을 끄고 켭니다. **그래프 설정 → Curve colors**에서 개별 색상을, **H NMR decomposition**에서 개별 선 굵기·모양·표시 여부·면적 음영을 조절합니다. 굵기를 비우면 공통 굵기를 따릅니다. 클립보드와 PNG/SVG/PDF는 현재 보이는 분해 주석을 포함합니다. 그래프 비율·범례 등 공통 기능도 유지합니다.
9. **Save to library**는 원본/보정/분해 조건과 피팅 기록, 색상·스타일을 함께 저장합니다. 저장된 분해는 처리 데이터 해시가 일치할 때만 다시 표시합니다. phase/baseline/grid 변경 시 오래된 분해/정량을 지웁니다. 라이브러리는 불러오기·순서 변경·이름 변경·삭제·JSON 이동을 지원합니다. 표의 행 높이는 글꼴 높이+여백을 사용합니다.

### 정량식과 필요한 확인

분해된 aliphatic에는 리간드뿐 아니라 PDA/ANP 고유의 수소도 포함됩니다. 기본 `aromatic_reference`는 **core의 질량당 aromatic H가 변하지 않는다**는 가정입니다.

- `k = standard_umol_H / A_standard(intensity·ppm)`
- `ali_s = A_ali,s × response_s × k / mass_s`, `aro_s = A_aro,s × response_s × k / mass_s`
- `ali_c = A_ali,c × response_c × k / mass_c`, `aro_c = A_aro,c × response_c × k / mass_c`
- `f = aro_c / aro_s`
- `ΔH(μmol/mg) = ali_s × f − ali_c`
- `loading(μmol/mg) = ΔH / H_per_ligand`
- `coverage(%) = 100 × loading / maximum_loading(μmol/mg)`

이 계산의 loading은 pristine **reference-equivalent** 기준입니다. 수정 시료 질량은 coverage 식에서 약분되지만 pristine 기준 질량은 남습니다. `f`는 aromatic 정규화 배율이며 실측 질량비가 아닙니다. 절대 ligand-equivalent 양은 loading에 입력 시료 질량을 곱한 정규화된 값입니다. 그래프의 intensity와 원본 데이터는 정규화하지 않습니다.

선택 가능한 `mass` 방식에서는 `f=1`, `alpha = 시료 core 질량 / pristine 질량`으로 aliphatic 면적을 직접 차감합니다. core 질량이 빈칸이면 총 시료 질량을 근사 사용합니다. 해당 core 질량 입력은 `aromatic_reference`에서는 사용하지 않습니다.

C6=13, C18=37, DMEN=10, Arg=7 H는 비교환성 H에 대한 출발값이며 분해 성분이 이 H를 실제로 대표하는지 확인해야 합니다. Lys는 MW 146.19만 기본 제공하고 H 수·질량은 비웁니다. 같은 pristine의 self-reference 0%는 자기 차감 결과이며 분해 정확도의 검증이 아닙니다.

현재 표준 기본값은 **42565812.55 intensity×ppm = 1.861273386 μmol H**, 최대 loading은 PDA **0.0693**, ANP **0.1619 μmol/mg**입니다. 표준의 실제 면적 단위/처리 배율 및 시료와의 정량 응답은 파일만으로 확인되지 않으므로 잠정 가정으로 표시합니다. point sum이면 표준 자체의 원래 ppm step, Hz 적분이면 MHz를 입력합니다. 응답 배율은 별도 설정합니다.

표준 단위/배율, 정량 측정 조건, 성분 배정/H 수/core 모델, sideband 검토의 네 확인란은 실제 확인 상태를 기록합니다. 0.10.5 기본 모드는 미확인 상태나 fit 품질 경고가 있어도 **잠정 리간드 양/coverage를 표시**하고 전체 사유를 Calculation details에 남깁니다. `Show provisional coverage`를 끄면 이전의 Withheld 모드입니다. 확인란 자체가 검량을 증명하지는 않습니다. 음수/>100% 결과를 자르거나 강제 변환하지 않고, 제공한 면적을 임의로 1000배 환산하지 않습니다.

R²가 높아도 넓은 1H 신호의 분해가 유일하지는 않습니다. 특히 water/OH/NH, rotor 배경, sideband 및 core 구조 변화는 aliphatic/aromatic 가정과 겹칠 수 있습니다. 피크 중심/폭의 경계 도달, 파라미터 상관 및 초기값에 따른 면적 차이를 진단에 표시합니다. 별도 물리/화학적 근거 없이 모든 aliphatic을 공유결합 surface ligand로 해석하지 마세요. apparent coverage는 투입 리간드 대비 반응 수율과도 다릅니다.

웹도 동일 엔진의 분해·그래프·정량을 제공합니다. 웹 라이브러리는 세션 단위여서 JSON 내보내기/다시 가져오기가 필요하고, 데스크톱은 영구 로컬 저장입니다. 0.10.0에 저장된 분석 조건은 새 분해 방식과 질량 기준 방식으로 옮기되 검증 체크를 초기화합니다. 기존 C NMR/DLS 데이터베이스는 초기화하지 않습니다.

방법 참고: [BIPM qNMR](https://www.bipm.org/en/organic-analysis/qnmr), [DMfit](https://nmr.cemhti.cnrs-orleans.fr/dmfit/), [nmrglue autophase](https://nmrglue.readthedocs.io/en/latest/reference/proc_autophase.html). LabPlotter는 자체 SciPy 기반 ACME 스타일 위상 및 제한 최소제곱 피팅을 사용하며, DMfit/nmrglue 구현을 그대로 사용하는 것은 아닙니다. 용액 dopamine의 aromatic/alkyl 위치는 [Mayadevi et al., ACS Omega 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9026075/)의 참고이며, 고체 PDA의 고정 피크 배정으로 사용하지 않습니다.

## 0.9.2 곡선별 색상 설정

- 모든 탭에서 **그래프 설정 → 곡선별 색상**을 열어 각 데이터 이름 옆의 **선택…** 버튼으로 RGB 색상을 지정하거나 HEX 코드를 입력할 수 있습니다.
- **기본값**은 해당 곡선만, **기본 곡선 색상 복원**은 현재 표시 중인 곡선들을 원래 색상으로 돌립니다. **이 탭 기본값 복원**은 숨긴 곡선을 포함한 그래프 설정을 초기화합니다.
- 실시간 미리보기를 켜면 즉시 반영되며, 끈 상태에서는 **적용**을 누릅니다. 잘못된 색상 입력이나 색상 선택 취소는 기존 그래프를 바꾸지 않습니다.
- 현재 작업의 데이터 숨김·이름 변경·순서 변경, Lab DLS 평균/개별 측정 전환, ssNMR 영역 재처리 후에도 사용자가 지정한 색을 유지합니다. Lab DLS 색상은 기존과 같이 설정에 저장됩니다.
- 범례, mean R 라벨·점선, TEM 중앙값 선, FTIR 피크 라벨, ZetaSizer SD 음영이 곡선 색상을 따릅니다. 주석에 별도 색상을 지정했다면 그 설정을 유지합니다. 복사·PNG·SVG·PDF 저장에도 동일하게 반영됩니다.
- ZetaSizer의 **입자별 기본 색상**은 그룹의 기본값이며, **곡선별 색상**에서 평균·각 반복 측정·막대를 개별 지정할 수 있습니다. 개별 지정한 색상이 그룹 기본값보다 우선합니다.
- 웹 버전에서도 모든 분석 탭에 색상 선택과 기본값 복원을 지원합니다.

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
