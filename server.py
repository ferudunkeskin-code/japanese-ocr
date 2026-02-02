import sys
from pathlib import Path

# Proje kökünü Python path'e ekle (production uyumlu)
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
import io
import fitz  # PyMuPDF
import base64
from PIL import Image
import tempfile
import os
import logging
from typing import Optional

# Logging ayarı
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger("furijapan")

# --------- AI CLIENT IMPORT (MOCK YOK) ---------
try:
    from app.llm.client import AIClient
    logger.info("AIClient başarıyla yüklendi.")
except ImportError as e:
    logger.critical("AIClient import edilemedi! OCR ve AI çalışmayacak.")
    raise e  # ÇÖKMEK İYİDİR → gizli mock istemiyoruz

# --------- FASTAPI ---------
app = FastAPI()

# --------- GLOBAL EXCEPTION HANDLER ---------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": f"Sunucu hatası: {str(exc)}"}
    )

# --------- APP STATE ---------
state = {
    "current_pdf": None,
    "current_image": None,
    "is_pdf": False,
    "total_pages": 0,
    "temp_file_path": None,
    "current_filename": None
}


def cleanup_temp_files():
    """Geçici dosyaları temizle"""
    if state["temp_file_path"] and os.path.exists(state["temp_file_path"]):
        try:
            os.unlink(state["temp_file_path"])
        except Exception as e:
            logger.error(f"Temp file cleanup error: {e}")
        state["temp_file_path"] = None
    
    # Eski PDF'i kapat
    if state["current_pdf"]:
        try:
            state["current_pdf"].close()
        except:
            pass
        state["current_pdf"] = None

@app.on_event("startup")
async def startup_event():
    """Uygulama başlarken state'i temizle"""
    cleanup_temp_files()
    state.update({
        "current_pdf": None,
        "current_image": None,
        "is_pdf": False,
        "total_pages": 0,
        "temp_file_path": None,
        "current_filename": None
    })

@app.on_event("shutdown")
def shutdown_event():
    """Uygulama kapanırken temizlik yap"""
    cleanup_temp_files()

