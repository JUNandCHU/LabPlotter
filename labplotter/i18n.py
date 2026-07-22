from __future__ import annotations

import json
import re
import string
import weakref
from pathlib import Path
from typing import Callable

from .config import settings_path


KO = {
    # Main window and common actions
    "LabPlotter · local scientific data workbench": "LabPlotter · 로컬 과학 데이터 워크벤치",
    "FTIR · NanoDrop · ZetaSizer · custom formats": "FTIR · NanoDrop · ZetaSizer · 사용자 형식",
    "FTIR · NanoDrop · ssNMR · ZetaSizer · custom formats": "FTIR · NanoDrop · ssNMR · ZetaSizer · 사용자 형식",
    "Language": "언어",
    "Smart Import…": "스마트 가져오기…",
    "Updates…": "업데이트…",
    "Contact…": "연락처…",
    "ZetaSizer library": "ZetaSizer 라이브러리",
    "Custom formats": "사용자 형식",
    "Remove": "제거",
    "Color…": "색상…",
    "Source": "원본",
    "Plot": "표시",
    "Series name": "데이터 이름",
    "Rename series": "데이터 이름 변경",
    "Choose line color": "선 색상 선택",
    "All files": "모든 파일",
    "Imported": "가져오기 완료",
    "Measurement {number}": "측정 {number}",
    # Plot controls
    "Copy image": "이미지 복사",
    "Save…": "저장…",
    "Graph style · Apply updates the preview immediately": "그래프 스타일 · 적용을 누르면 미리보기에 즉시 반영됩니다",
    "X name": "X축 이름",
    "Y name": "Y축 이름",
    "unit": "단위",
    "Font": "글꼴",
    "size": "크기",
    "Line": "선 굵기",
    "Bold labels": "축 제목 굵게",
    "Legend": "범례",
    "Reverse X": "X축 반전",
    "Background": "배경",
    "White": "흰색",
    "Dark": "어두움",
    "X MIN": "X 최솟값",
    "X MAX": "X 최댓값",
    "Y MIN": "Y 최솟값",
    "Y MAX": "Y 최댓값",
    "Apply": "적용",
    "Major tick spacing": "주 눈금 간격",
    "Plot error": "그래프 오류",
    "Copied": "복사 완료",
    "A 300 dpi image is now on the clipboard.": "300 dpi 이미지가 클립보드에 복사되었습니다.",
    "Clipboard": "클립보드",
    "Save error": "저장 오류",
    "PNG image": "PNG 이미지",
    "SVG vector": "SVG 벡터",
    "PDF vector": "PDF 벡터",
    "Graph settings…": "그래프 설정…",
    "Graph settings": "그래프 설정",
    "Lines and shapes…": "선과 도형…",
    "Restore tab defaults": "이 탭 기본값 복원",
    "Copy graph": "그래프만 복사",
    "Copy + annotations": "그래프 + 주석 복사",
    "Save graph…": "그래프만 저장…",
    "Save + annotations…": "그래프 + 주석 저장…",
    "Live preview": "실시간 미리보기",
    "Axes and lines": "축과 선",
    "Fonts and colors": "글꼴과 색상",
    "Lines and shapes": "선과 도형",
    "Axis labels and units": "축 제목과 단위",
    "Unit": "단위",
    "Ranges and major ticks": "축 범위와 주 눈금",
    "X minimum": "X 최솟값",
    "X maximum": "X 최댓값",
    "Y minimum": "Y 최솟값",
    "Y maximum": "Y 최댓값",
    "X tick spacing": "X 눈금 간격",
    "Y tick spacing": "Y 눈금 간격",
    "Frame and curves": "프레임과 곡선",
    "Curve width": "곡선 굵기",
    "Tick width": "눈금 굵기",
    "Tick length": "눈금 길이",
    "Frame width": "프레임 굵기",
    "X-axis title": "X축 제목",
    "Y-axis title": "Y축 제목",
    "Tick labels": "눈금 레이블",
    "Size": "크기",
    "Bold": "굵게",
    "Color": "색상",
    "Choose…": "선택…",
    "When Korean text is present, LabPlotter automatically uses an installed Hangul-capable fallback font.": "한글이 포함되면 LabPlotter가 설치된 한글 지원 글꼴을 자동으로 사용합니다.",
    "Choose a line or shape, then drag directly on the graph. Positions are kept relative to the graph frame.": "선이나 도형을 선택한 뒤 그래프 위에서 직접 드래그하세요. 위치는 그래프 프레임을 기준으로 유지됩니다.",
    "New annotation": "새 주석 도형",
    "Type": "종류",
    "Style": "선 모양",
    "Width": "굵기",
    "Line": "선",
    "Rectangle": "직사각형",
    "Ellipse": "타원",
    "Circle": "원",
    "Solid": "실선",
    "Dashed": "긴 점선",
    "Dotted": "점선",
    "Dash-dot": "일점쇄선",
    "Draw on graph": "그래프에 그리기",
    "Placed annotations": "배치된 선과 도형",
    # ZetaSizer OCR review
    "OCR reviewed (high first)": "OCR 검수 수(많은 순)",
    "OCR reading": "OCR 읽기",
    "OCR reading · {kind} measurement {number}": "OCR 읽기 · {kind} 측정 {number}",
    "Original result image": "원본 결과 이미지",
    "Editable OCR result": "편집 가능한 OCR 결과",
    "OCR is a draft. Compare every value with the source image; low-confidence cells are highlighted.": "OCR 결과는 초안입니다. 모든 값을 원본 이미지와 비교하세요. 신뢰도가 낮은 셀은 강조됩니다.",
    "Run OCR again": "OCR 다시 실행",
    "Add row": "행 추가",
    "Remove last row": "마지막 행 제거",
    "Save reviewed result to library": "검수 결과를 라이브러리에 저장",
    "Not reviewed": "검수 안 됨",
    "Reviewed and saved": "검수 및 저장 완료",
    "OCR draft · review required": "OCR 초안 · 검수 필요",
    "Running local OCR…": "로컬 OCR 실행 중…",
    "OCR failed": "OCR 실패",
    "Confirm reviewed OCR": "OCR 검수 확인",
    "Have you compared the editable result with the source image? Save this reviewed table to the particle library?": "편집 결과를 원본 이미지와 비교했나요? 이 검수된 표를 파티클 라이브러리에 저장할까요?",
    "OCR saved": "OCR 저장 완료",
    "Reviewed OCR result saved to the particle library.": "검수한 OCR 결과를 파티클 라이브러리에 저장했습니다.",
    "{kind}_OCR M{number}": "{kind}_OCR 측정{number}",
    "Select a measurement above, then create an editable OCR review tab.": "위에서 측정을 선택한 뒤 편집 가능한 OCR 검수 탭을 만드세요.",
    "OCR current measurement…": "현재 측정 OCR 읽기…",
    "Name": "항목",
    "Mean": "평균",
    "Standard Deviation": "표준편차",
    "RSD": "RSD",
    "Minimum": "최솟값",
    "Maximum": "최댓값",
    "Remove selected": "선택 항목 제거",
    "Clear all": "모두 지우기",
    "Drag on the graph…": "그래프 위에서 드래그하세요…",
    "Annotation added": "주석 도형이 추가되었습니다",
    # Matplotlib toolbar
    "Home": "홈",
    "Reset original view": "처음 보기로 복원",
    "Back": "뒤로",
    "Back to previous view": "이전 보기로",
    "Forward": "앞으로",
    "Forward to next view": "다음 보기로",
    "Pan": "이동",
    "Left button pans, Right button zooms\nx/y fixes axis, CTRL fixes aspect": "왼쪽 버튼: 이동, 오른쪽 버튼: 확대/축소\nx/y: 축 고정, Ctrl: 종횡비 고정",
    "Zoom": "확대/축소",
    "Zoom to rectangle\nx/y fixes axis": "사각형 영역 확대\nx/y: 축 고정",
    "Subplots": "부분 그래프",
    "Configure subplots": "부분 그래프 설정",
    "Save": "저장",
    "Save the figure": "그래프 저장",
    # Axis names
    "Wavenumber": "파수",
    "Transmittance": "투과도",
    "Absorbance": "흡광도",
    "Wavelength": "파장",
    "Particle diameter": "입자 직경",
    "Intensity": "강도",
    "Zeta potential": "제타 전위",
    "Total counts": "총 계수",
    "Chemical shift": "화학적 이동",
    # FTIR
    "Add FTIR files…": "FTIR 파일 추가…",
    "FTIR processing": "FTIR 처리",
    "Baseline correction": "베이스라인 보정",
    "Method": "방법",
    "Spectrum": "스펙트럼",
    "Smoothness λ": "평활도 λ",
    "Asymmetry p": "비대칭도 p",
    "Polynomial order": "다항식 차수",
    "Normalization": "정규화",
    "Mark peaks": "피크 표시",
    "Apply processing": "처리 적용",
    "Common FTIR range reference…": "일반적인 FTIR 범위 참고표…",
    "Linear endpoints (diagonal)": "양 끝점 직선(대각선)",
    "Rubberband (convex hull)": "러버밴드(볼록 껍질)",
    "Modified polynomial (ModPoly)": "수정 다항식(ModPoly)",
    "AsLS (asymmetric least squares)": "AsLS(비대칭 최소제곱)",
    "arPLS (asymmetrically reweighted PLS)": "arPLS(비대칭 재가중 PLS)",
    "airPLS (adaptive reweighted PLS)": "airPLS(적응형 재가중 PLS)",
    "Transmittance (downward bands)": "투과도(아래 방향 밴드)",
    "Absorbance (upward peaks)": "흡광도(위 방향 피크)",
    "Min-max (0–1)": "최소–최대(0–1)",
    "Maximum = 1": "최댓값 = 1",
    "Vector (L2)": "벡터(L2)",
    "Add one or more FTIR files": "하나 이상의 FTIR 파일을 추가하세요",
    "FTIR data": "FTIR 데이터",
    "FTIR import": "FTIR 가져오기",
    "Common FTIR ranges · reference only": "일반적인 FTIR 범위 · 참고용",
    "Ranges overlap and do not constitute a unique functional-group assignment.": "범위는 서로 겹치며 특정 작용기를 단독으로 확정하는 기준이 아닙니다.",
    "Candidate vibration / group": "후보 진동 / 작용기",
    "Approximate range": "대략적인 범위",
    "O–H stretch (often broad)": "O–H 신축(흔히 넓음)",
    "N–H stretch": "N–H 신축",
    "=C–H / aromatic C–H stretch": "=C–H / 방향족 C–H 신축",
    "sp3 C–H stretch": "sp3 C–H 신축",
    "C≡N / C≡C region": "C≡N / C≡C 영역",
    "C=O stretch": "C=O 신축",
    "Aromatic C=C region": "방향족 C=C 영역",
    "C–N stretch (context dependent)": "C–N 신축(환경 의존)",
    "C–O stretch": "C–O 신축",
    "Aromatic C–H out-of-plane": "방향족 C–H 면외 진동",
    # Help text
    "The median values in the first and last 3% of the spectrum are joined by a straight line. This is closest to manually selecting both ends for a diagonal baseline in Origin. It is transparent and stable for nearly linear drift, but biased when a real band occurs at either end.": "스펙트럼 양 끝 3% 구간의 중앙값을 직선으로 연결합니다. Origin에서 양 끝을 잡아 대각선 베이스라인을 만드는 방식과 가장 가깝습니다. 베이스라인 드리프트가 거의 직선일 때 명확하고 안정적이지만, 양 끝에 실제 밴드가 있으면 편향될 수 있습니다.",
    "A piecewise-linear baseline follows the upper convex hull for transmittance or the lower hull for absorbance. It is useful for a broad, slowly varying background, but noise or very broad bands may be mistaken for the baseline.": "투과도에서는 스펙트럼 위쪽의 볼록 껍질, 흡광도에서는 아래쪽 껍질을 따라 구간별 직선 베이스라인을 만듭니다. 넓고 완만한 배경에 유용하지만 노이즈나 매우 넓은 밴드를 베이스라인으로 오인할 수 있습니다.",
    "A polynomial is fitted repeatedly while points on the peak or band side are clipped automatically. The polynomial order controls curvature; 2–4 is usually reasonable. A high order can follow and remove real broad bands.": "피크나 밴드 쪽 점을 자동으로 제외하면서 다항식을 반복 피팅합니다. 다항식 차수가 곡률을 결정하며 보통 2–4가 적절합니다. 차수가 너무 높으면 실제 넓은 밴드까지 베이스라인이 따라가 제거할 수 있습니다.",
    "A Whittaker smoother with asymmetric weights estimates the baseline. Larger λ produces a smoother baseline, while p controls peak/baseline asymmetry. Strong broad bands can be overcorrected depending on λ and p.": "Whittaker 평활화와 비대칭 가중치로 베이스라인을 추정합니다. λ가 클수록 더 매끄러워지고 p가 피크와 베이스라인의 비대칭성을 정합니다. 강하고 넓은 밴드는 λ와 p에 따라 과보정될 수 있습니다.",
    "Weights are adjusted iteratively from the negative-residual distribution. Unlike AsLS, p does not need to be selected directly and λ is the main control. It adapts relatively automatically to curved backgrounds.": "음의 잔차 분포를 이용해 가중치를 반복 조정합니다. AsLS와 달리 p를 직접 정하지 않아도 되며 λ가 주 조절값입니다. 곡선형 배경에 비교적 자동으로 대응합니다.",
    "Adaptive PLS gives progressively larger weights to residuals below the baseline. Peak positions are not required and λ controls smoothness. It can help with complex backgrounds but may be aggressive for some spectra.": "베이스라인 아래 잔차에 점차 더 큰 가중치를 주는 적응형 PLS입니다. 피크 위치를 지정할 필요가 없고 λ가 평활도를 조절합니다. 복잡한 배경에 유용하지만 일부 스펙트럼에서는 과도하게 보정될 수 있습니다.",
    "Transmittance has downward bands, so an upper baseline is estimated and corrected as T/baseline × 100. Absorbance has upward peaks, so a lower baseline is estimated and subtracted.": "투과도는 아래 방향 밴드를 가지므로 위쪽 베이스라인을 추정한 뒤 T/베이스라인 × 100으로 보정합니다. 흡광도는 위 방향 피크를 가지므로 아래쪽 베이스라인을 추정한 뒤 베이스라인을 뺍니다.",
    # NanoDrop
    "Add NanoDrop file…": "NanoDrop 파일 추가…",
    "Plot one Blank spectrum": "Blank 스펙트럼 하나 표시",
    "Double-click Plot to show/hide a curve.\nDouble-click a name to rename it.": "표시 열을 더블클릭하면 곡선을 표시/숨김합니다.\n이름을 더블클릭하면 이름을 변경합니다.",
    "NanoDrop exports": "NanoDrop 내보내기 파일",
    "NanoDrop import": "NanoDrop 가져오기",
    "Add a NanoDrop XML/XLSX export": "NanoDrop XML/XLSX 파일을 추가하세요",
    # Solid-state NMR
    "Add Bruker ZIP…": "Bruker ZIP 추가…",
    "All supported 1D FIDs are listed. When 13C data are present, carbon spectra are shown by default and other nuclei remain hidden.": "지원되는 모든 1D FID를 표시합니다. 13C 데이터가 있으면 탄소 스펙트럼을 기본 표시하고 다른 핵종은 숨깁니다.",
    "ssNMR processing": "ssNMR 처리",
    "Use saved TopSpin window function": "저장된 TopSpin window function 사용",
    "Phase mode": "위상 방식",
    "Automatic phase": "자동 위상 보정",
    "Saved TopSpin phase": "저장된 TopSpin 위상",
    "Magnitude (phase independent)": "크기 스펙트럼(위상 독립)",
    "No phase correction": "위상 보정 없음",
    "Automatic phase minimizes dispersive/negative signal in the expected nucleus range. Saved TopSpin phase uses PHC0/PHC1 from procs. Magnitude is phase-independent but broadens line shapes.": "자동 위상 보정은 해당 핵종의 예상 범위에서 분산형·음의 신호를 최소화합니다. 저장된 TopSpin 위상은 procs의 PHC0/PHC1을 사용합니다. 크기 스펙트럼은 위상과 무관하지만 선 모양이 넓어집니다.",
    "Additional line broadening (Hz)": "추가 line broadening (Hz)",
    "P0 adjustment (degrees)": "P0 조정(도)",
    "P1 adjustment (degrees)": "P1 조정(도)",
    "Vertical offset": "수직 간격",
    "Linear edge baseline": "양 끝 직선 베이스라인",
    "Normalize each spectrum": "각 스펙트럼 정규화",
    "View acquisition details…": "측정 정보 보기…",
    "Bruker/TopSpin ZIP": "Bruker/TopSpin ZIP",
    "ssNMR import": "ssNMR 가져오기",
    "Imported {count} one-dimensional spectra; {carbon} are 13C spectra.": "1D 스펙트럼 {count}개를 가져왔으며 그중 {carbon}개가 13C 스펙트럼입니다.",
    "Skipped:": "제외된 항목:",
    "Add a Bruker ssNMR ZIP archive": "Bruker ssNMR ZIP 파일을 추가하세요",
    "Acquisition details": "측정 정보",
    "Select exactly one spectrum.": "스펙트럼 하나만 선택하세요.",
    "Experiment": "실험 번호",
    "Nucleus": "핵종",
    "Pulse program": "펄스 프로그램",
    "Title": "제목",
    "Scans": "스캔 수",
    "MAS rate": "MAS 속도",
    "Spectral width": "스펙트럼 폭",
    "Saved line broadening": "저장된 line broadening",
    "Group delay": "그룹 지연",
    "Unsupported Bruker acquisition data type: {type}": "지원하지 않는 Bruker 측정 데이터 형식입니다: {type}",
    "The Bruker FID does not contain enough complex points.": "Bruker FID에 복소 데이터 포인트가 충분하지 않습니다.",
    "This is not a readable Bruker ZIP archive: {error}": "읽을 수 있는 Bruker ZIP 파일이 아닙니다: {error}",
    "The ZIP archive contains too many entries.": "ZIP 파일에 항목이 너무 많습니다.",
    "No Bruker acqus files were found in the ZIP archive.": "ZIP 파일에서 Bruker acqus 파일을 찾지 못했습니다.",
    "Experiment {experiment}: pseudo-2D/2D ser data": "실험 {experiment}: pseudo-2D/2D ser 데이터",
    "Experiment {experiment}: FID is larger than the safety limit": "실험 {experiment}: FID가 안전 제한보다 큽니다",
    "Experiment {experiment}: {error}": "실험 {experiment}: {error}",
    "No supported one-dimensional FIDs were found.": "지원되는 1D FID를 찾지 못했습니다.",
    # ZetaSizer
    "Import ZetaSizer workbook…": "ZetaSizer 통합문서 가져오기…",
    "Particle library · select one or more": "입자 라이브러리 · 하나 이상 선택",
    "Particle": "입자",
    "DLS n": "DLS 수",
    "Zeta n": "Zeta 수",
    "OCR n": "OCR 검수 수",
    "Comparison": "비교",
    "Data": "데이터",
    "Display": "표시 방식",
    "Zeta": "Zeta 전위",
    "Mean ± SD": "평균 ± 표준편차",
    "Mean + replicates": "평균 + 반복 측정",
    "Replicates only": "반복 측정만",
    "Log X for DLS": "DLS X축 로그",
    "View result tables": "결과표 보기",
    "View result tables…": "결과표 보기…",
    "Refresh library": "라이브러리 새로고침",
    "Library tools": "라이브러리 도구",
    "Sort by": "정렬 기준",
    "Name A–Z": "이름 오름차순",
    "Name Z–A": "이름 내림차순",
    "Recently updated": "최근 업데이트순",
    "DLS count (high first)": "DLS 수 많은 순",
    "Zeta count (high first)": "Zeta 수 많은 순",
    "Source A–Z": "원본 이름순",
    "Default sorting": "기본 정렬",
    "Delete selected…": "선택 입자 삭제…",
    "Particle library": "입자 라이브러리",
    "Select one or more particles first.": "먼저 하나 이상의 입자를 선택하세요.",
    "Delete particles": "입자 삭제",
    "Delete {count} selected particles and all of their stored measurements? This cannot be undone.": "선택한 입자 {count}개와 저장된 모든 측정값을 삭제할까요? 이 작업은 되돌릴 수 없습니다.",
    "ZetaSizer Excel": "ZetaSizer Excel",
    "ZetaSizer import": "ZetaSizer 가져오기",
    "Stored {curves} replicate curves for {particles} particles.": "{particles}개 입자의 반복 측정 곡선 {curves}개를 저장했습니다.",
    "Import a workbook, then select particles from the library": "통합문서를 가져온 뒤 라이브러리에서 입자를 선택하세요",
    "Result tables": "결과표",
    "Select exactly one particle.": "입자 하나만 선택하세요.",
    "{particle} · {kind} result tables": "{particle} · {kind} 결과표",
    "{particle} · result tables": "{particle} · 결과표",
    "No embedded table image": "포함된 결과표 이미지가 없습니다",
    "Embedded source image: {width} × {height} px": "원본 포함 이미지: {width} × {height} px",
    "Fit window": "창에 맞춤",
    "rep {number}": "반복 {number}",
    # Custom formats
    "Map a new Excel format": "새 Excel 형식 지정",
    "{name} format": "{name} 형식",
    "Custom format name": "사용자 형식 이름",
    "Sheet": "시트",
    "Header row": "헤더 행",
    "Data starts at row": "데이터 시작 행",
    "X column": "X 열",
    "Y column(s), comma separated": "Y 열(여러 개는 쉼표로 구분)",
    "Cancel": "취소",
    "Save format and import": "형식 저장 후 가져오기",
    "A name and at least one Y column are required.": "이름과 하나 이상의 Y 열이 필요합니다.",
    "Format mapping": "형식 지정",
    "Saved format": "저장된 형식",
    "Import using selected format…": "선택한 형식으로 가져오기…",
    "Map a new format…": "새 형식 지정…",
    "Remove selected curves": "선택한 곡선 제거",
    "Set selected curve color…": "선택한 곡선 색상 지정…",
    "Unknown workbooks open a preview where you\nchoose the sheet, header, X and Y columns.": "처음 보는 통합문서는 미리보기에서\n시트, 헤더, X/Y 열을 지정합니다.",
    "Data workbooks": "데이터 통합문서",
    "Custom format": "사용자 형식",
    "Create a format mapping first.": "먼저 형식을 지정하세요.",
    "New or unrecognized format": "새 형식 또는 인식되지 않은 형식",
    "{name} does not match a saved format.\nPlease map its sheet and data columns once.": "{name}은 저장된 형식과 일치하지 않습니다.\n시트와 데이터 열을 한 번 지정하세요.",
    "Custom import": "사용자 형식 가져오기",
    "Create or select a custom format, then import data": "사용자 형식을 만들거나 선택한 뒤 데이터를 가져오세요",
    # Update center
    "LabPlotter Update Center": "LabPlotter 업데이트 센터",
    "Installed version: {version}": "설치된 버전: {version}",
    "Apply a verified .labpatch file without replacing the application folder or its local Python environment. The app closes during the update and restarts automatically.": "앱 폴더나 로컬 Python 환경을 교체하지 않고 검증된 .labpatch 파일을 적용합니다. 업데이트 중 앱이 종료되고 완료 후 자동으로 다시 실행됩니다.",
    "Apply .labpatch…": ".labpatch 적용…",
    "Rollback latest update…": "최근 업데이트 되돌리기…",
    "Available rollback backups: {count}": "사용 가능한 롤백 백업: {count}",
    # Contact
    "Contact and feedback": "연락처 및 피드백",
    "Copy email": "이메일 복사",
    "Feedback, bug reports, and requests for new instrument formats are welcome.": "피드백, 오류 제보, 새로운 장비 형식 추가 요청을 환영합니다.",
    "Email address copied.": "이메일 주소를 복사했습니다.",
    "Select LabPlotter patch": "LabPlotter 패치 선택",
    "LabPlotter patch": "LabPlotter 패치",
    "Apply update": "업데이트 적용",
    "LabPlotter will close, apply the patch, validate it, and restart. Continue?": "LabPlotter를 종료하고 패치를 적용·검증한 뒤 다시 실행합니다. 계속할까요?",
    "Rollback": "되돌리기",
    "No applied update backup is available.": "적용된 업데이트의 백업이 없습니다.",
    "Restore the version from immediately before the latest update? LabPlotter will close and restart.": "최근 업데이트 직전 버전으로 복원할까요? LabPlotter가 종료된 뒤 다시 실행됩니다.",
    "Lab data": "실험 데이터",
    "Smart Import": "스마트 가져오기",
    "Update Manager": "업데이트 관리자",
    "updater.py is missing from the application folder.": "앱 폴더에 updater.py가 없습니다.",
    "LabPlotter startup error": "LabPlotter 시작 오류",
    "LabPlotter error": "LabPlotter 오류",
    "Error log:": "오류 로그:",
    # Data and processing errors
    "Unsupported FTIR file: {suffix}": "지원하지 않는 FTIR 파일입니다: {suffix}",
    "Could not find at least three numeric X/Y rows.": "숫자로 된 X/Y 행을 세 개 이상 찾지 못했습니다.",
    "Unsupported NanoDrop file: {suffix}": "지원하지 않는 NanoDrop 파일입니다: {suffix}",
    "No DLS or zeta-potential raw data sheets were detected.": "DLS 또는 zeta-potential 원자료 시트를 찾지 못했습니다.",
    "Invalid column: {column}": "잘못된 열입니다: {column}",
    "Sheet '{sheet}' is not present.": "'{sheet}' 시트가 없습니다.",
    "The selected mapping did not produce numeric X/Y data.": "선택한 형식에서 숫자 X/Y 데이터를 얻지 못했습니다.",
    "No curves": "곡선이 없습니다",
    "Replicate X ranges do not overlap": "반복 측정의 X 범위가 서로 겹치지 않습니다",
    # Clipboard errors
    "Could not create a Windows bitmap for the clipboard.": "클립보드용 Windows 비트맵을 만들 수 없습니다.",
    "Image clipboard is currently supported on Windows builds.": "이미지 클립보드는 현재 Windows 빌드에서만 지원됩니다.",
    "Could not allocate clipboard memory.": "클립보드 메모리를 할당할 수 없습니다.",
    "Could not lock clipboard memory.": "클립보드 메모리를 잠글 수 없습니다.",
    "Could not open the Windows clipboard. Close other clipboard tools and try again.": "Windows 클립보드를 열 수 없습니다. 다른 클립보드 도구를 닫고 다시 시도하세요.",
    "Could not clear the Windows clipboard.": "Windows 클립보드를 비울 수 없습니다.",
    "Windows rejected the bitmap clipboard data.": "Windows가 비트맵 클립보드 데이터를 받지 못했습니다.",
    # External update manager and patch validation
    "LabPlotter Update Manager": "LabPlotter 업데이트 관리자",
    "Preparing update…": "업데이트 준비 중…",
    "Unsafe patch path: {path}": "안전하지 않은 패치 경로입니다: {path}",
    "Non-portable patch path: {path}": "호환되지 않는 패치 경로입니다: {path}",
    "Patch path is outside the LabPlotter allowlist: {path}": "LabPlotter 허용 목록 밖의 패치 경로입니다: {path}",
    "Patch cannot modify protected directory: {path}": "패치가 보호된 폴더를 수정할 수 없습니다: {path}",
    "version.json is missing; this installation cannot accept .labpatch files.": "version.json이 없어 이 설치본에는 .labpatch를 적용할 수 없습니다.",
    "Could not read the installed version: {error}": "설치된 버전을 읽을 수 없습니다: {error}",
    "The patch does not contain manifest.json.": "패치에 manifest.json이 없습니다.",
    "Invalid manifest.json: {error}": "잘못된 manifest.json입니다: {error}",
    "Unsupported patch format: {format}": "지원하지 않는 패치 형식입니다: {format}",
    "This patch is not for LabPlotter.": "LabPlotter용 패치가 아닙니다.",
    "Patch version metadata is incomplete.": "패치 버전 정보가 불완전합니다.",
    "Patch file lists are invalid.": "패치 파일 목록이 잘못되었습니다.",
    "Invalid cumulative snapshot metadata.": "누적 스냅샷 패치 정보가 잘못되었습니다.",
    "Cumulative snapshot file inventory is incomplete.": "누적 스냅샷의 파일 목록이 불완전합니다.",
    "A patch file entry is incomplete.": "패치 파일 항목이 불완전합니다.",
    "Duplicate patch path: {path}": "중복된 패치 경로입니다: {path}",
    "Patch payload is missing: {path}": "패치 데이터가 없습니다: {path}",
    "Checksum validation failed: {path}": "체크섬 검증에 실패했습니다: {path}",
    "Patch expected a new file, but it already exists: {path}": "패치가 새 파일을 예상했지만 이미 존재합니다: {path}",
    "Installed file differs from the expected base version: {path}": "설치된 파일이 예상 기준 버전과 다릅니다: {path}",
    "A delete entry is incomplete.": "삭제 항목이 불완전합니다.",
    "A path cannot be replaced and deleted together: {path}": "같은 경로를 교체하면서 삭제할 수 없습니다: {path}",
    "File scheduled for deletion differs from the expected base: {path}": "삭제할 파일이 예상 기준 파일과 다릅니다: {path}",
    "Could not snapshot the current Python environment.\n{details}": "현재 Python 환경을 기록할 수 없습니다.\n{details}",
    "The selected backup is incomplete.": "선택한 백업이 불완전합니다.",
    "This backup does not match the currently installed version.": "이 백업은 현재 설치된 버전과 일치하지 않습니다.",
    "Restoring LabPlotter {version}…": "LabPlotter {version} 복원 중…",
    "Restoring the previous Python dependency versions…": "이전 Python 패키지 버전 복원 중…",
    "Files were restored, but dependency restoration failed.\n{details}": "파일은 복원했지만 Python 패키지 복원에 실패했습니다.\n{details}",
    "Installing updated Python dependencies…": "업데이트된 Python 패키지 설치 중…",
    "Dependency installation failed.\n{details}": "Python 패키지 설치에 실패했습니다.\n{details}",
    "Post-update smoke test failed.\n{details}": "업데이트 후 실행 점검에 실패했습니다.\n{details}",
    "Select a file with the .labpatch extension.": ".labpatch 확장자 파일을 선택하세요.",
    "The selected patch file does not exist.": "선택한 패치 파일이 없습니다.",
    "Validating {name}…": "{name} 검증 중…",
    "This patch accepts {versions}, but the installed version is {current}.": "이 패치는 {versions} 버전용이지만 현재 설치 버전은 {current}입니다.",
    "This patch is already installed.": "이 패치는 이미 설치되어 있습니다.",
    "The manifest declares dependency changes but does not include requirements.txt.": "패키지 변경이 선언되었지만 requirements.txt가 포함되지 않았습니다.",
    "Applying verified files…": "검증된 파일 적용 중…",
    "Running post-update validation…": "업데이트 후 실행 점검 중…",
    "Update completed: {current} → {target}": "업데이트 완료: {current} → {target}",
    "Update failed; restoring the previous version…": "업데이트 실패: 이전 버전 복원 중…",
    "Update failed: {error}\nRollback also failed: {rollback_error}": "업데이트 실패: {error}\n롤백도 실패했습니다: {rollback_error}",
    "Rollback completed. Restored LabPlotter {version}.": "롤백 완료: LabPlotter {version}을 복원했습니다.",
    "Update failed.": "업데이트에 실패했습니다.",
    "The previous installation was kept or restored when possible.": "가능한 경우 이전 설치 상태를 유지하거나 복원했습니다.",
    "Log:": "로그:",
}


