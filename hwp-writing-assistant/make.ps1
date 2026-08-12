# make.ps1 — 원고(.md) 하나로 전체 파이프라인을 돌린다.
#
#   .\make.ps1 원고.md              검증 → 생성 → 후처리 → 미리보기
#   .\make.ps1 원고.md -Open        위 과정 후 한글로 열기
#   .\make.ps1 원고.md -Out 보고서.hwpx
#   .\make.ps1 원고.md -NoShiftTab   한글 실측 내어쓰기 단계를 끔
#   .\make.ps1 원고.md -Force       숫자 오류가 있어도 계속 진행
#
# 숫자 검증에서 오류(❌)가 나오면 기본적으로 여기서 멈춘다.
# 틀린 숫자로 hwpx를 만들면 고친 뒤 다시 만들어야 하므로 두 번 일이 된다.

param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Src,
    [string]$Out,
    [switch]$LabelIndent,
    [switch]$NoShiftTab,
    [switch]$Open,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = "python"

if (-not (Test-Path $Src)) { Write-Host "원고를 찾을 수 없음: $Src" -ForegroundColor Red; exit 1 }
if (-not $Out) { $Out = [IO.Path]::ChangeExtension($Src, ".hwpx") }
$draft = [IO.Path]::Combine([IO.Path]::GetTempPath(), "_draft_$(Get-Random).hwpx")

Write-Host "`n[1/4] 숫자 검증" -ForegroundColor Cyan
& $py "$here\scripts\check_numbers.py" $Src
$bad = $LASTEXITCODE
if ($bad -ne 0 -and -not $Force) {
    Write-Host "`n숫자 오류가 있어 중단함. 고친 뒤 다시 실행하거나, 그대로 만들려면 -Force 를 붙일 것." -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] HWPX 생성" -ForegroundColor Cyan
& $py "$here\scripts\build_hwpx.py" $Src $draft
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n[3/4] 레이아웃 후처리" -ForegroundColor Cyan
$polishArgs = @($draft, $Out)
if ($LabelIndent) { $polishArgs += "--label-indent" }
& $py "$here\scripts\hwpx_polish.py" @polishArgs
if ($LASTEXITCODE -ne 0) { exit 1 }
Remove-Item $draft -ErrorAction SilentlyContinue

if (-not $NoShiftTab) {
    Write-Host "`n[4/5] Shift+Tab 내어쓰기 (한글 실측)" -ForegroundColor Cyan
    & $py "$here\scripts\hwpx_shifttab.py" $Out
    if ($LASTEXITCODE -eq 2) { Write-Host "      → 한글을 쓸 수 없는 환경이라 계산값 그대로 둠" }
}

Write-Host "`n[5/5] 미리보기" -ForegroundColor Cyan
& $py "$here\scripts\preview_hwpx.py" $Out --detail

Write-Host "`n완료: $Out" -ForegroundColor Green
Write-Host "한글에서 확인할 것: ① 줄바꿈이 어절 경계인가 ② 이어지는 줄이 기호 뒤에 정렬됐는가 ③ 글자 겹침이 없는가 ④ 표 테두리·열 너비"

if ($Open) { Start-Process $Out }
