import sys
import os
import serial.tools.list_ports
import datetime
import traceback
import cv2
import numpy as np
import random
import io
import pyqtgraph as pg
import pyqtgraph.opengl as gl
import folium


from PyQt6.QtWebEngineWidgets import QWebEngineView

# --- 1. GPU ÇAKIŞMASINI ÖNLEYEN DİKTATÖR KOMUTLAR ---
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --disable-gpu-compositing --disable-software-rasterizer"
os.environ["QT_OPENGL"] = "desktop"
sys.argv.extend(["--disable-gpu", "--disable-gpu-compositing"])

# --- 2. SESSİZ ÇÖKMELERİ ÖNLEYEN HATA YAKALAYICI ---
def excepthook(exc_type, exc_value, exc_tb):
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("\n--- SİSTEM HATASI TESPİT EDİLDİ ---")
    print(tb)
    print("-----------------------------------\n")
    from PyQt6.QtWidgets import QApplication
    QApplication.quit()

sys.excepthook = excepthook

# --- 3. SERİ PORT KONTROLÜ ---
try:
    import serial
except ImportError:
    print("HATA: 'pyserial' yüklü değil! Lütfen terminale 'pip install pyserial' yazın.")
    sys.exit(1)

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel,
                             QVBoxLayout, QHBoxLayout, QPushButton, QGroupBox,
                             QCheckBox, QComboBox, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSizePolicy,
                             QAbstractItemView)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from Telemetri import TelemetriVerisi

# --- VIDEO THREAD ---
class VideoThread(QThread):
    change_pixmap_signal = pyqtSignal(np.ndarray)

    def run(self):
        try:
            cap = cv2.VideoCapture(0)
            while True:
                ret, frame = cap.read()
                if ret:
                    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.change_pixmap_signal.emit(rgb_image)
                self.msleep(30)
        except Exception as e:
            pass