def _translated(source: str, language: str) -> str:
    return KO.get(source, source) if language == "ko" else source


def translate_value(value: str, old_language: str, new_language: str) -> str:
    if old_language == new_language:
        return value
    for english, korean in KO.items():
        source = korean if old_language == "ko" else english
        target = korean if new_language == "ko" else english
        if value == source:
            return target
        if "{" in source:
            fields = []
            pattern = ""
            for literal, field, _format_spec, _conversion in string.Formatter().parse(source):
                pattern += re.escape(literal)
                if field:
                    fields.append(field)
                    pattern += rf"(?P<{field}>.+?)"
            match = re.fullmatch(pattern, value)
            if match:
                translated_fields = {
                    key: translate_value(field_value, old_language, new_language)
                    for key, field_value in match.groupdict().items()
                }
                return target.format(**translated_fields)
    return value


def canonical(value: str) -> str:
    for english, korean in KO.items():
        if value == korean:
            return english
    return value


class LanguageManager:
    def __init__(self, path: Path | None = None):
        if path is None:
            try:
                path = settings_path()
            except OSError:
                path = None
        self.path = path
        self.current = "en"
        self._listeners: list[weakref.WeakMethod] = []
        if self.path and self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
                if value.get("language") in {"en", "ko"}:
                    self.current = value["language"]
            except Exception:
                pass

    def text(self, source: str, language: str | None = None, **values) -> str:
        text = _translated(source, language or self.current)
        return text.format(**values) if values else text

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        self._listeners.append(weakref.WeakMethod(callback))

    def set(self, language: str) -> None:
        if language not in {"en", "ko"} or language == self.current:
            return
        old = self.current
        self.current = language
        if self.path:
            try:
                value = {}
                if self.path.exists():
                    value = json.loads(self.path.read_text(encoding="utf-8"))
                value["language"] = language
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
        live = []
        for reference in self._listeners:
            callback = reference()
            if callback is not None:
                live.append(reference)
                callback(old, language)
        self._listeners = live


