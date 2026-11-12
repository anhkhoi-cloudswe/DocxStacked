# start.ps1 - Khởi động Gom Đề (Backend FastAPI + Frontend React)
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   GOM ĐỀ (gomde) — HỆ THỐNG BIÊN SOẠN ĐỀ THI ÔN TẬP SINH VIÊN FPT   " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

$backendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/k call .venv\Scripts\activate.bat && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload" -PassThru
$frontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/k cd frontend && npm run dev" -PassThru

Start-Sleep -Seconds 3

Write-Host "`nĐã khởi động thành công:" -ForegroundColor Green
Write-Host "  - Backend API:  http://127.0.0.1:8000 (Tài liệu API: http://127.0.0.1:8000/docs)" -ForegroundColor Yellow
Write-Host "  - Frontend App: http://localhost:5173" -ForegroundColor Yellow

Start-Process "http://localhost:5173"