@app.get("/", response_class=HTMLResponse)
def home():
    return """

<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>FuriJapan OCR</title>
<style>
    body { 
    font-family:'Segoe UI', sans-serif; 
    margin:0; 
    background:#f0f2f5; 
    /* EKLEMEN GEREKENLER: */
    word-wrap: break-word; 
    overflow-wrap: break-word;
    line-height: 1.6;
    }
    .header { background:#2c3e50; color:white; padding:15px; text-align:center; font-size:20px; }
    .container { max-width: 800px; margin: 20px auto; padding:20px; background:white; border-radius:8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
    .upload-section { 
        border: 2px dashed #3498db; 
        padding: 20px; 
        text-align: center; 
        margin-bottom: 20px; 
        border-radius: 8px;
        cursor: pointer;
        transition: all 0.3s ease;
        position: relative;
        min-height: 120px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .upload-section:hover { 
        background: #f8f9fa; 
        border-color: #2980b9;
    }
    .upload-section.dragover {
        background: #e8f4fc;
        border-color: #1abc9c;
        border-style: solid;
    }
    .upload-section i {
        font-size: 40px;
        color: #3498db;
        margin-bottom: 10px;
    }
    .upload-hint {
        font-size: 12px;
        color: #666;
        margin-top: 10px;
        padding: 5px 10px;
        background: #f1f8ff;
        border-radius: 4px;
        border: 1px dashed #b3d7ff;
    }
    button { cursor: pointer; background: #3498db; color: white; border: none; padding: 10px 20px; border-radius: 4px; margin: 5px 2px; }
    button:hover { background: #2980b9; }
    textarea { width: 100%; margin-top: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; resize: both; }
    #question { height: 60px; }
    #pdfArea { width: 100%; min-height: 300px; background:#eee; display: flex; justify-content: center; overflow: auto; border: 1px solid #ddd; }
    #pdfArea img { max-width: 100%; height: auto; max-height: 600px; }
    .nav-controls { display: flex; justify-content: center; align-items: center; margin: 10px 0; gap: 15px; }
    #loader { display:none; color:#e67e22; font-weight: bold; text-align: center; }
    #statusBar { position:fixed; bottom:0; width:100%; background:#2c3e50; color:white; padding:5px; text-align:center; font-size:12px; }
    .file-info { background:#f8f9fa; padding:10px; border-radius:4px; margin:10px 0; font-size:14px; }
    .error-message { background:#e74c3c; color:white; padding:10px; border-radius:4px; margin:10px 0; display:none; }
    .success-message { background:#27ae60; color:white; padding:10px; border-radius:4px; margin:10px 0; display:none; }
    #pastePreview { 
        max-width: 200px; 
        max-height: 150px; 
        margin-top: 10px;
        border: 1px solid #ddd;
        border-radius: 4px;
        display: none;
    }
    .paste-indicator {
        position: absolute;
        top: 10px;
        right: 10px;
        background: #3498db;
        color: white;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 11px;
        display: none;
    }
    .audio-controls {
        display: flex;
        gap: 5px;
        margin-top: 10px;
        flex-wrap: wrap;
        justify-content: center;
    }
    .audio-controls button {
        flex: 1;
        min-width: 80px;
    }
    .play-btn { background: #27ae60; }
    .play-btn:hover { background: #219653; }
    .pause-btn { background: #f39c12; }
    .pause-btn:hover { background: #e67e22; }
    .stop-btn { background: #e74c3c; }
    .stop-btn:hover { background: #c0392b; }
    .download-btn { background: #8e44ad; }
    .download-btn:hover { background: #7d3c98; }
    .audio-status {
        text-align: center;
        margin: 5px 0;
        font-size: 12px;
        color: #666;
    }
    .progress-bar {
        width: 100%;
        height: 4px;
        background: #ddd;
        border-radius: 2px;
        margin-top: 5px;
        overflow: hidden;
        display: none;
    }
    .progress-fill {
        height: 100%;
        background: #3498db;
        width: 0%;
        transition: width 0.1s linear;
    }
.action-buttons {
    display: flex;            /* Grid yerine Flex kullanıyoruz */
    gap: 8px;                 /* Butonlar arası boşluk */
    margin-top: 10px;
    width: 100%;              /* Satırı tam kapla */
}

.action-buttons button {
    flex: 1;                  /* Tüm butonlara eşit genişlik ver */
    white-space: nowrap;      /* Metinlerin alt satıra kaymasını engeller */
    padding: 10px 5px;        /* İç boşluk */
    font-size: 14px;          /* Gerekirse yazıyı biraz küçültün */
}
    .furigana-btn {
        background: #d35400;
    }
    .furigana-btn:hover {
        background: #e67e22;
    }
    .furigana-text {
        background: #fff9e6;
        border: 1px solid #f1c40f;
        padding: 10px;
        border-radius: 4px;
        margin-top: 10px;
        font-family: 'MS Gothic', 'Hiragino Kaku Gothic Pro', 'Meiryo', sans-serif;
        line-height: 1.8;
        white-space: pre-wrap;
        display: none;
        font-size: 16px;
    }
    .furigana-text ruby {
        ruby-align: center;
    }
    .furigana-text rt {
        font-size: 0.7em;
        color: #666;
        opacity: 0.8;
        font-weight: normal;
    }
    ruby {
        ruby-align: center;
    }
    rt {
        font-size: 0.7em;
        color: #666;
        opacity: 0.8;
        font-weight: normal;
    }
</style>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
</head>
<body>
<div class="header">FuriJapan AI Tool</div>
<div class="container">
    <div class="error-message" id="errorMessage"></div>
    <div class="success-message" id="successMessage"></div>
    
    <div class="upload-section" id="uploadArea">
        <div class="paste-indicator" id="pasteIndicator">Yapıştırmak için Ctrl+V</div>
        <i class="fas fa-cloud-upload-alt"></i>
        <input type="file" id="docInput" accept="application/pdf,image/*" style="display: none;" capture="environment">
        <p style="font-size: 16px; margin-bottom: 5px;"><strong>PDF veya Resim Yükleyin</strong></p>
        <p style="font-size: 14px; color: #555; margin-bottom: 10px;">
            Dosya seçmek için tıklayın<br>
            veya ekran görüntüsünü yapıştırın (Ctrl+V)
        </p>
        <div class="upload-hint">
            Desteklenen formatlar: PDF, PNG, JPG, GIF, BMP
        </div>
        <img id="pastePreview" alt="Yapıştırılan resim önizlemesi">
    </div>
    
    <div class="file-info">
        <div id="fileInfo">Yüklenen dosya: Yok</div>
        <div id="pageCount" style="display:none;">Toplam Sayfa: <span id="totalPages">0</span></div>
    </div>
    <div id="loader">⏳ İşleniyor...</div>
    <div class="nav-controls" id="pagination" style="display:none;">
        <button onclick="prevPage()"><i class="fas fa-chevron-left"></i> Geri</button>
        <span id="pageInfo">0 / 0</span>
        <button onclick="nextPage()">İleri <i class="fas fa-chevron-right"></i></button>
    </div>
    <div id="pdfArea"><img id="pageImg" style="display:none;"></div>
    
    <div class="action-buttons">
        <button onclick="ocrPage()" style="background:#27ae60;">
            <i class="fas fa-text-height"></i> OCR Yap
        </button>
        <button onclick="addFurigana()" style="background:#2980b9;">
            <i class="fas fa-language"></i> Furigana Ekle
        </button>
        <button onclick="addFuriganaPlus()" style="background:#8e44ad;">
            <i class="fas fa-plus-circle"></i> Furigana Plus
        </button>
    </div>

    <textarea id="source" placeholder="OCR Metni buraya gelecek..." rows="6"></textarea>
    <div class="furigana-text" id="furiganaText"></div>
    
    <textarea id="question" placeholder="AI'ye soru sor (Örn: Bu metni Türkçeye çevir)" rows="3"></textarea>
    <button onclick="askAI()" style="width:100%;">
        <i class="fas fa-robot"></i> AI'ye Sor
    </button>
    <textarea id="answer" placeholder="AI Yanıtı..." rows="6"></textarea>
    
    <!-- Ses Kontrolleri -->
    <div class="audio-controls">
        <button class="play-btn" onclick="playSpeech()">
            <i class="fas fa-play"></i> Oynat
        </button>
        <button class="pause-btn" onclick="pauseSpeech()">
            <i class="fas fa-pause"></i> Duraklat
        </button>
        <button class="stop-btn" onclick="stopSpeech()">
            <i class="fas fa-stop"></i> Durdur
        </button>
        <button class="download-btn" onclick="downloadAudio()">
            <i class="fas fa-download"></i> İndir
        </button>
        <button class="replay-btn" onclick="replaySpeech()" style="background:#3498db;">
            <i class="fas fa-redo"></i> Yeniden Oynat
        </button>
    </div>
    <div class="audio-status" id="audioStatus">Hazır</div>
    <div class="progress-bar" id="progressBar">
        <div class="progress-fill" id="progressFill"></div>
    </div>
    
    <button onclick="downloadText()" style="background:#95a5a6; width:100%; margin-top:10px;">
        <i class="fas fa-download"></i> Metni İndir
    </button>
    <button onclick="downloadFurigana()" style="background:#d35400; width:100%; margin-top:5px; display:none;" id="downloadFuriganaBtn">
        <i class="fas fa-download"></i> Furigana Metnini İndir
    </button>
</div>
<div id="statusBar">Hazır</div>

<!-- Gizli ses elementi -->
<audio id="audioPlayer" style="display: none;"></audio>

<script>
let totalPages = 0;
let currentPage = 0;
let currentFileName = "";
let isPasteMode = false;
let audioCache = null; // Ses önbelleği
let currentAudioText = ""; // Şu anki sesin metni
let audioPlayer = document.getElementById('audioPlayer');
let currentIsPdf = false; // PDF mi değil mi bilgisini tut
let furiganaResult = ""; // Furigana sonucunu sakla

// Audio olay dinleyicileri
audioPlayer.addEventListener('timeupdate', updateProgressBar);
audioPlayer.addEventListener('ended', function() {
    document.getElementById('audioStatus').innerText = "Oynatma tamamlandı";
    document.getElementById('progressBar').style.display = 'none';
});

// Simüle edilmiş Font Awesome için fallback
if (!document.querySelector('link[href*="font-awesome"]')) {
    const style = document.createElement('style');
    style.textContent = `
        .fas:before { content: "▲"; }
        .fa-cloud-upload-alt:before { content: "📁"; }
        .fa-text-height:before { content: "📝"; }
        .fa-robot:before { content: "🤖"; }
        .fa-play:before { content: "▶"; }
        .fa-pause:before { content: "⏸"; }
        .fa-stop:before { content: "⏹"; }
        .fa-download:before { content: "⬇"; }
        .fa-redo:before { content: "↻"; }
        .fa-language:before { content: "あ"; }
        .fa-chevron-left:before { content: "←"; }
        .fa-chevron-right:before { content: "→"; }
    `;
    document.head.appendChild(style);
}

function showError(message) {
    const errorDiv = document.getElementById("errorMessage");
    errorDiv.innerText = message;
    errorDiv.style.display = "block";
    setTimeout(() => {
        errorDiv.style.display = "none";
    }, 5000);
}

function showSuccess(message) {
    const successDiv = document.getElementById("successMessage");
    successDiv.innerText = message;
    successDiv.style.display = "block";
    setTimeout(() => {
        successDiv.style.display = "none";
    }, 3000);
}

function setStatus(msg){ 
    document.getElementById("statusBar").innerText = msg; 
    console.log("Status:", msg);
}

function showLoader(v){ 
    document.getElementById("loader").style.display = v ? "block" : "none"; 
}

function updateFileInfo() {
    const fileInput = document.getElementById("docInput");
    const fileInfo = document.getElementById("fileInfo");
    const pageCountDiv = document.getElementById("pageCount");
    
    if(fileInput.files[0] || currentFileName) {
        fileInfo.innerHTML = `Yüklenen dosya: <strong>${currentFileName}</strong>`;
        if(totalPages > 0) {
            pageCountDiv.style.display = "block";
            document.getElementById("totalPages").innerText = totalPages;
        } else {
            pageCountDiv.style.display = "none";
        }
    } else {
        fileInfo.innerHTML = "Yüklenen dosya: Yok";
        pageCountDiv.style.display = "none";
    }
}

// Dosya adı oluşturma yardımcı fonksiyonu
function generateFileName(baseName, extension, includePageNumber = true) {
    let fileName = baseName;
    
    // Uzantıyı kaldır
    fileName = fileName.replace(/\.[^/.]+$/, "");
    
    // Eğer PDF ise ve birden fazla sayfa varsa sayfa numarasını ekle
    if (includePageNumber && currentIsPdf && totalPages > 1) {
        fileName += `_s${currentPage + 1}`; // s1, s2, s3 şeklinde
    }
    
    // Ek uzantıyı ekle
    fileName += extension;
    
    return fileName;
}

// İlerleme çubuğunu güncelle
function updateProgressBar() {
    const progressBar = document.getElementById('progressBar');
    const progressFill = document.getElementById('progressFill');
    
    if (audioPlayer.duration > 0) {
        const percent = (audioPlayer.currentTime / audioPlayer.duration) * 100;
        progressFill.style.width = percent + '%';
        
        // Süre bilgisini göster
        const currentTime = formatTime(audioPlayer.currentTime);
        const totalTime = formatTime(audioPlayer.duration);
        document.getElementById('audioStatus').innerText = 
            `Oynatılıyor: ${currentTime} / ${totalTime}`;
    }
}

// Saniyeyi dakika:saniye formatına çevir
function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
}

// Yapıştırma işlevselliği
document.addEventListener('DOMContentLoaded', function() {
    const uploadArea = document.getElementById('uploadArea');
    const pasteIndicator = document.getElementById('pasteIndicator');
    const pastePreview = document.getElementById('pastePreview');
    
    // Upload alanına tıklanınca file input'u tetikle
    uploadArea.addEventListener('click', function(e) {
        if (e.target.id !== 'docInput' && !isPasteMode) {
            document.getElementById('docInput').click();
        }
    });
    
    // Ctrl tuşuna basıldığında paste indicator'ı göster
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            pasteIndicator.style.display = 'block';
            uploadArea.classList.add('dragover');
        }
    });
    
    // Ctrl tuşu bırakıldığında paste indicator'ı gizle
    document.addEventListener('keyup', function(e) {
        if (!e.ctrlKey && !e.metaKey) {
            pasteIndicator.style.display = 'none';
            uploadArea.classList.remove('dragover');
        }
    });
    
    // Paste (yapıştır) event'ini dinle
    document.addEventListener('paste', async function(e) {
        // Sadece upload alanı aktifse veya Ctrl+V ile
        if (e.clipboardData && (e.clipboardData.types.includes('Files') || e.clipboardData.items)) {
            e.preventDefault();
            
            // Pano verilerini al
            const items = e.clipboardData.items;
            let imageFile = null;
            
            // Resim dosyalarını ara
            for (let item of items) {
                if (item.type.indexOf('image') !== -1) {
                    const blob = item.getAsFile();
                    if (blob) {
                        imageFile = new File([blob], `pasted_image_${Date.now()}.png`, {
                            type: 'image/png',
                            lastModified: Date.now()
                        });
                        break;
                    }
                }
            }
            
            if (imageFile) {
                isPasteMode = true;
                setStatus("Yapıştırılan resim işleniyor...");
                
                // Önizleme göster
                const reader = new FileReader();
                reader.onload = function(event) {
                    pastePreview.src = event.target.result;
                    pastePreview.style.display = 'block';
                    uploadArea.querySelector('i').style.display = 'none';
                    uploadArea.querySelector('p').innerHTML = '<strong>Resim yapıştırıldı!</strong><br>Yüklemek için tıklayın';
                };
                reader.readAsDataURL(imageFile);
                
                // Upload alanını tıklanabilir yap ve dosyayı yükle
                uploadArea.style.cursor = 'pointer';
                uploadArea.onclick = async function() {
                    await uploadFile(imageFile, true);
                    // Reset
                    pastePreview.style.display = 'none';
                    uploadArea.querySelector('i').style.display = 'block';
                    uploadArea.querySelector('p').innerHTML = 
                        '<strong>PDF veya Resim Yükleyin</strong><br>Dosya seçmek için tıklayın<br>veya ekran görüntüsünü yapıştırın (Ctrl+V)';
                    uploadArea.onclick = null;
                    isPasteMode = false;
                };
                
                showSuccess("Resim başarıyla yapıştırıldı! Yüklemek için tıklayın.");
            } else {
                showError("Panoda resim bulunamadı. Lütfen ekran görüntüsü kopyalayın.");
            }
        }
    });
    
    // Dosya seçildiğinde
    document.getElementById('docInput').addEventListener('change', function(e) {
        if (this.files[0]) {
            uploadDoc();
        }
    });
    
    updateFileInfo();
});

// Dosya yükleme fonksiyonu (hem normal hem paste için)
async function uploadFile(file, isPasted = false) {
    try {
        showLoader(true);
        setStatus("Dosya yükleniyor...");
        
        // Temizlik
        document.getElementById("pageImg").style.display = "none";
        document.getElementById("pageImg").src = "";
        document.getElementById("source").value = "";
        document.getElementById("answer").value = "";
        document.getElementById("pagination").style.display = "none";
        document.getElementById("furiganaText").style.display = "none";
        document.getElementById("downloadFuriganaBtn").style.display = "none";
        totalPages = 0;
        currentPage = 0;
        
        // Ses önbelleğini temizle
        audioCache = null;
        currentAudioText = "";
        furiganaResult = "";
        
        if (isPasted) {
            currentFileName = `yapıştırılan_resim_${Date.now()}.png`;
        } else {
            currentFileName = file.name;
        }
        
        updateFileInfo();

        let form = new FormData();
        form.append("file", file);

        setStatus("Sunucuya gönderiliyor...");
        let res = await fetch("/upload-doc", {method:"POST", body:form});
        
        // Yanıtı text olarak al ve JSON mu kontrol et
        const responseText = await res.text();
        
        if(!res.ok) {
            // HTML hatası mı kontrol et
            if(responseText.trim().startsWith("<!DOCTYPE") || responseText.trim().startsWith("<html")) {
                showError("Sunucu hatası: HTML yanıt alındı. Lütfen tekrar deneyin.");
                throw new Error("HTML hatası alındı");
            }
            
            try {
                const errorData = JSON.parse(responseText);
                throw new Error(errorData.detail || "Yükleme başarısız");
            } catch {
                throw new Error(responseText || "Yükleme başarısız");
            }
        }
        
        // Başarılı yanıt
        let data;
        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error("Geçersiz JSON yanıtı");
        }

        if(data.pages) {
            totalPages = data.pages;
            currentPage = 0;
            currentIsPdf = data.is_pdf; // PDF mi değil mi bilgisini kaydet
            
            // PDF ise navigasyonu göster, değilse (resimse) gizle
            document.getElementById("pagination").style.display = data.is_pdf ? "flex" : "none";
            
            await updatePage();
            setStatus(`"${currentFileName}" başarıyla yüklendi.`);
            showSuccess(`"${currentFileName}" başarıyla yüklendi!`);
        } else {
            throw new Error("Sayfa bilgisi alınamadı");
        }
    } catch(e) { 
        console.error("Yükleme hatası:", e);
        setStatus("Hata: " + e.message); 
        showError("Yükleme hatası: " + e.message);
    } finally { 
        showLoader(false);
        updateFileInfo();
    }
}

// Orijinal uploadDoc fonksiyonu (file input için)
async function uploadDoc(){
    const fileInput = document.getElementById("docInput");
    if(!fileInput.files[0]) {
        setStatus("Lütfen bir dosya seçin!");
        return;
    }
    
    await uploadFile(fileInput.files[0], false);
}

async function updatePage(){
    if (totalPages === 0) {
        setStatus("Gösterilecek sayfa yok");
        return;
    }
    
    try {
        setStatus("Sayfa getiriliyor...");
        // Cache buster
        const v = new Date().getTime(); 
        let res = await fetch(`/page/${currentPage}?v=${v}`);
        
        // Yanıtı text olarak al
        const responseText = await res.text();
        
        if(!res.ok) {
            // HTML hatası mı kontrol et
            if(responseText.trim().startsWith("<!DOCTYPE") || responseText.trim().startsWith("<html")) {
                showError("Sayfa yükleme hatası: HTML yanıt alındı.");
                throw new Error("HTML hatası alındı");
            }
            
            try {
                const errorData = JSON.parse(responseText);
                throw new Error(errorData.detail || "Sayfa alınamadı");
            } catch {
                throw new Error(responseText || "Sayfa alınamadı");
            }
        }
        
        // Başarılı yanıt
        let data;
        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error("Geçersiz JSON yanıtı");
        }

        if(data.image) {
            const imgElement = document.getElementById("pageImg");
            imgElement.src = "data:image/png;base64," + data.image;
            imgElement.style.display = "block";
            document.getElementById("pageInfo").innerText = (currentPage + 1) + " / " + totalPages;
            setStatus("Hazır");
        } else {
            throw new Error("Görüntü verisi alınamadı");
        }
    } catch(e) {
        console.error("Sayfa güncelleme hatası:", e);
        setStatus("Sayfa yüklenemedi");
        showError("Sayfa yükleme hatası: " + e.message);
    }
}

function nextPage(){ 
    if(currentPage < totalPages - 1){ 
        currentPage++; 
        updatePage(); 
    }
}

function prevPage(){ 
    if(currentPage > 0){ 
        currentPage--; 
        updatePage(); 
    }
}

async function ocrPage(){
    if(totalPages === 0) {
        setStatus("Önce bir dosya yükleyin!");
        return;
    }
    
    try {
        showLoader(true);
        setStatus("OCR yapılıyor...");
        let form = new FormData();
        form.append("page_num", currentPage.toString());
        let res = await fetch("/ocr-page", {method:"POST", body:form});
        
        // Yanıtı text olarak al
        const responseText = await res.text();
        
        if(!res.ok) {
            // HTML hatası mı kontrol et
            if(responseText.trim().startsWith("<!DOCTYPE") || responseText.trim().startsWith("<html")) {
                showError("OCR hatası: HTML yanıt alındı.");
                throw new Error("HTML hatası alındı");
            }
            
            try {
                const errorData = JSON.parse(responseText);
                throw new Error(errorData.detail || "OCR işlemi başarısız");
            } catch {
                throw new Error(responseText || "OCR işlemi başarısız");
            }
        }
        
        // Başarılı yanıt
        let data;
        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error("Geçersiz JSON yanıtı");
        }
        
        document.getElementById("source").value = data.text || "OCR metni bulunamadı";
        setStatus("OCR tamamlandı.");
        showSuccess("OCR başarıyla tamamlandı!");
        
        // Furigana metnini temizle
        document.getElementById("furiganaText").style.display = "none";
        document.getElementById("downloadFuriganaBtn").style.display = "none";
    } catch(e) { 
        console.error("OCR hatası:", e);
        setStatus("OCR hatası: " + e.message); 
        showError("OCR hatası: " + e.message);
    }
    finally { 
        showLoader(false); 
    }
}

// Furigana ekleme fonksiyonu - <ruby> tag'i kullanarak
async function addFurigana() {
    const sourceText = document.getElementById("source").value;
    if(!sourceText.trim()) {
        setStatus("Furigana eklemek için metin yok!");
        showError("Furigana eklemek için metin yok!");
        return;
    }

    try {
        showLoader(true);
        setStatus("Furigana ekleniyor...");

        let form = new FormData();
        form.append("text", sourceText);

        let res = await fetch("/furigana", {method:"POST", body:form});

        const responseText = await res.text();

        if(!res.ok) {
            try {
                const errorData = JSON.parse(responseText);
                throw new Error(errorData.detail || "Furigana ekleme başarısız");
            } catch {
                throw new Error(responseText || "Furigana ekleme başarısız");
            }
        }

        let data = JSON.parse(responseText);

        furiganaResult = data.html || "Furigana eklenemedi";

        const furiganaElement = document.getElementById("furiganaText");
        furiganaElement.innerHTML = furiganaResult;
        furiganaElement.style.display = "block";

        document.getElementById("downloadFuriganaBtn").style.display = "block";

        setStatus("Furigana eklendi.");
        showSuccess("Furigana başarıyla eklendi!");

    } catch(e) {
        console.error("Furigana ekleme hatası:", e);
        setStatus("Furigana hatası: " + e.message);
        showError("Furigana hatası: " + e.message);
    } finally { 
        showLoader(false); 
    }
}
async function addFuriganaPlus() {
    const sourceText = document.getElementById("source").value;
    if(!sourceText.trim()) {
        setStatus("Furigana Plus için metin yok!");
        showError("Furigana Plus için metin yok!");
        return;
    }

    try {
        showLoader(true);
        setStatus("Furigana Plus ekleniyor...");

        let form = new FormData();
        form.append("text", sourceText);

        let res = await fetch("/furigana-plus", {method:"POST", body:form});
        const responseText = await res.text();

        if(!res.ok) {
            throw new Error("Furigana Plus başarısız");
        }

        let data = JSON.parse(responseText);
        furiganaResult = data.html || "Furigana Plus eklenemedi";

        const furiganaElement = document.getElementById("furiganaText");
        furiganaElement.innerHTML = furiganaResult;
        furiganaElement.style.display = "block";

        document.getElementById("downloadFuriganaBtn").style.display = "block";

        setStatus("Furigana Plus tamamlandı.");
        showSuccess("Furigana Plus başarıyla eklendi!");

    } catch(e) {
        console.error(e);
        showError("Furigana Plus hatası: " + e.message);
    } finally {
        showLoader(false);
    }
}
  
async function askAI(){
    const question = document.getElementById("question").value;
    const source = document.getElementById("source").value;
    
    if(!question.trim()) {
        setStatus("Lütfen bir soru girin!");
        showError("Lütfen bir soru girin!");
        return;
    }
    
    if(!source.trim()) {
        setStatus("Önce OCR yaparak metin elde edin!");
        showError("Önce OCR yaparak metin elde edin!");
        return;
    }
    
    try {
        showLoader(true);
        let form = new FormData();
        form.append("context", source);
        form.append("question", question);
        let res = await fetch("/ask", {method:"POST", body:form});
        
        // Yanıtı text olarak al
        const responseText = await res.text();
        
        if(!res.ok) {
            // HTML hatası mı kontrol et
            if(responseText.trim().startsWith("<!DOCTYPE") || responseText.trim().startsWith("<html")) {
                showError("AI hatası: HTML yanıt alındı.");
                throw new Error("HTML hatası alındı");
            }
            
            try {
                const errorData = JSON.parse(responseText);
                throw new Error(errorData.detail || "AI sorgulama başarısız");
            } catch {
                throw new Error(responseText || "AI sorgulama başarısız");
            }
        }
        
        // Başarılı yanıt
        let data;
        try {
            data = JSON.parse(responseText);
        } catch {
            throw new Error("Geçersiz JSON yanıtı");
        }
        
        document.getElementById("answer").value = data.answer || "Yanıt alınamadı";
        setStatus("AI yanıtı alındı.");
        showSuccess("AI yanıtı başarıyla alındı!");
    } catch(e) {
        console.error("AI sorma hatası:", e);
        setStatus("AI hatası: " + e.message);
        showError("AI hatası: " + e.message);
    } finally { 
        showLoader(false); 
    }
}

// Furigana metnini indirme fonksiyonu
function downloadFurigana() {
    if (!furiganaResult) {
        showError("İndirilecek furigana metni yok");
        return;
    }
    
    // Dosya adını oluştur
    let baseName = currentFileName || 'furigana_metni';
    let fileName = generateFileName(baseName, '_furigana.html');
    
    // --- YENİ EKLENEN KISIM: HTML ŞABLONU ---
    // Bu şablon dosyanın telefonda ve bilgisayarda düzgün görünmesini sağlar
    const tamHtmlİcerigi = `
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${fileName}</title>
    <style>
        body { 
            font-family: 'Helvetica Neue', Arial, sans-serif; 
            line-height: 2.8; 
            padding: 25px; 
            background-color: #ffffff;
            color: #333;
            /* Metnin sağdan taşmasını engelleyen sihirli komutlar: */
            word-wrap: break-word; 
            overflow-wrap: break-word;
            max-width: 900px;
            margin: 0 auto;
            font-size: 20px;
        }
        ruby { ruby-align: center; }
        rt { font-size: 0.55em; color: #666; font-weight: normal; }
    </style>
</head>
<body>
    <div style="border-bottom: 2px solid #eee; margin-bottom: 20px; padding-bottom: 10px; font-size: 14px; color: #999;">
        FuriJapan OCR Çıktısı - ${new Date().toLocaleString()}
    </div>
    ${furiganaResult}
</body>
</html>`;
    // ---------------------------------------

    // Blob oluştururken sadece furiganaResult değil, tamHtmlİcerigi kullanıyoruz
    const blob = new Blob([tamHtmlİcerigi], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setStatus("Furigana metni indirildi.");
    showSuccess("Furigana metni başarıyla indirildi: " + fileName);
}

// SES KONTROL FONKSİYONLARI

async function playSpeech() {
    const text = document.getElementById("source").value;
    if(!text.trim()) {
        setStatus("Seslendirilecek metin yok!");
        showError("Seslendirilecek metin yok!");
        return;
    }
    
    // Aynı metin için önbellekte ses varsa kullan
    if (audioCache && currentAudioText === text) {
        // Önbellekten çal
        audioPlayer.src = audioCache;
        audioPlayer.play();
        document.getElementById('progressBar').style.display = 'block';
        document.getElementById('audioStatus').innerText = "Önbellekten oynatılıyor...";
        showSuccess("Ses önbellekten oynatılıyor!");
        return;
    }
    
    // Sunucudan yeni ses al
    try {
        showLoader(true);
        document.getElementById('audioStatus').innerText = "Ses oluşturuluyor...";
        
        let form = new FormData();
        form.append("text", text);
        let res = await fetch("/speech", {method:"POST", body:form});
        
        if(!res.ok) {
            const errorText = await res.text();
            if(errorText.trim().startsWith("<!DOCTYPE") || errorText.trim().startsWith("<html")) {
                showError("Ses hatası: HTML yanıt alındı.");
                throw new Error("HTML hatası alındı");
            }
            throw new Error("Ses oluşturma başarısız");
        }
        
        let blob = await res.blob();
        if(blob.type && blob.type.startsWith('audio/')) {
            // Ses önbelleğe al
            const audioUrl = URL.createObjectURL(blob);
            audioCache = audioUrl;
            currentAudioText = text;
            
            audioPlayer.src = audioUrl;
            audioPlayer.play();
            document.getElementById('progressBar').style.display = 'block';
            document.getElementById('audioStatus').innerText = "Oynatılıyor...";
            showSuccess("Ses oluşturuldu ve oynatılıyor!");
        } else {
            throw new Error("Geçersiz ses formatı");
        }
    } catch(e) {
        console.error("Ses oynatma hatası:", e);
        setStatus("Ses hatası: " + e.message);
        showError("Ses hatası: " + e.message);
    } finally { 
        showLoader(false); 
    }
}

function pauseSpeech() {
    if (!audioPlayer.paused && !audioPlayer.ended) {
        audioPlayer.pause();
        document.getElementById('audioStatus').innerText = "Duraklatıldı";
        showSuccess("Ses duraklatıldı");
    } else {
        showError("Oynatılan ses yok");
    }
}

function stopSpeech() {
    if (audioPlayer.src) {
        audioPlayer.pause();
        audioPlayer.currentTime = 0;
        document.getElementById('audioStatus').innerText = "Durduruldu";
        document.getElementById('progressBar').style.display = 'none';
        document.getElementById('progressFill').style.width = '0%';
        showSuccess("Ses durduruldu");
    } else {
        showError("Oynatılan ses yok");
    }
}

function replaySpeech() {
    if (audioPlayer.src) {
        audioPlayer.currentTime = 0;
        audioPlayer.play();
        document.getElementById('progressBar').style.display = 'block';
        document.getElementById('audioStatus').innerText = "Yeniden oynatılıyor...";
        showSuccess("Ses yeniden oynatılıyor!");
    } else {
        showError("Önce ses oluşturun");
    }
}

function downloadAudio() {
    if (!audioCache) {
        showError("İndirilecek ses dosyası yok");
        return;
    }
    
    const text = document.getElementById("source").value;
    
    // Dosya adını oluştur
    let baseName = currentFileName || 'ses_cikisi';
    let fileName = generateFileName(baseName, '_ses.mp3');
    
    // Önbellekteki sesi indir
    const a = document.createElement('a');
    a.href = audioCache;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    
    document.getElementById('audioStatus').innerText = "Ses indirildi";
    showSuccess("Ses başarıyla indirildi: " + fileName);
}

function downloadText() {
    const text = document.getElementById("source").value;
    if(!text.trim()) {
        setStatus("İndirilecek metin yok!");
        showError("İndirilecek metin yok!");
        return;
    }
    
    // Dosya adını oluştur
    let baseName = currentFileName || 'metin_cikisi';
    let fileName = generateFileName(baseName, '_ocr.txt');
    
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setStatus("Metin indirildi.");
    showSuccess("Metin başarıyla indirildi: " + fileName);
}

// Yardımcı fonksiyon: Ctrl tuşu gösterimi için
document.addEventListener('keydown', function(e) {
    if (e.ctrlKey || e.metaKey) {
        document.getElementById('uploadArea').classList.add('dragover');
    }
});

document.addEventListener('keyup', function(e) {
    if (!e.ctrlKey && !e.metaKey) {
        document.getElementById('uploadArea').classList.remove('dragover');
    }
});
</script>
</body>
</html>
"""   


