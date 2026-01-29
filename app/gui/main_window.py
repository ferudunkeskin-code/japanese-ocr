# -*- coding: utf-8 -*-
import webbrowser
import os

import tempfile
import pygame  # Ses çalma için

from pathlib import Path
from typing import Optional
from PyQt6.QtCore import Qt, QSettings, QBuffer, QIODevice
from PyQt6.QtGui import QFont, QAction, QPixmap, QImage, QKeyEvent

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QFileDialog, QMessageBox,
    QLabel, QSplitter, QStatusBar, QApplication, 
    QFrame, QGraphicsView, QGraphicsScene, QComboBox, QDoubleSpinBox,
    QInputDialog, QLineEdit
)

from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

from app.llm.client import AIClient

from PyQt6.QtCore import QThread, pyqtSignal

class AutomationWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, source_text, mode):
        super().__init__()
        self.source_text = source_text
        self.mode = mode

    def run(self):
        try:
            # AIClient'ı burada başlatmak, QSettings'den anahtarı almasını sağlar
            ai = AIClient() 
            result = ai.get_ruby_html_text(self.source_text, mode=self.mode)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))       
            
class AudioWorker(QThread):
    finished = pyqtSignal(bytes)
    error = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            ai = AIClient()
            audio_data = ai.generate_speech(self.text)
            self.finished.emit(audio_data)
        except Exception as e:
            self.error.emit(str(e))
            
class DocumentViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setStyleSheet("background-color: #1e1e1e; border: 1px solid #333; border-radius: 4px;")

    def display_pixmap(self, pixmap: QPixmap):
        self.scene.clear()
        self.scene.addPixmap(pixmap)
        self.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_in(self): self.scale(1.2, 1.2)
    def zoom_out(self): self.scale(0.8, 0.8)
    def reset_zoom(self):
        self.resetTransform()
        self.fitInView(self.scene.itemsBoundingRect(), Qt.AspectRatioMode.KeepAspectRatio)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Japonca Python - AI Destekli OCR & Analiz Asistanı")
        self.resize(1400, 750)
        
        self.current_file: Optional[Path] = None
        self.pdf_doc = None
        self.current_page = 0
        self.default_font_size = 13
        self.current_font_size = self.default_font_size
        
        pygame.mixer.init() # Ses motorunu başlat
        self.is_paused = False
        
        self._init_ui()
        self.load_settings()
        

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # TOOLBAR
        self.toolbar = self.addToolBar("Dosya")
        load_act = QAction("📂 Dosya Yükle", self)
        load_act.triggered.connect(self.on_load_clicked)
        self.toolbar.addAction(load_act)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setObjectName("mainSplitter")
        
        # Ayarlar Butonu
        self.toolbar.addSeparator()
        settings_act = QAction("🔑 API Ayarı", self)
        settings_act.triggered.connect(self.prompt_for_api_key)
        self.toolbar.addAction(settings_act)

        # --- SOL PANEL ---
        left_container = QFrame()
        left_layout = QVBoxLayout(left_container)

        img_nav_layout = QHBoxLayout()
        self.lbl_file_status = QLabel("Dosya: Yüklenmedi")
        self.btn_z_in = QPushButton("➕")
        self.btn_z_out = QPushButton("➖")
        self.btn_z_reset = QPushButton("Reset")
        self.lbl_page_info = QLabel("")
        self.btn_prev = QPushButton("◀ Geri")
        self.btn_next = QPushButton("İleri ▶")
        for btn in [self.btn_z_in, self.btn_z_out, self.btn_z_reset, self.btn_prev, self.btn_next]:
            btn.setFixedWidth(65)

        img_nav_layout.addWidget(self.lbl_file_status)
        img_nav_layout.addStretch()
        img_nav_layout.addWidget(self.btn_z_out)
        img_nav_layout.addWidget(self.btn_z_reset)
        img_nav_layout.addWidget(self.btn_z_in)
        img_nav_layout.addSpacing(10)
        img_nav_layout.addWidget(self.lbl_page_info)
        img_nav_layout.addWidget(self.btn_prev)
        img_nav_layout.addWidget(self.btn_next)
        left_layout.addLayout(img_nav_layout)

        self.left_v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.left_v_splitter.setObjectName("leftVSplitter")
        
        self.viewer = DocumentViewer()
        self.left_v_splitter.addWidget(self.viewer)

        text_container = QWidget()
        text_v_layout = QVBoxLayout(text_container)
        text_v_layout.setContentsMargins(0, 0, 0, 0)
        
        # --- SOL ALT KONTROL SATIRI ---
        text_ctrl_layout = QHBoxLayout()
        text_ctrl_layout.addWidget(QLabel("<b>Okunan Metin</b>"))
        text_ctrl_layout.addStretch()

        text_ctrl_layout.addWidget(QLabel("DPI:"))
        self.cmb_dpi = QComboBox()
        self.cmb_dpi.addItems(["150", "200", "300", "400"])
        self.cmb_dpi.setCurrentText("150")
        self.cmb_dpi.setFixedWidth(55)
        text_ctrl_layout.addWidget(self.cmb_dpi)
        
        text_ctrl_layout.addWidget(QLabel("Temp:"))
        self.spn_temp = QDoubleSpinBox()
        self.spn_temp.setRange(0.0, 1.0)
        self.spn_temp.setSingleStep(0.1)
        self.spn_temp.setValue(0.1)
        self.spn_temp.setFixedWidth(50)
        text_ctrl_layout.addWidget(self.spn_temp)

        self.btn_theme = QPushButton("🌙")
        self.btn_theme.setFixedWidth(40)
        self.btn_theme.setCheckable(True)
        self.btn_theme.clicked.connect(self.toggle_theme)
        text_ctrl_layout.addWidget(self.btn_theme)

        self.btn_txt_small = QPushButton("A-")
        self.btn_txt_reset = QPushButton("Normal")
        self.btn_txt_large = QPushButton("A+")
        for btn in [self.btn_txt_small, self.btn_txt_reset, self.btn_txt_large]:
            btn.setFixedWidth(50) # Biraz küçülttük yer açmak için
            text_ctrl_layout.addWidget(btn)

        # --- SOL PANEL SES VE KAYIT BUTONLARI ---
        self.btn_l_play = QPushButton("▶")
        self.btn_l_pause = QPushButton("⏸")
        self.btn_l_stop = QPushButton("⏹")
        self.btn_l_save_audio = QPushButton("💾") # Ses kaydet
        self.btn_l_save_text = QPushButton("📄")  # Metni TXT kaydet

        for btn in [self.btn_l_play, self.btn_l_pause, self.btn_l_stop, self.btn_l_save_audio, self.btn_l_save_text]:
            btn.setFixedSize(26, 26)
            btn.setStyleSheet("font-size: 12px; padding: 0px;")
            text_ctrl_layout.addWidget(btn)
            
        text_v_layout.addLayout(text_ctrl_layout)
        
        self.txt_source = QTextEdit()
        self.txt_source.setPlaceholderText("Henüz metin okunmadı...")
        self.txt_source.setStyleSheet("QTextEdit { background-color: #ffffff; color: #000000; border: 1px solid #ccc; }")
        self.update_text_font()
        text_v_layout.addWidget(self.txt_source, stretch=10)

        # SOL ASİSTAN
        left_assistant_layout = QVBoxLayout()
        left_assistant_layout.setSpacing(2)
        left_assistant_layout.addWidget(QLabel("<b>💡 Metin Asistanı:</b>"))
        l_ask_lay = QHBoxLayout()
        self.txt_left_prompt = QTextEdit()
        self.txt_left_prompt.setFixedHeight(45)
        self.btn_left_ask = QPushButton("Sor")
        self.btn_left_ask.setFixedSize(60, 45)
        self.btn_left_ask.clicked.connect(self.process_left_assistant_ask)
        l_ask_lay.addWidget(self.txt_left_prompt)
        l_ask_lay.addWidget(self.btn_left_ask)
        left_assistant_layout.addLayout(l_ask_lay)
        text_v_layout.addLayout(left_assistant_layout)
        
        self.left_v_splitter.addWidget(text_container)
        left_layout.addWidget(self.left_v_splitter)

        self.btn_ai_read = QPushButton("🤖 AI ile Bu Sayfayı Oku")
        self.btn_ai_read.setStyleSheet("background-color: #8e44ad; color: white; height: 16px; font-weight: bold;")
        self.btn_ai_read.clicked.connect(self.process_with_ai)
        left_layout.addWidget(self.btn_ai_read)

        # --- SAĞ PANEL ---
        right_container = QFrame()
        right_layout = QVBoxLayout(right_container)

        right_top_layout = QHBoxLayout()
        right_top_layout.addWidget(QLabel("<b>Analiz ve Çıktı</b>"))
        right_top_layout.addStretch()

        # --- SAĞ PANEL SES BUTONLARI ---
        self.btn_r_play = QPushButton("▶")
        self.btn_r_pause = QPushButton("⏸")
        self.btn_r_stop = QPushButton("⏹")
        self.btn_r_save_audio = QPushButton("💾")

        for btn in [self.btn_r_play, self.btn_r_pause, self.btn_r_stop, self.btn_r_save_audio]:
            btn.setFixedSize(26, 26)
            btn.setStyleSheet("font-size: 12px; padding: 0px;")
            right_top_layout.addWidget(btn)
            
        self.btn_print = QPushButton("🖨 Yazdır")
        self.btn_print.setFixedWidth(70)
        self.btn_print.clicked.connect(self.print_output)
        right_top_layout.addWidget(self.btn_print)
        right_layout.addLayout(right_top_layout)

        self.txt_output = QTextEdit()
        self.txt_output.setReadOnly(True)
        self.txt_output.setStyleSheet("QTextEdit { background-color: #ffffff; color: #000000; border: 1px solid #ccc; }")
        right_layout.addWidget(self.txt_output, stretch=10)

        # SAĞ ASİSTAN ... (Mevcut kodun devamı)
        right_assistant_layout = QVBoxLayout()
        right_assistant_layout.addWidget(QLabel("<b>💡 Analiz Asistanı:</b>"))
        r_ask_lay = QHBoxLayout()
        self.txt_prompt = QTextEdit()
        self.txt_prompt.setFixedHeight(45)
        self.btn_ask = QPushButton("Sor")
        self.btn_ask.setFixedSize(60, 45)
        self.btn_ask.clicked.connect(self.process_assistant_ask)
        r_ask_lay.addWidget(self.txt_prompt)
        r_ask_lay.addWidget(self.btn_ask)
        right_assistant_layout.addLayout(r_ask_lay)
        right_layout.addLayout(right_assistant_layout)

        # Alt Butonlar
        right_btn_layout = QHBoxLayout()
        self.btn_analyze = QPushButton("📊 Analiz")
        self.btn_words = QPushButton("📚 Kelimeler")
        self.btn_furigana = QPushButton("🏮 Furigana")
        self.btn_auto_save = QPushButton("🚀 Tek Tıkla")
        self.btn_auto_plus = QPushButton("✨ Tek Tıkla Plus")
        for btn in [self.btn_analyze, self.btn_words, self.btn_furigana, self.btn_auto_save, self.btn_auto_plus]:
            btn.setFixedHeight(25)
            right_btn_layout.addWidget(btn)

        right_layout.addLayout(right_btn_layout)

        self.main_splitter.addWidget(left_container)
        self.main_splitter.addWidget(right_container)
        main_layout.addWidget(self.main_splitter)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        # --- SİNYAL BAĞLANTILARI (Eski ve Yeni Hepsi) ---
        self.btn_z_in.clicked.connect(self.viewer.zoom_in)
        self.btn_z_out.clicked.connect(self.viewer.zoom_out)
        self.btn_z_reset.clicked.connect(self.viewer.reset_zoom)
        self.btn_txt_large.clicked.connect(lambda: self.change_font_size(2))
        self.btn_txt_small.clicked.connect(lambda: self.change_font_size(-2))
        self.btn_txt_reset.clicked.connect(self.reset_font_size)
        self.btn_prev.clicked.connect(lambda: self.change_pdf_page(-1))
        self.btn_next.clicked.connect(lambda: self.change_pdf_page(1))
        self.btn_analyze.clicked.connect(self.process_analysis)
        self.btn_words.clicked.connect(self.process_word_list)
        self.btn_furigana.clicked.connect(self.process_furigana)
        self.btn_auto_save.clicked.connect(lambda: self.process_automation(mode="normal"))
        self.btn_auto_plus.clicked.connect(lambda: self.process_automation(mode="plus"))
        
        # --- SİNYAL BAĞLANTILARI (Hata Almamak İçin Burayı Kontrol Et) ---
        self.btn_l_play.clicked.connect(lambda: self.handle_ai_speech(self.txt_source.toPlainText()))
        self.btn_r_play.clicked.connect(lambda: self.handle_ai_speech(self.txt_output.toPlainText()))
        self.btn_l_pause.clicked.connect(self.toggle_pause)
        self.btn_r_pause.clicked.connect(self.toggle_pause)
        self.btn_l_stop.clicked.connect(self.stop_speech)
        self.btn_r_stop.clicked.connect(self.stop_speech)
        
        # SES KAYDETME (Dinamik isimle)
        self.btn_l_save_audio.clicked.connect(lambda: self.save_ai_speech(self.txt_source.toPlainText()))
        self.btn_r_save_audio.clicked.connect(lambda: self.save_ai_speech(self.txt_output.toPlainText()))
        
        # SOL PANEL METİN KAYDETME (📄 Butonu)
        self.btn_l_save_text.clicked.connect(self.save_source_text_as_file)
        
    def print_output(self):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            self.txt_output.print(printer)

    def process_assistant_ask(self):
        context_data = self.txt_output.toPlainText().strip()
        user_question = self.txt_prompt.toPlainText().strip()
        if not user_question: return
        self.status_bar.showMessage("Asistan yanıtlıyor...")
        QApplication.processEvents()
        try:
            ai = AIClient()
            answer = ai.get_assistant_response(context_data, user_question)
            current_text = self.txt_output.toMarkdown()
            separator = "\n\n---\n### 💡 Asistan Yanıtı\n"
            self.txt_output.setMarkdown(current_text + separator + answer)
            self.txt_prompt.clear()
            self.status_bar.showMessage("Yanıt eklendi.")
            self.txt_output.verticalScrollBar().setValue(self.txt_output.verticalScrollBar().maximum())
        except Exception as e:
            self.status_bar.showMessage(f"Hata: {str(e)}")

    def on_load_clicked(self):
        file_path_str, _ = QFileDialog.getOpenFileName(self, "Dosya Seç", "", "Hepsi (*.png *.jpg *.pdf *.txt)")
        if not file_path_str: return
        self.txt_source.clear()
        self.txt_output.clear()
        self.viewer.scene.clear()
        self.current_file = Path(file_path_str)
        self.lbl_file_status.setText(f"Dosya: {self.current_file.name}")
        if self.current_file.suffix.lower() == '.pdf':
            import fitz
            self.pdf_doc = fitz.open(str(self.current_file))
            self.current_page = 0
            self.show_pdf_page()
        elif self.current_file.suffix.lower() == '.txt':
            self.pdf_doc = None
            with open(file_path_str, 'r', encoding='utf-8') as f:
                self.txt_source.setPlainText(f.read())
            self.lbl_page_info.setText("")
        else:
            self.pdf_doc = None
            self.viewer.display_pixmap(QPixmap(file_path_str))
            self.lbl_page_info.setText("")

    def show_pdf_page(self):
        if not self.pdf_doc: return
        page = self.pdf_doc.load_page(self.current_page)
        current_dpi = int(self.cmb_dpi.currentText())
        pix = page.get_pixmap(dpi=current_dpi)
        img = QImage.fromData(pix.tobytes("png"))
        self.viewer.display_pixmap(QPixmap.fromImage(img))
        self.lbl_page_info.setText(f"{self.current_page + 1}/{len(self.pdf_doc)}")

    def change_pdf_page(self, delta):
        if not self.pdf_doc: return
        new_page = self.current_page + delta
        if 0 <= new_page < len(self.pdf_doc):
            self.txt_source.clear()
            self.txt_output.clear()
            self.current_page = new_page
            self.show_pdf_page()

    def update_text_font(self):
        self.txt_source.setFont(QFont("Segoe UI", self.current_font_size))

    def change_font_size(self, delta):
        self.current_font_size = max(8, min(72, self.current_font_size + delta))
        self.update_text_font()

    def reset_font_size(self):
        self.current_font_size = self.default_font_size
        self.update_text_font()

    def process_with_ai(self):
        ai = self.get_ai_client() # Güvenli başlatma
        if not ai: return # Kullanıcı iptal ettiyse çık

        items = self.viewer.scene.items()
        if not items: return
        
        self.status_bar.showMessage("AI Okuyor...")
        QApplication.processEvents()
        try:
            pixmap = items[0].pixmap()
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap.save(buffer, "PNG")
            
            temp_val = self.spn_temp.value()
            result = ai.ocr_vision(buffer.data(), temperature=temp_val)
            self.txt_source.setPlainText(result)
            self.status_bar.showMessage("Metin okuma bitti.")
        except Exception as e:
            if "401" in str(e): # Geçersiz anahtar hatası gelirse
                self.status_bar.showMessage("API Anahtarı geçersiz!")
                self.prompt_for_api_key()
            else:
                self.status_bar.showMessage(f"Hata: {str(e)}")
                
    def process_automation(self, mode="normal"):
        source_text = self.txt_source.toPlainText().strip()
        
        # EĞER METİN YOKSA: Önce OCR yap, sonra bu fonksiyonu tekrar çağır
        if not source_text:
            self.status_bar.showMessage("Metin kutusu boş, önce görsel okunuyor...")
            self.process_with_ai() # Bu fonksiyon OCR yapar ve txt_source'u doldurur
            
            # OCR bittikten sonra metni tekrar kontrol et
            source_text = self.txt_source.toPlainText().strip()
            if not source_text:
                self.status_bar.showMessage("Hata: Okunacak bir metin veya görsel bulunamadı.")
                return

        # 1. Butonları kilitle (Donma hissini ve mükerrer tıklamayı önler)
        self.btn_auto_save.setEnabled(False)
        self.btn_auto_plus.setEnabled(False)
        self.status_bar.showMessage(f"AI çalışıyor, lütfen bekleyin... ({mode.upper()} MOD)")

        # 2. İşçiyi (QThread) oluştur ve başlat
        self.worker = AutomationWorker(source_text, mode)
        
        # Sinyalleri bağla
        self.worker.finished.connect(lambda res: self.on_automation_finished(res, mode))
        self.worker.error.connect(self.on_ai_error)
        
        self.worker.start() # Arayüz kilitlenmeden arka planda başlar
        

    def on_ai_error(self, err_msg):
        """Hata durumunda butonları aç ve mesaj ver."""
        self.status_bar.showMessage(f"Hata: {err_msg}")
        self.btn_auto_save.setEnabled(True)
        self.btn_auto_plus.setEnabled(True)

    def on_automation_finished(self, ruby_content, mode):
        """AI cevabı geldiğinde dosyayı kaydeden ve açan güvenli kısım."""
        try:
            final_body = ruby_content.replace("\n", "<br>")
            
            target_dir = os.path.join(os.getcwd(), "data")
            if not os.path.exists(target_dir): 
                os.makedirs(target_dir)
            
            suffix = "_Plus" if mode == "plus" else ""
            # Dosya adı için güvenli kontrol
            f_base = self.current_file.stem if self.current_file else "Yapistirilan"
            f_name = f"{f_base}{suffix}_s{self.current_page+1}.html"
            file_path = os.path.join(target_dir, f_name)
            
            html_content = f"<html><body style='font-family:MS Mincho; font-size:28px; padding:40px; line-height:3;'>{final_body}</body></html>"
            
            with open(file_path, "w", encoding="utf-8") as f: 
                f.write(html_content)
                
            webbrowser.open(f"file:///{os.path.abspath(file_path)}")
            self.status_bar.showMessage(f"Başarıyla kaydedildi: data/{f_name}")
            
        except Exception as e:
            self.status_bar.showMessage(f"Dosya hatası: {str(e)}")
        finally:
            # Her durumda butonları tekrar aktif et
            self.btn_auto_save.setEnabled(True)
            self.btn_auto_plus.setEnabled(True)
            
    def process_word_list(self):
        txt = self.txt_source.toPlainText()
        if txt: 
            self.status_bar.showMessage("Kelimeler analiz ediliyor...")
            QApplication.processEvents()
            self.txt_output.setMarkdown(AIClient().get_word_list_analysis(txt))
            self.status_bar.showMessage("Analiz bitti.")

    def process_analysis(self):
        txt = self.txt_source.toPlainText()
        if txt: self.txt_output.setMarkdown(AIClient().analyze_japanese_text(txt))

    def process_furigana(self):
        txt = self.txt_source.toPlainText()
        if txt: self.txt_output.setPlainText(AIClient().get_furigana_text(txt))

    def load_settings(self):
        settings = QSettings("MyJapaneseApp", "Layout")
        if settings.value("geometry"): self.restoreGeometry(settings.value("geometry"))
        if settings.value("mainSplitterState"): self.main_splitter.restoreState(settings.value("mainSplitterState"))
        else: self.main_splitter.setSizes([700, 700])
        if settings.value("leftVSplitterState"): self.left_v_splitter.restoreState(settings.value("leftVSplitterState"))
        else: self.left_v_splitter.setSizes([400, 200])

    def closeEvent(self, event):
        settings = QSettings("MyJapaneseApp", "Layout")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("mainSplitterState", self.main_splitter.saveState())
        settings.setValue("leftVSplitterState", self.left_v_splitter.saveState())
        super().closeEvent(event)
        
    def process_left_assistant_ask(self):
        """Sol taraftaki OCR metnini bağlam alarak AI'ya soru sorar."""
        context_data = self.txt_source.toPlainText().strip()
        user_question = self.txt_left_prompt.toPlainText().strip()
        if not user_question: return
        self.status_bar.showMessage("Metin asistanı yanıtlıyor...")
        QApplication.processEvents()
        try:
            ai = AIClient()
            answer = ai.get_assistant_response(context_data, user_question)
            current_text = self.txt_output.toMarkdown()
            separator = "\n\n---\n### 📝 Metin Analiz Yanıtı\n"
            self.txt_output.setMarkdown(current_text + separator + answer)
            self.txt_left_prompt.clear()
            self.status_bar.showMessage("Yanıt eklendi.")
            self.txt_output.verticalScrollBar().setValue(self.txt_output.verticalScrollBar().maximum())
        except Exception as e:
            self.status_bar.showMessage(f"Hata: {str(e)}")        

    def toggle_theme(self):
        """Metin alanlarını Karanlık ve Aydınlık mod arasında değiştirir."""
        is_dark = self.btn_theme.isChecked()
        
        if is_dark:
            self.btn_theme.setText("☀️")
            # Karanlık Mod Stili
            dark_css = """
                QTextEdit { 
                    background-color: #1e1e1e; 
                    color: #ffffff; 
                    border: 1px solid #333;
                    selection-background-color: #444;
                }
                QTextEdit::placeholder { color: #888888; font-style: italic; font-size: 10px; }
            """
            self.txt_source.setStyleSheet(dark_css)
            self.txt_output.setStyleSheet(dark_css)
            self.status_bar.showMessage("Karanlık mod aktif.")
        else:
            self.btn_theme.setText("🌙")
            # Aydınlık Mod Stili
            light_css = """
                QTextEdit { 
                    background-color: #ffffff; 
                    color: #000000; 
                    border: 1px solid #ccc;
                    selection-background-color: #b3d7ff;
                }
                QTextEdit::placeholder { color: #666666; font-style: italic; font-size: 10px; }
            """
            self.txt_source.setStyleSheet(light_css)
            self.txt_output.setStyleSheet(light_css)
            self.status_bar.showMessage("Aydınlık mod aktif.")
            
    def keyPressEvent(self, event: QKeyEvent):
        """Klavye olaylarını yakalar. Ctrl+V ile görsel yapıştırmayı sağlar."""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V:
            clipboard = QApplication.clipboard()
            mime_data = clipboard.mimeData()

            if mime_data.hasImage():
                # Yeni görsel gelince eski metinleri ve sahneyi temizle
                self.txt_source.clear()
                self.txt_output.clear()
                self.viewer.scene.clear()
                
                pixmap = QPixmap.fromImage(clipboard.image())
                if not pixmap.isNull():
                    self.viewer.display_pixmap(pixmap)
                    self.lbl_file_status.setText("Dosya: Panodan Yapıştırıldı")
                    self.lbl_page_info.setText("")
                    self.current_file = None
                    self.pdf_doc = None
                    self.status_bar.showMessage("Görüntü panodan yapıştırıldı.", 3000)
                else:
                    self.status_bar.showMessage("Panodaki görüntü geçersiz!")
            else:
                self.status_bar.showMessage("Panoda yapıştırılacak bir görsel bulunamadı!")
        
        # Diğer standart tuş takımlarını bozmamak için üst sınıfa ilet
        super().keyPressEvent(event)
        
    def get_ai_client(self):
        """AIClient'ı güvenli bir şekilde başlatır, anahtar yoksa kullanıcıya sorar."""
        try:
            return AIClient()
        except ValueError as e:
            if str(e) == "API_KEY_MISSING":
                if self.prompt_for_api_key():
                    return AIClient() # Anahtar girildiyse tekrar dene
            return None

    def prompt_for_api_key(self):
        """Kullanıcıdan anahtar isteyen pencere. Çökmeyi önlemek için try-except içinde."""
        try:
            # Mevcut anahtarı kutuda göstermek için çekelim
            settings = QSettings("FuriJapan", "APIConfig")
            current_key = settings.value("openai_api_key", "")

            key, ok = QInputDialog.getText(
                self, 
                "API Ayarları", 
                "OpenAI API Anahtarınızı girin:", 
                QLineEdit.EchoMode.Normal, # Burayı QLineEdit üzerinden çağırmak daha garantidir
                current_key
            )

            if ok and key.strip():
                settings.setValue("openai_api_key", key.strip())
                QMessageBox.information(self, "Başarılı", "API Anahtarı güncellendi.")
                return True
            return False
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Pencere açılırken bir sorun oluştu: {str(e)}")
            return False
        
    # --- SES YÖNETİM METODLARI (THREAD DESTEKLİ) ---


    def play_audio_data(self, audio_data):
        """Worker'dan gelen ses verisini çalar"""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name
            
            pygame.mixer.music.load(tmp_path)
            pygame.mixer.music.play()
            self.status_bar.showMessage("AI Seslendiriyor...")
        except Exception as e:
            self.status_bar.showMessage(f"Çalma Hatası: {str(e)}")

    def toggle_pause(self):
        if pygame.mixer.music.get_busy() or self.is_paused:
            if not self.is_paused:
                pygame.mixer.music.pause()
                self.is_paused = True
                self.status_bar.showMessage("Duraklatıldı.")
            else:
                pygame.mixer.music.unpause()
                self.is_paused = False
                self.status_bar.showMessage("Devam ediyor.")

    def stop_speech(self):
        pygame.mixer.music.stop()
        self.is_paused = False
        self.status_bar.showMessage("Ses durduruldu.")


    def get_dynamic_filename(self, suffix=".mp3", is_audio=True):
        """Dosya adı + Sayfa No + İndeks formatında isim üretir."""
        base_name = self.current_file.stem if self.current_file else "adsiz"
        page_num = self.current_page + 1
        
        # Klasör seçimi
        sub_folder = "audio" if is_audio else "texts"
        save_dir = Path(__file__).resolve().parent.parent.parent / "data" / sub_folder
        save_dir.mkdir(parents=True, exist_ok=True)

        if is_audio:
            # Kaçıncı ses dosyası olduğunu bul (s1, s2...)
            existing_count = len(list(save_dir.glob(f"{base_name}{page_num}_s*{suffix}")))
            final_name = f"{base_name}{page_num}_s{existing_count + 1}{suffix}"
        else:
            # TXT için direkt isim
            final_name = f"{base_name}{page_num}{suffix}"

        return save_dir / final_name

    def save_source_text_as_file(self):
        """Sol paneldeki Japonca metni TXT olarak kaydeder."""
        text = self.txt_source.toPlainText().strip()
        if not text:
            self.status_bar.showMessage("Kaydedilecek metin yok.")
            return

        full_path = self.get_dynamic_filename(suffix=".txt", is_audio=False)
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Metni TXT Olarak Kaydet", str(full_path), "Metin Dosyası (*.txt)"
        )

        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_bar.showMessage(f"Metin kaydedildi: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Hata", f"Metin kaydedilemedi: {e}")

    def save_ai_speech(self, text):
        """Sesi arka planda üretir ve dinamik isimle kaydeder."""
        if not text.strip(): return

        full_path = self.get_dynamic_filename(suffix=".mp3", is_audio=True)
        
        path, _ = QFileDialog.getSaveFileName(
            self, "Sesi Kaydet", str(full_path), "Ses Dosyası (*.mp3)"
        )

        if path:
            self.status_bar.showMessage("Ses hazırlanıyor...")
            self.save_worker = AudioWorker(text)
            self.save_worker.finished.connect(lambda data: self._finish_audio_save(data, path))
            self.save_worker.start()

    def _finish_audio_save(self, data, path):
        with open(path, "wb") as f:
            f.write(data)
        self.status_bar.showMessage(f"Ses kaydedildi: {os.path.basename(path)}")

    def handle_ai_speech(self, text):
        """Oynatma işlemi (Thread üzerinden)"""
        if not text.strip(): return
        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            return

        self.status_bar.showMessage("AI Ses hazırlıyor...")
        self.play_worker = AudioWorker(text)
        self.play_worker.finished.connect(self._play_audio_stream)
        self.play_worker.start()

    def _play_audio_stream(self, audio_data):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_data)
            path = tmp.name
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        self.status_bar.showMessage("Okunuyor...")