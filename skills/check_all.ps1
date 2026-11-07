# 发布前一键自检：数据+技能四项校验（单进程） + 密钥泄漏
# 用法：powershell -ExecutionPolicy Bypass -File skills\check_all.ps1
# 四项校验由 prototype\check_all.py 在同一进程内完成。
# 注意：venv 基于 Windows Store Python 时，WindowsApps 别名解析偶发失败，
#       内置 4 次退避重试；若仍持续失败，用非 Store Python 重建 venv。
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = "fake_news_env\Scripts\python.exe"
$env:PYTHONIOENCODING = 'utf-8'
$fail = 0

Write-Host "[1/2] 数据与技能校验（结构/媒体/核查/技能）..."
$out = $null; $code = 1
for ($attempt = 1; $attempt -le 4; $attempt++) {
    $out = & $py prototype\check_all.py 2>&1
    $code = $LASTEXITCODE
    if ($code -eq 0) { break }
    $transient = ($out -match 'Unable to create process|did not find executable')
    if (-not $transient) { break }
    Write-Host "  (第 $attempt 次启动失败：Windows 别名/进程抖动，重试)" -ForegroundColor Yellow
    Start-Sleep -Milliseconds (600 * $attempt)
}
$out | ForEach-Object { Write-Host $_ }
if ($code -ne 0) { $fail++ }

Write-Host "[2/2] 密钥泄漏扫描 ..."
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