manager = LanguageManager()


def tr(source: str, **values) -> str:
    return manager.text(source, **values)


def language() -> str:
    return manager.current


def set_language(value: str) -> None:
    manager.set(value)


def localize_widget_tree(widget, old_language: str = "en", new_language: str | None = None) -> None:
    """Translate static Tk text, headings, notebook tabs and choice lists in place."""
    target = new_language or manager.current
    if old_language == target:
        return
    try:
        current_title = widget.title()
        widget.title(translate_value(current_title, old_language, target))
    except Exception:
        pass
    try:
        text = widget.cget("text")
        if isinstance(text, str) and text:
            widget.configure(text=translate_value(text, old_language, target))
    except Exception:
        pass
    try:
        columns = widget.cget("columns")
        for column in columns:
            heading = widget.heading(column)
            if heading.get("text"):
                widget.heading(column, text=translate_value(heading["text"], old_language, target))
    except Exception:
        pass
    try:
        values = tuple(widget.cget("values"))
        if values:
            current = widget.get()
            widget.configure(values=tuple(translate_value(str(value), old_language, target) for value in values))
            translated_current = translate_value(current, old_language, target)
            if translated_current != current:
                widget.set(translated_current)
    except Exception:
        pass
    try:
        for tab_id in widget.tabs():
            tab_text = widget.tab(tab_id, "text")
            widget.tab(tab_id, text=translate_value(tab_text, old_language, target))
    except Exception:
        pass
    for child in widget.winfo_children():
        localize_widget_tree(child, old_language, target)
