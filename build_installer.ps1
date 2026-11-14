$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$isccExe = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"

if (-not (Test-Path -LiteralPath $isccExe)) {
    throw "Inno Setup 6를 찾지 못했습니다: $isccExe"
}

Push-Location $projectRoot
try {
    python -m PyInstaller --noconfirm --clean --onefile --windowed `
        --name "SpectrumAnalyzer" `
        --icon "spectrum_analyzer_icon.ico" `
        --version-file "csv_graph_version_info.txt" `
        --exclude-module pygame `
        --exclude-module scipy `
        --exclude-module pandas `
        --distpath "release_1.4.1" `
        "csv_graph_gui.py"
    if ($LASTEXITCODE -ne 0) {
        throw "실행 파일 빌드가 실패했습니다."
    }

    & $isccExe "installer.iss"
    if ($LASTEXITCODE -ne 0) {
        throw "설치 파일 빌드가 실패했습니다."
    }
}
finally {
    Pop-Location
}

Write-Host "설치 파일 생성 완료: $projectRoot\release_1.4.1\SpectrumAnalyzer-Setup-1.4.1-x64.exe"