@app.post("/furigana-plus")
async def furigana_plus(text: str = Form(...)):
    try:
        ai = AIClient()
        html = ai.get_ruby_html_text(text, mode="plus")
        return {"html": html}
    except Exception as e:
        logger.error(f"Furigana Plus hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Furigana Plus hatası: {str(e)}"}
        )

@app.post("/upload-doc")
async def upload_doc(file: UploadFile = File(...)):
    """PDF veya resim dosyasını yükle"""
    global state
    
    # Önceki dosyaları temizle
    cleanup_temp_files()
    
    try:
        # Dosya içeriğini oku
        data = await file.read()
        
        if len(data) == 0:
            return JSONResponse(
                status_code=400,
                content={"detail": "Boş dosya yüklendi"}
            )
        
        # PDF mi kontrol et
        is_pdf = False
        
        # 1. İlk bytes'ı kontrol et
        if len(data) >= 4 and data[:4] == b"%PDF":
            is_pdf = True
        else:
            # 2. Uzantıya bak
            filename = file.filename or ""
            if filename.lower().endswith('.pdf'):
                is_pdf = True
        
        if is_pdf:
            # PDF dosyası - geçici dosyaya yaz
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                
                # PyMuPDF ile aç
                doc = fitz.open(tmp_path)
                state.update({
                    "current_pdf": doc,
                    "current_image": None,
                    "is_pdf": True,
                    "total_pages": doc.page_count,
                    "temp_file_path": tmp_path,
                    "current_filename": file.filename
                })
                
                logger.info(f"PDF yüklendi: {file.filename}, Sayfa sayısı: {doc.page_count}")
                
                return {
                    "pages": doc.page_count,
                    "is_pdf": True,
                    "filename": file.filename
                }
                
            except Exception as e:
                logger.error(f"PDF açma hatası: {e}")
                if 'tmp_path' in locals() and tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"PDF açılamadı: {str(e)}"}
                )
        
        else:
            # Resim dosyası
            try:
                # PIL ile resmi açmayı dene
                img = Image.open(io.BytesIO(data))
                img.verify()  # Resmin doğruluğunu kontrol et
                
                # Resmi PNG formatına çevir
                img = Image.open(io.BytesIO(data))
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='PNG')
                img_bytes = img_bytes.getvalue()
                
                state.update({
                    "current_pdf": None,
                    "current_image": img_bytes,
                    "is_pdf": False,
                    "total_pages": 1,
                    "temp_file_path": None,
                    "current_filename": file.filename
                })
                
                logger.info(f"Resim yüklendi: {file.filename}, Boyut: {img.size}")
                
                return {
                    "pages": 1,
                    "is_pdf": False,
                    "filename": file.filename
                }
                
            except Exception as e:
                logger.error(f"Resim açma hatası: {e}")
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Resim açılamadı: {str(e)}"}
                )
        
    except Exception as e:
        logger.error(f"Yükleme hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Dosya yükleme hatası: {str(e)}"}
        )

