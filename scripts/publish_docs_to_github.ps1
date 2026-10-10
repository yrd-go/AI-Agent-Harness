<#
.SYNOPSIS
    把本地 AI-Agent-Harness 的文档与代码改动同步到 GitHub（README 重写 / 截图归入 docs/images /
    P0 安全修复 / 测试与 CI）。

.DESCRIPTION
    为什么需要这个脚本：
        本机没装 gh CLI，git 也没有全局身份与凭据缓存，因此无法由工具直接改远端；
        而 44 张截图需要 `git mv` 才能保留历史。脚本把这一整套动作固化下来：

        1) clone（或复用）仓库到工作目录；
        2) git mv 01~44-*.png -> docs/images/（保留 Git 历史，图片链接不失效）；
        3) 用本地源目录的文件覆盖：README / LICENSE / docs/PITFALLS.md / src / scripts / tests /
           .github / DEPLOY*.md / requirements.txt 等；
        4) 打印 git status 与 diff --stat，让你先看清楚改了什么；
        5) 只有显式加 -Push 才会 commit + push。

    安全设计：
        - 默认 **干跑**（不加 -Push 不提交、不推送）；
        - 绝不复制 .env / secrets.toml（并会显式检查、发现就报错退出）；
        - 只对仓库根目录里形如 `NN-*.png` 的文件执行 git mv，router_output.png 等历史产物留在原地。

.EXAMPLE
    # 1) 先干跑，看 diff（推荐第一步）
    pwsh -File scripts\publish_docs_to_github.ps1 -UserEmail "you@example.com"

.EXAMPLE
    # 2) 确认无误后真正提交并推送
    pwsh -File scripts\publish_docs_to_github.ps1 -UserEmail "you@example.com" -Push

.NOTES
    建议用 PowerShell 7（pwsh）执行；Windows PowerShell 5.1 对无 BOM 的 UTF-8 脚本可能显示乱码
    （不影响 git 操作本身）。推送时若提示输入凭据，请用 GitHub 的 Personal Access Token 作为密码，
    或提前配置好 Git Credential Manager。
#>
[CmdletBinding()]
param(
    [string]$SourceDir = "C:\Users\Administrator\my-agent",
    [string]$RepoUrl = "https://github.com/yrd-go/AI-Agent-Harness.git",
    [string]$Branch = "main",
    [string]$WorkDir = (Join-Path $env:TEMP "ai-agent-harness-publish"),
    [string]$UserName = "Rundong Yang",
    [string]$UserEmail = "",
    [string]$CommitMessage = "docs: 重写 README；44 张截图归入 docs/images；补测试与 CI；修复凭据泄露与自检假绿",
    [switch]$Push
)

$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Ok($text)   { Write-Host "  [OK] $text" -ForegroundColor Green }
function Warn($text) { Write-Host "  [WARN] $text" -ForegroundColor Yellow }
function Die($text)  { Write-Host "  [FAIL] $text" -ForegroundColor Red; exit 1 }

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    & git -C $WorkDir @Args
    if ($LASTEXITCODE -ne 0) { Die "git $($Args -join ' ') 失败（退出码 $LASTEXITCODE）" }
}

# ---------------------------------------------------------------------------
Step "0/6 环境与源目录检查"
# ---------------------------------------------------------------------------
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Die "找不到 git，请先安装 Git for Windows" }
if (-not (Test-Path -LiteralPath $SourceDir)) { Die "源目录不存在：$SourceDir" }

$mustHave = @("README.md", "LICENSE", "docs\PITFALLS.md", "streamlit_app.py",
              "tests\run_all.py", ".github\workflows\ci.yml",
              "src\paths.py", "src\mcp_demo\mcp_protocol_probe.py")
$missing = $mustHave | Where-Object { -not (Test-Path -LiteralPath (Join-Path $SourceDir $_)) }
if ($missing) { Die ("源目录缺少这些文件，先确认改动都已完成：`n    " + ($missing -join "`n    ")) }
Ok "源目录文件齐备：$SourceDir"

