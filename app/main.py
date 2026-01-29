import sys
import os
from PyQt6.QtWidgets import QApplication
from app.gui.main_window import MainWindow

def main():
    # Gerekli klasörleri burada kontrol edelim (app.config yerine)
    data_dir = os.path.join(os.getcwd(), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)

    app = QApplication(sys.argv)
    
    # Uygulama genelinde bir font veya stil belirlenebilir
    app.setStyle("Fusion") 
    
    window = MainWindow()
    window.show()
    
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())