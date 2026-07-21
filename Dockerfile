# 使用輕量級的 Python 3.10 slim 映像檔
FROM python:3.10-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數，防止 Python 產生 .pyc 檔案並強制輸出標準輸出
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py

# 先複製 requirements.txt 以利用 Docker 的快取機制
COPY requirements.txt .

# 安裝套件 (Pandas 等套件會在這裡安裝)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 複製專案內的所有程式碼到容器內
COPY . .

# 建立必要的資料夾 (確保容器內有這些路徑)
RUN mkdir -p history uploads logs backups

# 暴露 Flask 預設運行的 5001 port
EXPOSE 5001

# 啟動應用程式 (若為正式生產環境，建議改用 gunicorn)
CMD ["python", "app.py"]