@app.get("/page/{num}")
async def get_page(num: int):
    """Belirtilen sayfayı görüntü olarak döndür"""
    try:
        if state["is_pdf"] and state["current_pdf"]:
            if num < 0 or num >= state["total_pages"]:
                return JSONResponse(
                    status_code=404,
                    content={"detail": "Sayfa aralık dışında"}
                )
            
            try:
                page = state["current_pdf"].load_page(num)
                # DPI değerini artırarak daha kaliteli görüntü
                pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                img_bytes = pix.tobytes("png")
                
                return {"image": base64.b64encode(img_bytes).decode()}
            except Exception as e:
                logger.error(f"PDF sayfası işleme hatası: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"detail": f"PDF sayfası işlenemedi: {str(e)}"}
                )
        
        elif state["current_image"]:
            # Resim dosyası - doğrudan döndür
            return {"image": base64.b64encode(state["current_image"]).decode()}
        
        else:
            return JSONResponse(
                status_code=404,
                content={"detail": "Yüklü dosya bulunamadı"}
            )
            
    except Exception as e:
        logger.error(f"Sayfa alma hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Sayfa alınamadı: {str(e)}"}
        )

@app.post("/ocr-page")
async def ocr_page(page_num: int = Form(...)):
    """OCR işlemi yap"""
    try:
        ai = AIClient()
        
        if state["is_pdf"]:
            if not state["current_pdf"]:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "PDF yüklü değil"}
                )
            
            if page_num < 0 or page_num >= state["total_pages"]:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Geçersiz sayfa numarası"}
                )
            
            try:
                page = state["current_pdf"].load_page(page_num)
                # OCR için daha yüksek DPI
                pix = page.get_pixmap(matrix=fitz.Matrix(3.0, 3.0))
                img_bytes = pix.tobytes("png")
                text = ai.ocr_vision(img_bytes)
            except Exception as e:
                logger.error(f"PDF OCR hatası: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"detail": f"PDF OCR hatası: {str(e)}"}
                )
        
        else:
            if not state["current_image"]:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Resim yüklü değil"}
                )
            
            try:
                text = ai.ocr_vision(state["current_image"])
            except Exception as e:
                logger.error(f"Resim OCR hatası: {e}")
                return JSONResponse(
                    status_code=500,
                    content={"detail": f"Resim OCR hatası: {str(e)}"}
                )
        
        return {"text": text}
        
    except Exception as e:
        logger.error(f"OCR hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"OCR hatası: {str(e)}"}
        )

