# Budżet domowy – odczyt tekstu z paragonu wbudowanym w Windows 10/11 silnikiem Windows.Media.Ocr.
# Użycie:  ocr-win.ps1 <plik>              -> JSON {"lines":[{text,x,y,w,h}]} (współrzędne 0..1, od lewego górnego rogu)
#          ocr-win.ps1 -Preview <plik> <jpg> -> podgląd JPG (też z PDF i HEIC, jeśli Windows umie go otworzyć)
#          ocr-win.ps1 -Check               -> "ok", gdy odczyt tekstu jest dostępny
param([switch]$Check, [switch]$Preview, [string]$Path, [string]$Out)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]

$asTaskOp = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAct = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$type) { $t = $asTaskOp.MakeGenericMethod($type).Invoke($null, @($op)); $null = $t.Wait(-1); $t.Result }
function AwaitAction($op) { $t = $asTaskAct.Invoke($null, @($op)); $null = $t.Wait(-1) }

function Get-Engine {
    $pl = New-Object Windows.Globalization.Language 'pl'
    if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($pl)) { return [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($pl) }
    return [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}

if ($Check) { if (Get-Engine) { 'ok'; exit 0 } else { 'brak'; exit 1 } }

# obrazy do odczytu: strony PDF albo zdjęcie (z uwzględnieniem obrotu zapisanego w EXIF)
function Get-Bitmaps([string]$file) {
    $sf = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($file)) ([Windows.Storage.StorageFile])
    $streams = @()
    if ($file.ToLower().EndsWith('.pdf')) {
        $doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($sf)) ([Windows.Data.Pdf.PdfDocument])
        for ($i = 0; $i -lt [Math]::Min($doc.PageCount, 5); $i++) {
            $page = $doc.GetPage($i)
            $opt = New-Object Windows.Data.Pdf.PdfPageRenderOptions
            $scale = [Math]::Max(1.0, 2400.0 / [Math]::Max($page.Size.Width, $page.Size.Height))
            $opt.DestinationWidth = [uint32]($page.Size.Width * $scale)
            $opt.DestinationHeight = [uint32]($page.Size.Height * $scale)
            $ms = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
            AwaitAction ($page.RenderToStreamAsync($ms, $opt))
            $streams += $ms
        }
    } else {
        $streams += Await ($sf.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    }
    foreach ($s in $streams) {
        $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($s)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $tr = New-Object Windows.Graphics.Imaging.BitmapTransform
        $w = $dec.OrientedPixelWidth; $h = $dec.OrientedPixelHeight
        $max = [Math]::Min(4000, [Windows.Media.Ocr.OcrEngine]::MaxImageDimension)
        if ([Math]::Max($w, $h) -gt $max) {
            $k = $max / [Math]::Max($w, $h)
            $tr.ScaledWidth = [uint32]($dec.PixelWidth * $k); $tr.ScaledHeight = [uint32]($dec.PixelHeight * $k)
            $tr.InterpolationMode = [Windows.Graphics.Imaging.BitmapInterpolationMode]::Fant
        }
        Await ($dec.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied, $tr,
            [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation, [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    }
}

if ($Preview) {
    $bmp = @(Get-Bitmaps $Path)[0]
    $null = New-Item -ItemType File -Force -Path $Out
    $of = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path $Out).Path)) ([Windows.Storage.StorageFile])
    $os = Await ($of.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
    $enc = Await ([Windows.Graphics.Imaging.BitmapEncoder]::CreateAsync([Windows.Graphics.Imaging.BitmapEncoder]::JpegEncoderId, $os)) ([Windows.Graphics.Imaging.BitmapEncoder])
    $enc.SetSoftwareBitmap($bmp)
    $big = [Math]::Max($bmp.PixelWidth, $bmp.PixelHeight)
    if ($big -gt 2400) { $k = 2400.0 / $big; $enc.BitmapTransform.ScaledWidth = [uint32]($bmp.PixelWidth * $k); $enc.BitmapTransform.ScaledHeight = [uint32]($bmp.PixelHeight * $k) }
    AwaitAction ($enc.FlushAsync())
    $os.Dispose()
    exit 0
}

$engine = Get-Engine
if (-not $engine) { [Console]::Error.WriteLine('Brak silnika OCR (dodaj język polski w Ustawieniach).'); exit 3 }
$lines = New-Object System.Collections.ArrayList
$page = 0
foreach ($bmp in @(Get-Bitmaps $Path)) {
    $W = [double]$bmp.PixelWidth; $H = [double]$bmp.PixelHeight
    $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    foreach ($ln in $res.Lines) {
        foreach ($wd in $ln.Words) {
            $r = $wd.BoundingRect
            $null = $lines.Add([ordered]@{ text = $wd.Text; x = $r.X / $W; y = $page + $r.Y / $H; w = $r.Width / $W; h = $r.Height / $H })
        }
    }
    $page++
}
$json = @{ lines = $lines; engine = 'windows' } | ConvertTo-Json -Depth 4 -Compress
[Console]::Out.Write($json)
