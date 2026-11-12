@echo off
chcp 65001 >nul
echo ======================================================================
echo    GOM ĐỀ (gomde) — HỆ THỐNG BIÊN SOẠN ĐỀ THI ÔN TẬP SINH VIÊN FPT
echo ======================================================================
echo Đang khởi động Backend API (Port 8000) và Frontend React (Port 5173)...

REM 1. Khởi chạy Backend FastAPI trong cửa sổ riêng
start "Gom De Backend API" cmd /k "call .venv\Scripts\activate.bat && python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload"

REM 2. Khởi chạy Frontend Vite trong cửa sổ riêng
start "Gom De Frontend React" cmd /k "cd frontend && npm run dev"

echo.
echo Đã khởi động xong hai dịch vụ:
echo   - Backend API:  http://127.0.0.1:8000  (Tài liệu: http://127.0.0.1:8000/docs)
echo   - Frontend App: http://localhost:5173
echo.
echo Tự động mở trình duyệt sau 3 giây...
timeout /t 3 /nobreak >nul
start http://localhost:5173