@app.post("/ask")
async def ask(context: str = Form(...), question: str = Form(...)):
    """AI'ye soru sor"""
    try:
        ai = AIClient()
        answer = ai.get_assistant_response(context, question)
        return {"answer": answer}
    except Exception as e:
        logger.error(f"AI sorgulama hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"AI sorgulama hatası: {str(e)}"}
        )

@app.post("/speech")
async def speech(text: str = Form(...)):
    """Metni sese çevir"""
    try:
        if not text.strip():
            return JSONResponse(
                status_code=400,
                content={"detail": "Boş metin"}
            )
        
        ai = AIClient()
        audio = ai.generate_speech(text)
        return StreamingResponse(
            io.BytesIO(audio), 
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline; filename=speech.mp3"}
        )
    except Exception as e:
        logger.error(f"Ses oluşturma hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Ses oluşturma hatası: {str(e)}"}
        )

@app.get("/health")
async def health_check():
    """Sağlık kontrol endpoint'i"""
    return {"status": "ok", "state": {
        "has_pdf": state["current_pdf"] is not None,
        "has_image": state["current_image"] is not None,
        "is_pdf": state["is_pdf"],
        "total_pages": state["total_pages"],
        "filename": state["current_filename"]
    }}

@app.post("/furigana")
async def furigana(text: str = Form(...)):
    try:
        ai = AIClient()
        html = ai.get_ruby_html_text(text)
        return {"html": html}
    except Exception as e:
        logger.error(f"Furigana hatası: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Furigana hatası: {str(e)}"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")