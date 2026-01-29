import os
import base64
from pathlib import Path
from openai import OpenAI
from PyQt6.QtCore import QSettings

class AIClient:
    def __init__(self):
        settings = QSettings("FuriJapan", "APIConfig")
        self.api_key = settings.value("openai_api_key")

        # Yedek olarak .env kontrolü
        if not self.api_key:
            env_path = Path(__file__).resolve().parent.parent.parent / '.env'
            if env_path.exists():
                from dotenv import load_dotenv
                load_dotenv(dotenv_path=env_path, override=True)
                self.api_key = os.getenv("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError("API_KEY_MISSING")

        # OpenAI nesnesini kuruyoruz
        self.client = OpenAI(api_key=self.api_key)
        self.model_name = "gpt-4o"
        
    def ocr_vision(self, image_bytes: bytes, temperature: float = 0.1) -> str:
        """Görseldeki Japonca metni OCR ile çıkarır."""
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
            return f"AI Hatası: {str(e)}"
        
    def get_ruby_html_text(self, text: str, mode: str = "normal") -> str:
        """Metne Furigana (Ruby) ekleyerek HTML döndürür."""
        if mode == "plus":
            instruction = (
                "KURAL 1: Metindeki her kanji kelimesini tara. Eğer bir kanji kelimesi daha önce geçtiyse, "
                "onu düz metin olarak bırak. SADECE metin içinde İLK GEÇTİĞİ YERDE <ruby> içine al.\n"
                "KURAL 2: Tekrarlanan kanjilere ASLA furigana ekleme."
            )
        else:
            instruction = "KURAL: Tüm kanjilere <ruby> etiketi ile Furigana ekle."

        prompt = (
            "GÖREV: Japonca metni HTML <ruby> formatına dönüştür.\n"
            "DİKKAT: Yanıtın SADECE HTML kodundan oluşmalıdır. Açıklama ASLA yazma.\n"
            f"{instruction}\n"
            "KURAL 3: ASLA parantez ( ) kullanma. Sadece <ruby><rt></rt></ruby> yapısını kullan.\n"
            "KURAL 4: Her cümleden sonra <br> ekle.\n\n"
            f"METİN: {text}"
        )
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3500,
                temperature=0.0
            )
            raw_content = response.choices[0].message.content
            
            # Temizleme Mantığı
            clean_content = raw_content.replace("```html", "").replace("```", "").strip()
            if "<" in clean_content:
                start_index = clean_content.find("<")
                end_index = clean_content.rfind(">") + 1
                clean_content = clean_content[start_index:end_index]
                
            return clean_content
        except Exception as e:
            return f"HTML Hatası: {str(e)}"
        
    def generate_speech(self, text: str, voice: str = "nova") -> bytes:
        """Metni sese dönüştürür (TTS)."""
        try:
            response = self.client.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text[:4000]
            )
            return response.content
        except Exception as e:
            raise Exception(f"AI Ses Hatası: {str(e)}")

    def get_assistant_response(self, context, question):
        prompt = f"BAĞLAM:\n{context}\n\nSORU: {question}\n\nLütfen bu soruyu verilen bağlamı temel alarak açıkla."
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Asistan Hatası: {str(e)}"

    def get_word_list_analysis(self, text: str) -> str:
        prompt = f"Şu Japonca metindeki tüm kanji ve kelimeleri listele. Tablo hazırla: {text}"
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Analiz Hatası: {str(e)}"

    def analyze_japanese_text(self, text: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": f"Metni analiz et: {text}"}],
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"Analiz Hatası: {str(e)}"