class YerIstasyonu(QMainWindow):
    def __init__(self):
        super().__init__(None)

        # --- PENCERE AYARLARI ---
        self.setWindowTitle("TEKNOFEST 2026 - CANLI VERİ & HARİTA (GPS)")
        self.setGeometry(50, 50, 1600, 950)
        self.setStyleSheet("""
            QMainWindow {background-color: #121212; color: white;}
            QGroupBox {border: 1px solid #444; border-radius: 5px; margin-top: 10px; font-weight: bold; color: #ddd; font-size: 11px;}
            QGroupBox::title {subcontrol-origin: margin; left: 10px; padding: 0 3px;}
            QLabel {color: white; font-family: 'Segoe UI';}
            QPushButton {background-color: #333; color: white; border: 1px solid #555; padding: 8px; border-radius: 3px; font-weight: bold;}
            QPushButton:hover {background-color: #555;}
            QTableWidget {background-color: #1e1e1e; color: #ecf0f1; gridline-color: #444; font-size: 12px; border: 1px solid #444;}
            QTableWidget::item {padding-left: 5px; padding-right: 5px;}
            QHeaderView::section {background-color: #0b1e3b; color: white; padding: 8px; font-weight: bold; border: 1px solid #000; font-size: 11px;}
            QTableWidget::item:selected {background-color: #3498db; color: white;}
            QScrollBar:horizontal {border: 1px solid #333; background: #121212; height: 15px; margin: 0px 20px 0 20px;}
            QScrollBar::handle:horizontal {background: #555; min-width: 20px;}
            QScrollBar:vertical {border: 1px solid #333; background: #121212; width: 15px; margin: 20px 0 20px 0;}
            QScrollBar::handle:vertical {background: #555; min-height: 20px;}
            QComboBox {background-color: #333; color: white; padding: 5px;}
            QCheckBox {padding: 2px; font-size: 11px;} 
        """)

        # Değişkenler
        self.telemetri_verisi = TelemetriVerisi()
        self.seri_port = None
        self.takim_no = "71523"
        self.son_harita_lat = 0.0
        self.son_harita_lon = 0.0

        # Dosya Hazırlığı
        if not os.path.exists("Loglar"): os.makedirs("Loglar")
        tarih = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        self.dosya_adi = f"Loglar/ucus_log_{tarih}.csv"

        self.header_list = [
            "PAKET NO", "UYDU STATÜSÜ", "HATA KODU", "GÖNDERME SAATİ", "BASINÇ",
            "YÜKSEKLİK", "İNİŞ HIZI", "SICAKLIK", "PİL GERİLİMİ", "GPS LAT", "GPS LON",
            "GPS ALT", "PITCH", "ROLL", "YAW", "RHRHRH", "TAKIM NO"
        ]

        with open(self.dosya_adi, 'w', encoding='utf-8') as f:
            f.write(",".join(self.header_list) + "\n")

        # --- ANA DÜZEN ---
        self.merkez_widget = QWidget(self)
        self.setCentralWidget(self.merkez_widget)
        self.ana_layout = QVBoxLayout()
        self.merkez_widget.setLayout(self.ana_layout)

        # 1. ÜST BÖLÜM
        self.ust_layout = QHBoxLayout()
        self.ust_layout.setSpacing(10)

        # KAMERA
        self.grp_kamera = QGroupBox("KAMERA")
        self.layout_kamera = QVBoxLayout()
        self.grp_kamera.setLayout(self.layout_kamera)
        self.video_etiketi = QLabel("SİNYAL YOK")
        self.video_etiketi.setStyleSheet("background-color: black; color: white;")
        self.video_etiketi.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_etiketi.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout_kamera.addWidget(self.video_etiketi)
        self.ust_layout.addWidget(self.grp_kamera, 30)

        # GPS HARİTA
        self.grp_gps = QGroupBox("GPS KONUM")
        self.layout_gps = QVBoxLayout()
        self.grp_gps.setLayout(self.layout_gps)

        self.harita_widget = QWebEngineView()
        self.layout_gps.addWidget(self.harita_widget)
        self.ust_layout.addWidget(self.grp_gps, 30)

        self.haritayi_ciz(39.92, 32.85)

        # 3D SİMÜLASYON
        self.grp_sim = QGroupBox("3D SİMÜLASYON")
        self.layout_sim = QVBoxLayout()
        self.grp_sim.setLayout(self.layout_sim)

        self.gl_widget = gl.GLViewWidget()
        self.gl_widget.setBackgroundColor('#121212')
        self.gl_widget.setCameraPosition(distance=30)

        axis = gl.GLAxisItem()
        self.gl_widget.addItem(axis)

        self.layout_sim.addWidget(self.gl_widget)
        self.ust_layout.addWidget(self.grp_sim, 30)

        grid = gl.GLGridItem()
        self.gl_widget.addItem(grid)

        self.uydu_3d = gl.GLBoxItem(size=pg.Vector(5, 5, 10), color=(52, 152, 219, 255))
        self.gl_widget.addItem(self.uydu_3d)

        # YAZILIM DURUMU
        self.grp_akis = QGroupBox("AKIŞ")
        self.layout_akis = QVBoxLayout()
        self.grp_akis.setLayout(self.layout_akis)

        self.chk_baslangic = QCheckBox("1. Başlatıldı")
        self.chk_kalibrasyon = QCheckBox("2. Kalibrasyon")
        self.chk_yukselme = QCheckBox("3. Yükselme")
        self.chk_ayrilma = QCheckBox("4. Ayrılma")
        self.chk_inis = QCheckBox("5. İniş")
        self.chk_kurtarma = QCheckBox("6. Bitiş")

        for chk in [self.chk_baslangic, self.chk_kalibrasyon, self.chk_yukselme, self.chk_ayrilma, self.chk_inis, self.chk_kurtarma]:
            chk.setEnabled(False)
            chk.setStyleSheet("color: #ccc; font-weight: normal; font-size: 10px;")
            self.layout_akis.addWidget(chk)

        self.chk_baslangic.setChecked(True)
        self.layout_akis.addStretch()
        self.ust_layout.addWidget(self.grp_akis, 10)
        self.ana_layout.addLayout(self.ust_layout, 40)

        # 2. ALT BÖLÜM
        self.alt_layout = QHBoxLayout()

        # GRAFİKLER
        self.widget_grafikler = QWidget(self)
        self.layout_grafikler_v = QVBoxLayout()
        self.layout_grafikler_v.setContentsMargins(0, 0, 0, 0)
        self.widget_grafikler.setLayout(self.layout_grafikler_v)

        pg.setConfigOption('background', '#1e1e1e')
        pg.setConfigOption('foreground', 'w')

        self.g_hiz = pg.PlotWidget(title="1. İniş Hızı (m/s)")
        self.g_hiz.showGrid(x=True, y=True)
        self.g_hiz.addItem(pg.InfiniteLine(pos=8, angle=0, pen=pg.mkPen('y', style=Qt.PenStyle.DashLine)))
        self.g_hiz.addItem(pg.InfiniteLine(pos=10, angle=0, pen=pg.mkPen('y', style=Qt.PenStyle.DashLine)))
        self.curve_hiz = self.g_hiz.plot(pen=pg.mkPen('#e74c3c', width=2))

        self.g_irtifa = pg.PlotWidget(title="2. Yükseklik (m)")
        self.g_irtifa.showGrid(x=True, y=True)
        self.curve_irtifa = self.g_irtifa.plot(pen=pg.mkPen('#3498db', width=2))

        self.g_sicaklik = pg.PlotWidget(title="3. Sıcaklık (°C)")
        self.g_sicaklik.showGrid(x=True, y=True)
        self.curve_sicaklik = self.g_sicaklik.plot(pen=pg.mkPen('#1abc9c', width=2))

        self.g_basinc = pg.PlotWidget(title="4. Basınç (Pa)")
        self.g_basinc.showGrid(x=True, y=True)
        self.curve_basinc = self.g_basinc.plot(pen=pg.mkPen('#9b59b6', width=2))

        self.g_pil = pg.PlotWidget(title="5. Pil (V)")
        self.g_pil.showGrid(x=True, y=True)
        self.curve_pil = self.g_pil.plot(pen=pg.mkPen('#f1c40f', width=2))

        for g in [self.g_hiz, self.g_irtifa, self.g_sicaklik, self.g_basinc, self.g_pil]:
            self.layout_grafikler_v.addWidget(g)

        self.alt_layout.addWidget(self.widget_grafikler, 25)

        # TABLO
        self.grp_tablo = QGroupBox("CANLI VERİ AKIŞI")
        self.layout_tablo_kutu = QVBoxLayout()
        self.grp_tablo.setLayout(self.layout_tablo_kutu)

        self.tablo = QTableWidget(self)
        self.tablo.setColumnCount(len(self.header_list))
        self.tablo.setHorizontalHeaderLabels(self.header_list)
        self.tablo.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tablo.horizontalHeader().setStretchLastSection(False)
        self.tablo.verticalHeader().setVisible(False)
        self.tablo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.layout_tablo_kutu.addWidget(self.tablo)

        self.alt_layout.addWidget(self.grp_tablo, 55)

        # KONTROL PANELİ
        self.grp_kontrol = QGroupBox("KONTROL MERKEZİ")
        self.layout_kontrol = QVBoxLayout()
        self.grp_kontrol.setLayout(self.layout_kontrol)

        self.h_baglanti = QHBoxLayout()
        self.combo_port = QComboBox(self)

        self.btn_yenile = QPushButton("🔄")
        self.btn_yenile.setStyleSheet("background-color: #555; max-width: 30px;")
        self.btn_yenile.clicked.connect(self.portlari_guncelle)

        self.btn_baglan = QPushButton("BAĞLAN")
        self.btn_baglan.setStyleSheet("background-color: #2980b9;")
        self.btn_baglan.clicked.connect(self.baglanti_yonet)

        self.h_baglanti.addWidget(QLabel("Port:"))
        self.h_baglanti.addWidget(self.combo_port)
        self.h_baglanti.addWidget(self.btn_yenile)
        self.h_baglanti.addWidget(self.btn_baglan)
        self.layout_kontrol.addLayout(self.h_baglanti)

        self.portlari_guncelle()

        self.layout_kontrol.addSpacing(15)

        self.layout_kontrol.addWidget(QLabel("ARAS DURUMU:"))
        self.h_aras = QHBoxLayout()
        self.h_aras.setSpacing(5)
        self.ind_hiz = QLabel("HIZ")
        self.ind_gps = QLabel("GPS")
        self.ind_sep = QLabel("AYR")
        self.ind_par = QLabel("PAR")

        base_style = "background:gray; padding:8px; border-radius:3px; font-weight:bold; color:white;"
        for lbl in [self.ind_hiz, self.ind_gps, self.ind_sep, self.ind_par]:
            lbl.setStyleSheet(base_style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.h_aras.addWidget(lbl)
        self.layout_kontrol.addLayout(self.h_aras)

        self.layout_kontrol.addSpacing(20)

        self.btn_ayrilma = QPushButton("MANUEL AYRILMA")
        self.btn_ayrilma.setStyleSheet("background-color: #c0392b; height: 40px;")
        self.layout_kontrol.addWidget(self.btn_ayrilma)

        self.layout_kontrol.addSpacing(5)

        self.btn_kalibre = QPushButton("İRTİFA SIFIRLA")
        self.btn_kalibre.setStyleSheet("background-color: #f39c12; color: black; height: 35px;")
        self.layout_kontrol.addWidget(self.btn_kalibre)

        # TEST BUTONU
        self.layout_kontrol.addSpacing(15)
        self.btn_test = QPushButton("🛠️ SAHTE VERİ GÖNDER (TEST)")
        self.btn_test.setStyleSheet("background-color: #8e44ad; height: 30px;")
        self.btn_test.clicked.connect(self.test_verisi_olustur)
        self.layout_kontrol.addWidget(self.btn_test)

        self.layout_kontrol.addStretch()

        self.lbl_log_mini = QLabel("Sistem Hazır. Port Seçin.")
        self.lbl_log_mini.setStyleSheet("color: gray; font-size: 11px;")
        self.lbl_log_mini.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.layout_kontrol.addWidget(self.lbl_log_mini)

        self.alt_layout.addWidget(self.grp_kontrol, 20)
        self.ana_layout.addLayout(self.alt_layout, 60)

        # --- BAŞLATMA ---
        self.thread = VideoThread(self)
        self.thread.change_pixmap_signal.connect(self.video_guncelle)
        self.thread.start()

        self.veri_zaman, self.veri_basinc, self.veri_irtifa = [], [], []
        self.veri_hiz, self.veri_sicaklik, self.veri_pil = [], [], []

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.seri_port_dinle)
        self.timer.start(100)

    # SINIF FONKSİYONLARI

    def portlari_guncelle(self):
        self.combo_port.clear()
        portlar = serial.tools.list_ports.comports()
        if portlar:
            for port in portlar:
                self.combo_port.addItem(port.device)
        else:
            self.combo_port.addItem("PORT YOK")

    def video_guncelle(self, frame):
        qt_img = self.convert_cv_qt(frame)
        self.video_etiketi.setPixmap(qt_img)

    def convert_cv_qt(self, cv_img):
        h, w, ch = cv_img.shape
        bytes_per_line = ch * w
        convert_to_Qt_format = QImage(cv_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        p = convert_to_Qt_format.scaled(self.video_etiketi.width(), self.video_etiketi.height(),
                                        Qt.AspectRatioMode.KeepAspectRatio)
        return QPixmap.fromImage(p)

    def baglanti_yonet(self):
        if self.seri_port and self.seri_port.is_open:
            self.seri_port.close()
            self.btn_baglan.setText("BAĞLAN")
            self.btn_baglan.setStyleSheet("background-color: #2980b9;")
            self.lbl_log_mini.setText("BAĞLANTI KESİLDİ")
        else:
            port_adi = self.combo_port.currentText()
            try:
                self.seri_port = serial.Serial(port_adi, 115200, timeout=0.1)
                self.btn_baglan.setText("KOPAR")
                self.btn_baglan.setStyleSheet("background-color: #c0392b;")
                self.lbl_log_mini.setText(f"BAŞARILI: {port_adi}")
            except Exception as e:
                self.lbl_log_mini.setText(f"HATA: PORT AÇILAMADI ({port_adi})")

    def seri_port_dinle(self):
        if self.seri_port and self.seri_port.is_open:
            try:
                if self.seri_port.in_waiting > 0:
                    gelen_veri = self.seri_port.readline().decode('utf-8', errors='ignore').strip()
                    if not gelen_veri: return
                    self.veriyi_ayristir_ve_guncelle(gelen_veri)
            except Exception as e:
                pass

    def test_verisi_olustur(self):
        saat = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        pkt = getattr(self.telemetri_verisi, 'paket_numarasi', 0) + 1

        basinc = 1012.5 + random.uniform(-2, 2)
        yuk = 250.3 + random.uniform(-5, 5)
        hiz = 9.5 + random.uniform(-1, 1)
        sicaklik = 24.2 + random.uniform(-0.5, 0.5)
        pil = 8.1 - (pkt * 0.005)
        lat = 39.92 + random.uniform(-0.0001, 0.0001)
        lon = 32.85 + random.uniform(-0.0001, 0.0001)
        alt = 1330.3 + random.uniform(-2, 2)
        pitch = 15 + random.uniform(-2, 2)
        roll = -5 + random.uniform(-2, 2)
        yaw = 200 + random.uniform(-5, 5)
        rhrhrh = "1A2B3C"

        sahte_paket = f"{pkt},4,0000,{saat},{basinc:.2f},{yuk:.2f},{hiz:.2f},{sicaklik:.2f},{pil:.2f},{lat:.5f},{lon:.5f},{alt:.2f},{pitch:.1f},{roll:.1f},{yaw:.1f},{rhrhrh},{self.takim_no}"

        self.lbl_log_mini.setText("TEST VERİSİ GELDİ")
        self.veriyi_ayristir_ve_guncelle(sahte_paket)

    def veriyi_ayristir_ve_guncelle(self, gelen_veri):
        veriler = gelen_veri.split(',')
        if len(veriler) == 17:
            try:
                self.telemetri_verisi.paket_numarasi = int(veriler[0])
                self.telemetri_verisi.uydu_statu = veriler[1]
                self.telemetri_verisi.hata_kodu = veriler[2]
                self.telemetri_verisi.gonderme_saati = veriler[3]
                self.telemetri_verisi.basinc = float(veriler[4])
                self.telemetri_verisi.yukseklik = float(veriler[5])
                self.telemetri_verisi.inis_hizi = float(veriler[6])
                self.telemetri_verisi.sicaklik = float(veriler[7])
                self.telemetri_verisi.pil_gerilimi = float(veriler[8])
                self.telemetri_verisi.gps_lat = float(veriler[9])
                self.telemetri_verisi.gps_lon = float(veriler[10])
                self.telemetri_verisi.gps_alt = float(veriler[11])
                self.telemetri_verisi.pitch = float(veriler[12])
                self.telemetri_verisi.roll = float(veriler[13])
                self.telemetri_verisi.yaw = float(veriler[14])
                self.telemetri_verisi.rhrhrh = veriler[15]
                self.takim_no = veriler[16]

                self.arayuzu_guncelle()
            except ValueError:
                pass

    def haritayi_ciz(self, lat, lon):
        if lat == 0.0 or lon == 0.0:
            return

        if abs(self.son_harita_lat - lat) < 0.0001 and abs(self.son_harita_lon - lon) < 0.0001:
            return

        self.son_harita_lat = lat
        self.son_harita_lon = lon

        m = folium.Map(location=[lat, lon], zoom_start=16, tiles='CartoDB positron')
        folium.Marker(
            [lat, lon],
            popup=f"Uydu\nLat: {lat:.5f}\nLon: {lon:.5f}",
            icon=folium.Icon(color="red", icon="rocket", prefix='fa')
        ).add_to(m)

        data = io.BytesIO()
        m.save(data, close_file=False)
        self.harita_widget.setHtml(data.getvalue().decode())

    def arayuzu_guncelle(self):
        # Hata kodu kontrolleri [cite: 298, 299, 300, 304]
        is_hiz_ok = 8 <= self.telemetri_verisi.inis_hizi <= 10
        is_gps_ok = self.telemetri_verisi.gps_lat != 0
        is_ayrilma_ok = int(self.telemetri_verisi.uydu_statu) >= 3 # 3: Ayrılma, 4: Görev Yükü İniş, 5: Kurtarma [cite: 363, 364, 365]
        is_parasut_ok = False # Acil durum butonu basılmadıkça veya algoritmik tetiklenmedikçe False olmalı

        def get_style(is_ok, reverse=False):
            color = "#27ae60" if is_ok else "#c0392b"
            if reverse: color = "#c0392b" if is_ok else "#27ae60"
            return f"background:{color}; padding:8px; border-radius:3px; font-weight:bold; color:white;"

        self.ind_hiz.setStyleSheet(get_style(is_hiz_ok))
        self.ind_gps.setStyleSheet(get_style(is_gps_ok))
        self.ind_sep.setStyleSheet(get_style(is_ayrilma_ok))
        self.ind_par.setStyleSheet(get_style(is_parasut_ok, reverse=True))

        # Akış Checkbox'larının güncellenmesi
        statu_int = int(self.telemetri_verisi.uydu_statu)
        if statu_int >= 1: self.chk_yukselme.setChecked(True)
        if statu_int >= 3: self.chk_ayrilma.setChecked(True)
        if statu_int >= 4: self.chk_inis.setChecked(True)
        if statu_int == 5: self.chk_kurtarma.setChecked(True)

        row_data = [
            str(self.telemetri_verisi.paket_numarasi), self.telemetri_verisi.uydu_statu,
            self.telemetri_verisi.hata_kodu, self.telemetri_verisi.gonderme_saati,
            f"{self.telemetri_verisi.basinc:.2f}", f"{self.telemetri_verisi.yukseklik:.2f}",
            f"{self.telemetri_verisi.inis_hizi:.2f}", f"{self.telemetri_verisi.sicaklik:.1f}",
            f"{self.telemetri_verisi.pil_gerilimi:.2f}", str(self.telemetri_verisi.gps_lat),
            str(self.telemetri_verisi.gps_lon), f"{self.telemetri_verisi.gps_alt:.1f}",
            f"{self.telemetri_verisi.pitch:.0f}", f"{self.telemetri_verisi.roll:.0f}",
            f"{self.telemetri_verisi.yaw:.0f}", self.telemetri_verisi.rhrhrh, self.takim_no
        ]

        with open(self.dosya_adi, 'a', encoding='utf-8') as f:
            f.write(",".join(row_data) + "\n")

        row = self.tablo.rowCount()
        self.tablo.insertRow(row)
        for i, val in enumerate(row_data):
            self.tablo.setItem(row, i, QTableWidgetItem(val))
        self.tablo.scrollToBottom()

        self.veri_zaman.append(self.telemetri_verisi.paket_numarasi)
        self.veri_basinc.append(self.telemetri_verisi.basinc)
        self.veri_irtifa.append(self.telemetri_verisi.yukseklik)
        self.veri_hiz.append(self.telemetri_verisi.inis_hizi)
        self.veri_sicaklik.append(self.telemetri_verisi.sicaklik)
        self.veri_pil.append(self.telemetri_verisi.pil_gerilimi)

        if len(self.veri_zaman) > 50:
            for l in [self.veri_zaman, self.veri_basinc, self.veri_irtifa, self.veri_hiz, self.veri_sicaklik, self.veri_pil]:
                l.pop(0)

        self.curve_hiz.setData(self.veri_zaman, self.veri_hiz)
        self.curve_irtifa.setData(self.veri_zaman, self.veri_irtifa)
        self.curve_sicaklik.setData(self.veri_zaman, self.veri_sicaklik)
        self.curve_basinc.setData(self.veri_zaman, self.veri_basinc)
        self.curve_pil.setData(self.veri_zaman, self.veri_pil)

        self.haritayi_ciz(self.telemetri_verisi.gps_lat, self.telemetri_verisi.gps_lon)

        transform = pg.Transform3D()
        transform.rotate(self.telemetri_verisi.roll, 1, 0, 0)
        transform.rotate(self.telemetri_verisi.pitch, 0, 1, 0)
        transform.rotate(self.telemetri_verisi.yaw, 0, 0, 1)
        transform.translate(-2.5, -2.5, -5)
        self.uydu_3d.setTransform(transform)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    pencere = YerIstasyonu()
    pencere.show()
    sys.exit(app.exec())