if ($Push -and [string]::IsNullOrWhiteSpace($UserEmail)) {
    Die "要提交就必须给出邮箱：请加 -UserEmail `"you@example.com`"（本地 git 没有全局身份）"
}
Write-Host "  模式：" -NoNewline
if ($Push) { Write-Host "提交并推送" -ForegroundColor Yellow } else { Write-Host "干跑（不提交、不推送）" -ForegroundColor Green }

# ---------------------------------------------------------------------------
Step "1/6 准备仓库工作副本"
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath (Join-Path $WorkDir ".git")) {
    Ok "复用已有工作副本：$WorkDir"
    Invoke-Git fetch origin $Branch
    Invoke-Git checkout $Branch
    Invoke-Git reset --hard "origin/$Branch"
} else {
    if (Test-Path -LiteralPath $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }
    & git clone --branch $Branch $RepoUrl $WorkDir
    if ($LASTEXITCODE -ne 0) { Die "clone 失败：$RepoUrl（检查网络与仓库权限）" }
    Ok "已 clone 到：$WorkDir"
}

# 安全检查：绝不把密钥文件带上去
foreach ($secret in @(".env", ".streamlit\secrets.toml")) {
    if (Test-Path -LiteralPath (Join-Path $SourceDir $secret)) {
        Warn "源目录存在 $secret（不会被复制，也已被 .gitignore 忽略）"
    }
}

# ---------------------------------------------------------------------------
Step "2/6 把 44 张截图 git mv 到 docs/images/"
# ---------------------------------------------------------------------------
$imagesDir = Join-Path $WorkDir "docs\images"
if (-not (Test-Path -LiteralPath $imagesDir)) { New-Item -ItemType Directory -Path $imagesDir -Force | Out-Null }

$rootPngs = Get-ChildItem -LiteralPath $WorkDir -File -Filter "*.png" |
            Where-Object { $_.Name -match '^\d{2}-' } | Sort-Object Name
if ($rootPngs.Count -eq 0) {
    Ok "根目录已无 NN-*.png（说明之前已迁移过），跳过 git mv"
} else {
    foreach ($png in $rootPngs) {
        Invoke-Git mv $png.Name ("docs/images/" + $png.Name)
    }
    Ok "已迁移 $($rootPngs.Count) 张截图到 docs/images/（保留 Git 历史）"
}

# ---------------------------------------------------------------------------
Step "3/6 用本地改动覆盖仓库文件"
# ---------------------------------------------------------------------------
$files = @(
    "README.md", "LICENSE", "requirements.txt", "DEPLOY.md", "DEPLOY_STRUCTURE.md",
    ".gitignore", "streamlit_app.py", "Dockerfile"
)
foreach ($f in $files) {
    $src = Join-Path $SourceDir $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $WorkDir $f) -Force
        Ok "覆盖 $f"
    }
}

$dirs = @("src", "scripts", "tests", "docs", ".github")
foreach ($d in $dirs) {
    $srcDir = Join-Path $SourceDir $d
    if (-not (Test-Path -LiteralPath $srcDir)) { Warn "源目录没有 $d/，跳过"; continue }
    $dstDir = Join-Path $WorkDir $d
    New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
    # 只复制源码与文档，排除缓存/虚拟环境/临时目录
    Get-ChildItem -LiteralPath $srcDir -Recurse -File |
        Where-Object {
            $_.FullName -notmatch '\\(__pycache__|\.venv|\.venv-rag|\.tmp_|node_modules)\\' -and
            $_.Name -notin @(".env") -and
            $_.Extension -notin @(".pyc", ".log")
        } |
        ForEach-Object {
            $rel = $_.FullName.Substring($srcDir.Length).TrimStart('\')
            $target = Join-Path $dstDir $rel
            New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $target -Force
        }
    Ok "同步 $d/"
}

# ---------------------------------------------------------------------------
Step "4/6 变更清单（提交前先看清楚）"
# ---------------------------------------------------------------------------
Invoke-Git add -A
Write-Host "`n--- git status --short ---"
& git -C $WorkDir status --short
Write-Host "`n--- git diff --cached --stat ---"
& git -C $WorkDir diff --cached --stat

$staged = & git -C $WorkDir diff --cached --name-only
if (-not $staged) {
    Ok "没有任何变更，无需提交（远端可能已经是最新）"
    exit 0
}

# ---------------------------------------------------------------------------
Step "5/6 提交"
# ---------------------------------------------------------------------------
if (-not $Push) {
    Warn "干跑模式：跳过 commit 与 push。确认上面的 diff 无误后，加 -Push 重新执行即可。"
    Write-Host "`n  手动提交命令（如需自己掌控）：" -ForegroundColor DarkGray
    Write-Host "    git -C `"$WorkDir`" config user.name `"$UserName`"" -ForegroundColor DarkGray
    Write-Host "    git -C `"$WorkDir`" config user.email `"$UserEmail`"" -ForegroundColor DarkGray
    Write-Host "    git -C `"$WorkDir`" commit -m `"$CommitMessage`"" -ForegroundColor DarkGray
    Write-Host "    git -C `"$WorkDir`" push origin $Branch" -ForegroundColor DarkGray
    exit 0
}

Invoke-Git config user.name $UserName
Invoke-Git config user.email $UserEmail
Invoke-Git commit -m $CommitMessage
Ok "已提交"

# ---------------------------------------------------------------------------
Step "6/6 推送"
# ---------------------------------------------------------------------------
& git -C $WorkDir push origin $Branch
if ($LASTEXITCODE -ne 0) {
    Warn "push 失败。常见原因与处理："
    Write-Host "    - 需要认证：用 Personal Access Token 当密码，或先配置 Git Credential Manager"
    Write-Host "    - 远端有他人提交：先 git -C `"$WorkDir`" pull --rebase origin $Branch 再 push"
    exit 1
}
Ok "推送成功"
Write-Host "`n接下来建议在 GitHub 上确认三件事：" -ForegroundColor Cyan
Write-Host "  1. 根目录只剩 src / scripts / data / docs / tests，44 张图已在 docs/images/；"
Write-Host "  2. README 首屏能直接看懂项目定位，Quick Start 三条命令可跑；"
Write-Host "  3. Actions 里 CI 变绿（单元测试 + 导入自检）。"
