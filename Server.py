from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, Response
import io
import fitz
import base64
from app.llm.client import AIClient

app = FastAPI()

# PDF iÃ§in global
current_pdf = None

# -----------------------
# ANA SAYFA
# -----------------------
@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>FuriJapan</title>
<style>
body { font-family: Arial; margin:0; background:#f5f5f5; }
.header { background:#333; color:white; padding:12px; text-align:center; font-size:20px; }
.container { padding:10px; }
textarea { width:100%; height:200px; font-size:16px; }
button { width:100%; padding:12px; margin-top:8px; font-size:16px; }
.hidden { display:none; }
iframe { width:100%; height:70vh; border:none; }
img { width:100%; border:1px solid #ccc; }

#pdfArea {
  touch-action: pan-y;
}

#textAreaBox {height: 30vh; }

#pdfArea { height: 40vh; }
</style>
</head>

<body>
<div class="header">FuriJapan</div>

<div class="container">

<h3>PDF YÃ¼kle</h3>
<input type="file" id="docInput">
<button onclick="uploadDoc()">YÃ¼kle</button>

<div>
<button onclick="prevPage()">â—€</button>
<span id="pageInfo">0 / 0</span>
<button onclick="nextPage()">â–¶</button>
</div>

<div id="pdfArea">
  <img id="pageImg">
</div>

<button onclick="ocrPage()">AI Oku</button>

<h3>Okunan Metin</h3>
<div id="textAreaBox">
  <textarea id="source"></textarea>
</div>

<h3>AIâ€™ye Sor</h3>
<textarea id="question"></textarea>
<button onclick="askAI()">Sor</button>
<textarea id="answer"></textarea>

<button onclick="playSpeech()">â–¶ Dinle</button>
<button onclick="pauseSpeech()">â¸</button>
<button onclick="stopSpeech()">â¹</button>
<button onclick="downloadSpeech()">ğŸ’¾ Kaydet</button>

<button onclick="showRuby()">âœ¨ Tek TÄ±kla</button>

</div>

<div id="rubyScreen" class="hidden">
<iframe id="rubyFrame"></iframe>
<button onclick="downloadHTML()">ğŸ’¾ HTML Ä°ndir</button>
<button onclick="back()">â† Geri</button>
</div>

<script>
window.onload = function() {
let startY = 0;

document.getElementById("textAreaBox").addEventListener("touchstart", e => {
  startY = e.changedTouches[0].screenY;
});

document.getElementById("textAreaBox").addEventListener("touchend", e => {
  let endY = e.changedTouches[0].screenY;
  let diff = startY - endY;

  if (diff > 40) growText();
  if (diff < -40) shrinkText();
});

function growText() {
  document.getElementById("textAreaBox").style.height = "60vh";
  document.getElementById("pdfArea").style.height = "20vh";
}

function shrinkText() {
  document.getElementById("textAreaBox").style.height = "30vh";
  document.getElementById("pdfArea").style.height = "40vh";
}

let touchStartX = 0;
let touchEndX = 0;

document.getElementById("pdfArea").addEventListener("touchstart", e => {
  touchStartX = e.changedTouches[0].screenX;
});

document.getElementById("pdfArea").addEventListener("touchend", e => {
  touchEndX = e.changedTouches[0].screenX;
  handleSwipe();
});

function handleSwipe() {
  let diff = touchEndX - touchStartX;

  if (diff > 50) {
    prevPage(); // saÄŸa kaydÄ±r
  } else if (diff < -50) {
    nextPage(); // sola kaydÄ±r
  }
}

let totalPages = 0;
let currentPage = 0;
let currentAudio = null;
let currentBlob = null;

async function uploadDoc() {
  let file = document.getElementById("docInput").files[0];
  let form = new FormData();
  form.append("file", file);

  let res = await fetch("/upload-doc", {method:"POST", body:form});
  let data = await res.json();

  totalPages = data.pages;
  currentPage = 0;
  updatePage();
}

async function updatePage() {
  let res = await fetch(`/page/${currentPage}`);
  let data = await res.json();

  document.getElementById("pageImg").src =
    "data:image/png;base64," + data.image;

  document.getElementById("pageInfo").innerText =
    (currentPage+1) + " / " + totalPages;
}

function nextPage(){
  if(currentPage < totalPages-1){
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
  let form = new FormData();
  form.append("page", currentPage);

  let res = await fetch("/ocr-page", {method:"POST", body:form});
  let data = await res.json();

  document.getElementById("source").value = data.text;
}

async function askAI(){
  let form = new FormData();
 form.append("context", document.getElementById("source").value);
 form.append("question", document.getElementById("question").value);
  let res = await fetch("/ask",{method:"POST",body:form});
  let data = await res.json();
  answer.value = data.answer;
}

async function fetchSpeech(){
  let form = new FormData();
  form.append("text", source.value);
  let res = await fetch("/speech",{method:"POST",body:form});
  currentBlob = await res.blob();
  currentAudio = new Audio(URL.createObjectURL(currentBlob));
}

async function playSpeech(){ if(!currentAudio) await fetchSpeech(); currentAudio.play(); }
function pauseSpeech(){ if(currentAudio) currentAudio.pause(); }
function stopSpeech(){ if(currentAudio){ currentAudio.pause(); currentAudio.currentTime=0; } }
function downloadSpeech(){
  if(!currentBlob) return;
  let a=document.createElement("a");
  a.href=URL.createObjectURL(currentBlob);
  a.download="speech.mp3";
  a.click();
}

async function showRuby(){
  let form=new FormData();
  form.append("text",source.value);
  let res=await fetch("/ruby",{method:"POST",body:form});
  let html=await res.text();
  rubyFrame.srcdoc=html;
  rubyScreen.classList.remove("hidden");
}

function back(){ rubyScreen.classList.add("hidden"); }

}
</script>
</body>
</html>
"""

# ---------------- PDF ----------------
@app.post("/upload-doc")
async def upload_doc(file: UploadFile = File(...)):
    global current_pdf
    content = await file.read()
    current_pdf = fitz.open(stream=content, filetype="pdf")
    return {"pages": current_pdf.page_count}

@app.get("/page/{num}")
def get_page(num: int):
    page = current_pdf[num]
    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return {"image": b64}

@app.post("/ocr-page")
async def ocr_page(page: int = Form(...)):
    page_obj = current_pdf[page]
    pix = page_obj.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    ai = AIClient()
    return {"text": ai.ocr_vision(img_bytes)}

# ---------------- OCR ----------------
@app.post("/ocr")
async def ocr(file: UploadFile = File(...)):
    content = await file.read()
    ai = AIClient()
    return {"text": ai.ocr_vision(content)}

# ---------------- RUBY ----------------
@app.post("/ruby")
async def ruby(text: str = Form(...)):
    ai = AIClient()
    html = ai.get_ruby_html_text(text)
    return HTMLResponse(html)

@app.post("/ruby-download")
async def ruby_download(text: str = Form(...)):
    ai = AIClient()
    html = ai.get_ruby_html_text(text)
    return Response(html, media_type="text/html",
                    headers={"Content-Disposition":"attachment; filename=furigana.html"})

# ---------------- SPEECH ----------------
@app.post("/speech")
async def speech(text: str = Form(...)):
    ai = AIClient()
    audio = ai.generate_speech(text)
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")

# ---------------- ASK ----------------
@app.post("/ask")
async def ask(context: str = Form(...), question: str = Form(...)):
    ai = AIClient()
    return {"answer": ai.get_assistant_response(context, question)}
