$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path $PSScriptRoot -Parent
$outputPath = Join-Path $projectRoot 'OPEN-HANDOFF.html'

$documents = @(
    @{ Id = 'handoff'; Title = '交接入口'; Path = 'HANDOFF.md' },
    @{ Id = 'project-brief'; Title = '项目大纲、进度与前瞻'; Path = 'docs/handoff/PROJECT_BRIEF_ZH.md' },
    @{ Id = 'codex-handover'; Title = '给新电脑 Codex 的工程上下文'; Path = 'docs/handoff/CODEX_HANDOVER.md' },
    @{ Id = 'prompt-playbook'; Title = 'AI 协作与 Prompt 实例'; Path = 'docs/handoff/AI_COLLABORATION_PLAYBOOK_ZH.md' }
)

$sections = foreach ($document in $documents) {
    $sourcePath = Join-Path $projectRoot $document.Path
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Missing handoff document: $($document.Path)"
    }
    $markdown = Get-Content -LiteralPath $sourcePath -Raw -Encoding utf8
    $html = (ConvertFrom-Markdown -InputObject $markdown).Html
    $html = $html.Replace('href="docs/handoff/PROJECT_BRIEF_ZH.md"', 'href="#project-brief"')
    $html = $html.Replace('href="docs/handoff/CODEX_HANDOVER.md"', 'href="#codex-handover"')
    $html = $html.Replace('href="docs/handoff/AI_COLLABORATION_PLAYBOOK_ZH.md"', 'href="#prompt-playbook"')
    $html = $html.Replace('href="HANDOFF.md"', 'href="#handoff"')
    "<section id='$($document.Id)' class='document'><div class='section-label'>$($document.Title)</div>$html</section>"
}

$navigation = foreach ($document in $documents) {
    "<a href='#$($document.Id)'>$($document.Title)</a>"
}

$page = @"
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>走进照片 · 交接资料</title>
  <style>
    :root { color-scheme: light; --ink:#20243a; --muted:#68708a; --line:#dce1ee; --accent:#4557b8; --paper:#fff; --back:#f2f4fa; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; background:var(--back); color:var(--ink); font:16px/1.75 "Microsoft YaHei", "PingFang SC", sans-serif; }
    aside { position:fixed; inset:0 auto 0 0; width:270px; padding:28px 22px; background:#1f2442; color:#fff; overflow:auto; }
    aside h1 { margin:0 0 8px; font-size:24px; }
    aside p { color:#bec6ec; font-size:13px; }
    nav { display:grid; gap:8px; margin-top:24px; }
    nav a { color:#eef1ff; text-decoration:none; padding:10px 12px; border-radius:8px; background:#ffffff0d; }
    nav a:hover { background:#ffffff20; }
    main { max-width:1100px; margin-left:270px; padding:32px 42px 80px; }
    .notice { max-width:920px; margin:0 auto 24px; padding:16px 20px; border:1px solid #cbd4ff; border-radius:12px; background:#eef1ff; }
    .document { max-width:920px; margin:0 auto 30px; padding:38px 46px; border:1px solid var(--line); border-radius:16px; background:var(--paper); box-shadow:0 10px 28px #28335b12; }
    .section-label { color:var(--accent); font-weight:700; letter-spacing:.08em; }
    h1,h2,h3 { line-height:1.35; scroll-margin-top:18px; }
    h1 { margin-top:12px; font-size:32px; }
    h2 { margin-top:34px; padding-bottom:8px; border-bottom:1px solid var(--line); font-size:23px; }
    h3 { margin-top:26px; font-size:19px; }
    a { color:#354bb5; }
    table { width:100%; border-collapse:collapse; display:block; overflow-x:auto; }
    th,td { border:1px solid var(--line); padding:9px 12px; text-align:left; vertical-align:top; min-width:120px; }
    th { background:#f5f6fb; }
    pre { overflow:auto; padding:16px; border-radius:10px; background:#171a2e; color:#eef1ff; line-height:1.55; }
    code { font-family:Consolas, monospace; }
    blockquote { margin:16px 0; padding:4px 18px; border-left:4px solid #8897e5; color:#46506d; background:#f8f9ff; }
    @media (max-width:850px) { aside { position:static; width:auto; } main { margin:0; padding:20px 12px 50px; } .document { padding:24px 20px; } }
    @media print { aside { display:none; } main { margin:0; padding:0; } .document { box-shadow:none; page-break-before:always; border:0; } .document:first-of-type { page-break-before:auto; } }
  </style>
</head>
<body>
  <aside><h1>走进照片</h1><p>离线交接阅读页。无需网络，点击目录在本页跳转。</p><nav>$($navigation -join "`n")</nav></aside>
  <main>
    <div class="notice"><strong>使用方法：</strong>解压交接包后，双击本文件。GitHub 上仍以原始 Markdown 文档为准；本页是为了避免本地浏览器把相对路径误当成网站。</div>
    $($sections -join "`n")
  </main>
</body>
</html>
"@

Set-Content -LiteralPath $outputPath -Value $page -Encoding utf8
Write-Output "READER=$outputPath"
