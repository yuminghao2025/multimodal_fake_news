# 发布前一键自检：结构 + 媒体存活 + 核查产物 + 技能套件 + 密钥泄漏
# 用法：powershell -ExecutionPolicy Bypass -File skills\check_all.ps1
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = "fake_news_env\Scripts\python.exe"
$env:PYTHONIOENCODING = 'utf-8'
$fail = 0

Write-Host "[1/5] 数据集结构校验 ..."
& $py prototype\check_dataset.py
if ($LASTEXITCODE -ne 0) { $fail++ }

Write-Host "[2/5] 媒体存活校验 ..."
$baseline = "metadata\media_baseline.json"
if (Test-Path $baseline) {
    & $py prototype\check_media.py --compare $baseline
    if ($LASTEXITCODE -ne 0) { $fail++ }
} else {
    & $py prototype\check_media.py --save $baseline
    Write-Host "  已生成基线（首次运行），下次将对比"
}

Write-Host "[3/5] 核查产物校验 ..."
& $py prototype\check_verify.py
if ($LASTEXITCODE -ne 0) { $fail++ }

Write-Host "[4/5] 技能套件自检 ..."
& $py prototype\check_skills.py
if ($LASTEXITCODE -ne 0) { $fail++ }

Write-Host "[5/5] 密钥泄漏扫描 ..."
$strict = git grep -I -E 'AIzaSy[0-9A-Za-z_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|ghp_[0-9A-Za-z]{30,}|sk-[A-Za-z0-9]{32,}' 2>$null
if ($LASTEXITCODE -eq 0 -and $strict) {
    Write-Host "  [FAIL] 发现疑似密钥：" -ForegroundColor Red
    $strict
    $fail++
} else {
    Write-Host "  无真实密钥形态命中"
}
$broad = git grep -I -E 'api[_-]?key\s*=' 2>$null | Where-Object { $_ -notmatch 'git grep|自查|SKILL\.md|compliance_checklist' }
if ($broad) {
    Write-Host "  [INFO] 以下 api_key 赋值需人工确认不是硬编码秘密：" -ForegroundColor Yellow
    $broad
}

if ($fail -gt 0) {
    Write-Host "`n自检未通过：$fail 项失败" -ForegroundColor Red
    exit 1
}
Write-Host "`n自检全部通过，可以提交/推送" -ForegroundColor Green
exit 0