import sys
import cv2
import numpy as np
import mss
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QSlider, QRubberBand)
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, QSize
from PyQt6.QtGui import QImage, QPixmap

# ==========================================
# 1. 选区工具 (透明覆盖层)
# ==========================================
class RegionSelector(QWidget):
    def __init__(self, on_selected):
        super().__init__()
        self.on_selected = on_selected
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setStyleSheet("background-color: black;")
        self.setWindowOpacity(0.3)
        self.setCursor(Qt.CursorShape.CrossCursor)
        
        # 覆盖所有屏幕
        total_rect = QRect()
        for screen in QApplication.screens():
            total_rect = total_rect.united(screen.geometry())
        self.setGeometry(total_rect)
        
        self.rubberBand = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.origin = QPoint()

    def mousePressEvent(self, event):
        self.origin = event.pos()
        self.rubberBand.setGeometry(QRect(self.origin, QSize()))
        self.rubberBand.show()

    def mouseMoveEvent(self, event):
        self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        rect = self.rubberBand.geometry()
        # 转换为屏幕绝对坐标
        global_pos = self.mapToGlobal(rect.topLeft())
        x, y, w, h = global_pos.x(), global_pos.y(), rect.width(), rect.height()
        
        if w > 5 and h > 5:
            self.on_selected(x, y, w, h)
        self.close()

# ==========================================
# 2. 主窗口 (实时预览 + 调节)
# ==========================================
class TunerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVE Threshold Tuner")
        self.resize(600, 400)
        self.setStyleSheet("background-color: #222; color: #EEE;")
        
        self.sct = mss.mss()
        self.monitor_region = None # {top, left, width, height}
        
        self.threshold_coarse = 180
        self.threshold_fine = 0
        
        self.setup_ui()
        
        # 定时器：每 100ms (10 FPS) 截取一次并处理
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_frame)
        self.timer.start(100)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # --- 顶部按钮 ---
        self.btn_select = QPushButton("1. Select Screen Region")
        self.btn_select.setFixedHeight(40)
        self.btn_select.setStyleSheet("background: #007ACC; font-weight: bold; font-size: 14px;")
        self.btn_select.clicked.connect(self.start_selection)
        layout.addWidget(self.btn_select)
        
        # --- 图像预览区 ---
        img_layout = QHBoxLayout()
        
        self.lbl_original = QLabel("Original")
        self.lbl_original.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_original.setStyleSheet("border: 1px solid #555; background: #000;")
        self.lbl_original.setMinimumSize(200, 100)
        
        self.lbl_processed = QLabel("Processed (Binary)")
        self.lbl_processed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_processed.setStyleSheet("border: 1px solid #00FF00; background: #000;")
        self.lbl_processed.setMinimumSize(200, 100)
        
        img_layout.addWidget(self.lbl_original)
        img_layout.addWidget(self.lbl_processed)
        layout.addLayout(img_layout)
        
        # --- 阈值显示 ---
        self.lbl_val = QLabel("Current Threshold: 180")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_val.setStyleSheet("font-size: 18px; color: #00FF00; font-weight: bold; margin: 10px;")
        layout.addWidget(self.lbl_val)
        
        # --- 滑块 1: 粗调 (130 - 250) ---
        layout.addWidget(QLabel("Coarse Adjustment (10s):"))
        self.slider_coarse = QSlider(Qt.Orientation.Horizontal)
        self.slider_coarse.setRange(130, 250)
        self.slider_coarse.setSingleStep(10)
        self.slider_coarse.setPageStep(10)
        self.slider_coarse.setValue(180)
        self.slider_coarse.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_coarse.setTickInterval(10)
        self.slider_coarse.valueChanged.connect(self.update_threshold)
        layout.addWidget(self.slider_coarse)
        
        # --- 滑块 2: 微调 (0 - 9) ---
        layout.addWidget(QLabel("Fine Adjustment (1s):"))
        self.slider_fine = QSlider(Qt.Orientation.Horizontal)
        self.slider_fine.setRange(0, 9)
        self.slider_fine.setValue(0)
        self.slider_fine.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_fine.setTickInterval(1)
        self.slider_fine.valueChanged.connect(self.update_threshold)
        layout.addWidget(self.slider_fine)

    def start_selection(self):
        self.selector = RegionSelector(self.set_region)
        self.selector.show()

    def set_region(self, x, y, w, h):
        # mss 需要整数且不能为0
        self.monitor_region = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
        self.setWindowTitle(f"Monitoring Region: {x},{y} {w}x{h}")

    def update_threshold(self):
        # 确保粗调是 10 的倍数 (虽然 slider 步长设了，但拖动可能不准，强制取整)
        c = self.slider_coarse.value()
        c = int(c / 10) * 10 
        f = self.slider_fine.value()
        
        total = c + f
        if total > 255: total = 255
        
        self.threshold_coarse = c
        self.threshold_fine = f
        self.lbl_val.setText(f"Current Threshold: {total}")

    def process_frame(self):
        if not self.monitor_region:
            return

        try:
            # 1. 截图
            img = np.array(self.sct.grab(self.monitor_region))
            # mss 返回 BGRA
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            
            # 2. 计算当前阈值
            thresh_val = self.threshold_coarse + self.threshold_fine
            if thresh_val > 255: thresh_val = 255
            
            # 3. 二值化处理
            _, img_binary = cv2.threshold(img_gray, thresh_val, 255, cv2.THRESH_BINARY)
            
            # 4. 显示原图 (左)
            self.display_image(self.lbl_original, img_bgr, is_binary=False)
            
            # 5. 显示处理后 (右) - 转回 BGR 以便显示
            self.display_image(self.lbl_processed, img_binary, is_binary=True)
            
        except Exception as e:
            print(f"Error: {e}")

    def display_image(self, label, img_np, is_binary):
        h, w = img_np.shape[:2]
        if is_binary:
            # 二值图是单通道，转为 RGB 方便 Qt 显示
            img_np = cv2.cvtColor(img_np, cv2.COLOR_GRAY2RGB)
        else:
            # OpenCV 是 BGR，Qt 需要 RGB
            img_np = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
            
        qimg = QImage(img_np.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        # 缩放以适应标签大小
        pix = QPixmap.fromImage(qimg).scaled(label.width(), label.height(), Qt.AspectRatioMode.KeepAspectRatio)
        label.setPixmap(pix)

if __name__ == "__main__":
    # 适配高分屏
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app = QApplication(sys.argv)
    win = TunerWindow()
    win.show()
    sys.exit(app.exec())
