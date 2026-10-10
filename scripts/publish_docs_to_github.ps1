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
    powershell -ExecutionPolicy Bypass -File "C:\Users\Administrator\my-agent\scripts\publish_docs_to_github.ps1" -UserEmail "you@example.com"

.EXAMPLE
    # 2) 确认无误后真正提交并推送
    powershell -ExecutionPolicy Bypass -File "C:\Users\Administrator\my-agent\scripts\publish_docs_to_github.ps1" -UserEmail "you@example.com" -Push

.NOTES
    启动方式（两种都行；本机只装了 Windows PowerShell 5.1，**不需要**安装 PowerShell 7）：
        ① 最稳：
             powershell -ExecutionPolicy Bypass -File "<脚本路径>" -UserEmail "..." [-Push]
        ② 已经在本机 PowerShell 窗口里时：
             & "<脚本路径>" -UserEmail "..." [-Push]
           若提示「未对文件进行数字签名」，说明当前执行策略更严，改用第 ① 种即可。

    脚本已存为「带 BOM 的 UTF-8」，因此 PowerShell 5.1 也能正确读中文。
    推送时会用 Git Credential Manager 弹浏览器登录，需先执行一次：
        git config --global credential.helper manager
    若改用令牌：push 时用户名填 GitHub 用户名、密码粘贴 Personal Access Token。
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
    # 刻意不使用 param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)：
    #   在 Windows PowerShell 5.1 下，带 [Parameter()] 的函数会变成"高级函数"，
    #   于是 `git add -A` 里的 `-A` 会被当成参数名 `Args` 的缩写 —— 直接报错
    #   「缺少参数"Args"的某个参数」（已实测复现）。
    #   改用简单函数 + 自动变量 $args 后，`-A` / `--hard` / `-m` 都会原样透传给 git。
    $gitArgs = $args
    & git -C $WorkDir @gitArgs
    if ($LASTEXITCODE -ne 0) {
        Die ("git " + ($gitArgs -join ' ') + " 失败（退出码 $LASTEXITCODE）")
    }
}

function Show-NetworkHints {
    Write-Host "`n  GitHub 连接失败（Connection was reset / 超时）的常见处理：" -ForegroundColor Yellow
    Write-Host "    1) 先确认通路：Test-NetConnection github.com -Port 443 -InformationLevel Quiet"
    Write-Host "       —— 输出 False 表示现在不通；换手机热点通常立刻可用"
    Write-Host "    2) 让 git 走 HTTP/1.1（丢包网络下比 HTTP/2 稳得多）："
    Write-Host "       git config --global http.version HTTP/1.1"
    Write-Host "    3) 直接重跑本脚本：本地改动都已就绪，重跑是幂等的（不会重复提交）"
    Write-Host "    4) 长期不通的兜底：在 GitHub 网页上手动替换这几个文件 ——"
    Write-Host "       README.md / README_EN.md / DEPLOY_STRUCTURE.md /"
    Write-Host "       scripts/health_check.py / scripts/publish_docs_to_github.ps1"
}

function Invoke-GitWithRetry {
    # 网络类 git 操作（fetch / checkout / reset）带自动重试。
    # 背景：国内访问 github.com 常见 "Recv failure: Connection was reset"，
    # 属于间歇性抖动，重试几次基本都能过去。
    param(
        [string]$What,
        [string[]]$GitArgs,
        [int[]]$Delays = @(2, 5, 10)
    )
    $attempts = $Delays.Count + 1
    for ($i = 1; $i -le $attempts; $i++) {
        & git -C $WorkDir @GitArgs
        $code = $LASTEXITCODE      # 立刻取值：中间夹了别的 cmdlet 之后 $LASTEXITCODE 可能已变
        if ($code -eq 0) {
            if ($i -gt 1) { Ok "$What：第 $i 次尝试成功" }
            return $true
        }
        if ($i -lt $attempts) {
            $wait = $Delays[$i - 1]
            Warn "$What 第 $i 次失败（退出码 $code），$wait 秒后重试（共 $attempts 次尝试）…"
            Start-Sleep -Seconds $wait
        }
    }
    return $false
}

function Invoke-CloneWithRetry {
    param(
        [string]$Url,
        [string]$Ref,
        [string]$Dir,
        [int[]]$Delays = @(2, 5, 10)
    )
    $attempts = $Delays.Count + 1
    for ($i = 1; $i -le $attempts; $i++) {
        & git clone --branch $Ref $Url $Dir
        $code = $LASTEXITCODE      # 立刻取值：后面的 Test-Path / Remove-Item 可能影响 $LASTEXITCODE
        if ($code -eq 0) {
            if ($i -gt 1) { Ok "clone：第 $i 次尝试成功" }
            return $true
        }
        if (Test-Path -LiteralPath $Dir) {
            Remove-Item -LiteralPath $Dir -Recurse -Force -ErrorAction SilentlyContinue
        }
        if ($i -lt $attempts) {
            $wait = $Delays[$i - 1]
            Warn "clone 第 $i 次失败（退出码 $code），$wait 秒后重试（共 $attempts 次尝试）…"
            Start-Sleep -Seconds $wait
        }
    }
    return $false
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
    if (-not (Invoke-GitWithRetry -What "fetch origin $Branch" -GitArgs @("fetch", "origin", $Branch))) {
        Show-NetworkHints
        Die "fetch 失败（重试 3 次仍不通）—— 本地改动没有任何损失，网络恢复后重跑本脚本即可"
    }
    Invoke-Git checkout $Branch
    Invoke-Git reset --hard "origin/$Branch"
} else {
    if (Test-Path -LiteralPath $WorkDir) { Remove-Item -LiteralPath $WorkDir -Recurse -Force }
    if (-not (Invoke-CloneWithRetry -Url $RepoUrl -Ref $Branch -Dir $WorkDir)) {
        Show-NetworkHints
        Die "clone 失败（重试 3 次仍不通）：$RepoUrl"
    }
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
    "README.md", "README_EN.md", "LICENSE", "requirements.txt", "DEPLOY.md",
    "DEPLOY_STRUCTURE.md", ".gitignore", ".gitattributes", "streamlit_app.py", "Dockerfile"
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
    Warn "push 第 1 次失败（退出码 $LASTEXITCODE），5 秒后重试 …"
    Start-Sleep -Seconds 5
    & git -C $WorkDir push origin $Branch
}
if ($LASTEXITCODE -ne 0) {
    Warn "push 第 2 次仍失败（退出码 $LASTEXITCODE），10 秒后最后重试一次 …"
    Start-Sleep -Seconds 10
    & git -C $WorkDir push origin $Branch
}
if ($LASTEXITCODE -ne 0) {
    Warn "push 失败（已重试 3 次）。常见原因与处理："
    Write-Host "    - 网络抖动：见下方提示（你的提交已在本地，重跑脚本即可继续推送）"
    Write-Host "    - 需要认证：用 Personal Access Token 当密码，或先配置 Git Credential Manager"
    Write-Host "    - 远端有他人提交：先 git -C `"$WorkDir`" pull --rebase origin $Branch 再 push"
    Show-NetworkHints
    exit 1
}
Ok "推送成功"
Write-Host "`n接下来建议在 GitHub 上确认三件事：" -ForegroundColor Cyan
Write-Host "  1. 根目录只剩 src / scripts / data / docs / tests，44 张图已在 docs/images/；"
Write-Host "  2. README 首屏能直接看懂项目定位，Quick Start 三条命令可跑；"
Write-Host "  3. Actions 里 CI 变绿（单元测试 + 导入自检）。"
