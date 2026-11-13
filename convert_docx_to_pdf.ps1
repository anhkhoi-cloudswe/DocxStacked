$docxFiles = @(
    "c:\AK\PET_PROJECTS\DocxStacked\data\output\PRM392\PRM392 - SP 2024 - FE.docx",
    "c:\AK\PET_PROJECTS\DocxStacked\data\output\PRM392\PRM392 - SU25 - FE.docx",
    "c:\AK\PET_PROJECTS\DocxStacked\data\output\PRM392\PRM392 - SP26 - RE.docx"
)

$word = New-Object -ComObject Word.Application
$word.Visible = $false

try {
    foreach ($file in $docxFiles) {
        if (Test-Path $file) {
            $pdfPath = [System.IO.Path]::ChangeExtension($file, ".pdf")
            Write-Host "Converting $file -> $pdfPath"
            $doc = $word.Documents.Open($file, $false, $true)
            $doc.ExportAsFixedFormat($pdfPath, 17) # 17 = wdExportFormatPDF
            $doc.Close(0)
            Write-Host "Success: $pdfPath"
        }
    }
} finally {
    $word.Quit()
}
