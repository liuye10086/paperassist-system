param(
  [Parameter(Mandatory=$true)][string]$DocumentPath,
  [Parameter(Mandatory=$true)][string]$OutputDirectory
)
# Word's page metafiles give visual QA without producing a PDF intermediate.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$reportPath=(Resolve-Path -LiteralPath $DocumentPath).Path
$previewPath=[System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $previewPath -Force | Out-Null
$wordApp=$null
$wordDoc=$null
try {
  $wordApp=New-Object -ComObject Word.Application
  $wordApp.Visible=$false
  $wordApp.DisplayAlerts=0
  $wordDoc=$wordApp.Documents.Open($reportPath,$false,$true,$false)
  $wordDoc.Repaginate()
  $wordDoc.ActiveWindow.View.Type=3
  $pageCount=$wordDoc.ComputeStatistics(2)
  for ($pageIndex=1; $pageIndex -le $pageCount; $pageIndex++) {
    $page=$wordDoc.ActiveWindow.ActivePane.Pages.Item($pageIndex)
    [byte[]]$emf=$page.EnhMetaFileBits
    $stream=[System.IO.MemoryStream]::new($emf,$false)
    $metafile=[System.Drawing.Imaging.Metafile]::new($stream)
    $bitmap=[System.Drawing.Bitmap]::new(1240,1754)
    $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.Clear([System.Drawing.Color]::White)
      $graphics.DrawImage($metafile,[System.Drawing.Rectangle]::new(0,0,1240,1754))
      $bitmap.Save((Join-Path $previewPath ('page-'+$pageIndex+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $graphics.Dispose(); $bitmap.Dispose(); $metafile.Dispose(); $stream.Dispose() }
  }
  Write-Output ('Word pages rendered directly to PNG: '+$pageCount)
} finally {
  if ($null -ne $wordDoc) { $wordDoc.Close(0) }
  if ($null -ne $wordApp) { $wordApp.Quit() }
}
