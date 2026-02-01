import os
import base64
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

# 1. Önce sistem ortam değişkenlerini (Render/Codespaces Secrets) yükle
# 2. Mevcut klasörde veya üst klasörlerde .env dosyası varsa onu da yükle
load_dotenv() 

# PyQt6 opsiyonel (Masaüstü GUI desteği için)
try:
    from PyQt6.QtCore import QSettings
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class AIClient:
    def __init__(self):
        # API anahtarını hiyerarşik olarak ara:
        # A) Sistem Değişkeni (Render Dashboard / GitHub Secrets)
        self.api_key = os.getenv("OPENAI_API_KEY")

        # B) Eğer sistemde yoksa ve .env dosyası da yüklenemediyse manuel yol dene
        if not self.api_key:
            env_paths = [
                Path.cwd() / ".env",
                Path(__file__).resolve().parent / ".env",
                Path(__file__).resolve().parent.parent.parent / ".env"
            ]
            for path in env_paths:
                if path.exists():
                    load_dotenv(path)
                    self.api_key = os.getenv("OPENAI_API_KEY")
                    if self.api_key: break

        # C) Eğer hala yoksa ve masaüstü modundaysak QSettings'e bak
        if not self.api_key and QT_AVAILABLE:
            try:
                settings = QSettings("FuriJapan", "APIConfig")
                self.api_key = settings.value("openai_api_key")
            except:
                pass

        # Hiçbir yerde bulunamadıysa hata fırlat
        if not self.api_key:
            raise ValueError(
                "API ANAHTARI EKSİK! Lütfen şunlardan birini yapın:\n"
                "1. Render/GitHub panelinden 'OPENAI_API_KEY' ekleyin.\n"
                "2. Proje ana dizinine .env dosyası koyun."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model_name = "gpt-4o"

    # ---------------- OCR ----------------
    def ocr_vision(self, image_bytes: bytes, temperature: float = 0.1) -> str:
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Resimdeki Japonca metni çıkar. Sadece metni ver."},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                        ],
                    }
                ],
                max_tokens=2000,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"AI OCR Hatası: {str(e)}"

    # ---------------- FURIGANA ----------------
    def get_ruby_html_text(self, text: str, mode: str = "normal") -> str:
        if mode == "plus":
            instruction = (
                "KURAL 1: Metindeki her kanji kelimesini tara. Eğer bir kanji kelimesi daha önce geçtiyse, "
                "onu düz metin olarak bırak. SADECE ilk geçtiği yerde <ruby> içine al.\n"
                "KURAL 2: Tekrarlanan kanjilere furigana ekleme."
            )
        else:
            instruction = "KURAL: Tüm kanjilere <ruby> etiketi ile Furigana ekle."

        prompt = (
            "GÖREV: Japonca metni HTML <ruby> formatına dönüştür.\n"
            "Yanıt SADECE HTML olsun.\n"
            f"{instruction}\n"
            f"METİN: {text}"
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3500,
                temperature=0.0
            )
            raw = response.choices[0].message.content
            # Markdown bloklarını temizle
            clean_html = raw.replace("```html", "").replace("```", "").strip()
            return clean_html
        except Exception as e:
            return f"Furigana HTML Hatası: {str(e)}"

    # ---------------- TTS (SES) ----------------
    def generate_speech(self, text: str, voice: str = "nova") -> bytes:
        try:
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text[:4000]
            )
            return response.content
        except Exception as e:
            raise Exception(f"AI Ses Hatası: {str(e)}")

    # ---------------- CHAT / ASİSTAN ----------------
    def get_assistant_response(self, context, question):
        prompt = f"BAĞLAM:\n{context}\n\nSORU: {question}"
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Asistan Hatası: {str(e)}"