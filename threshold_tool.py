import sys
import cv2
import numpy as np
import mss
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QSlider, QRubberBand)
from PyQt6.QtCore import Qt, QTimer, QRect, QPoint, QSize
from PyQt6.QtGui import QImage, QPixmap

# ==========================================
# 🔍 选区工具 (半透明遮罩)
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
# 🎛️ 主控制窗口
# ==========================================
class ThresholdTool(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVE Threshold Tuner")
        self.resize(400, 350)
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint)
        
        self.sct = mss.mss()
        self.monitor_region = None
        self.threshold_val = 180 # 默认值
        
        self.init_ui()
        
        # 定时器：30 FPS 刷新画面
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # 1. 选区按钮
        self.btn_select = QPushButton("1. Select Screen Region")
        self.btn_select.setFixedHeight(40)
        self.btn_select.clicked.connect(self.start_selection)
        layout.addWidget(self.btn_select)
        
        # 2. 阈值显示
        self.lbl_val = QLabel(f"Current Threshold: {self.threshold_val}")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_val.setStyleSheet("font-size: 16px; font-weight: bold; color: blue;")
        layout.addWidget(self.lbl_val)
        
        # 3. 滑块控制区
        slider_layout = QVBoxLayout()
        
        # 粗调 (10步进)
        self.slider_coarse = QSlider(Qt.Orientation.Horizontal)
        self.slider_coarse.setRange(13, 25) # 130 - 250
        self.slider_coarse.setValue(18)
        self.slider_coarse.valueChanged.connect(self.update_threshold)
        slider_layout.addWidget(QLabel("Coarse (130-250):"))
        slider_layout.addWidget(self.slider_coarse)
        
        # 微调 (1步进)
        self.slider_fine = QSlider(Qt.Orientation.Horizontal)
        self.slider_fine.setRange(0, 9) # 0 - 9
        self.slider_fine.setValue(0)
        self.slider_fine.valueChanged.connect(self.update_threshold)
        slider_layout.addWidget(QLabel("Fine (0-9):"))
        slider_layout.addWidget(self.slider_fine)
        
        layout.addLayout(slider_layout)
        
        # 4. 预览区域
        self.lbl_preview = QLabel("Waiting for selection...")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("border: 2px dashed gray; background: #eee;")
        self.lbl_preview.setMinimumHeight(150)
        layout.addWidget(self.lbl_preview)

    def start_selection(self):
        self.selector = RegionSelector(self.set_region)
        self.selector.show()

    def set_region(self, x, y, w, h):
        self.monitor_region = {"top": y, "left": x, "width": w, "height": h}
        self.btn_select.setText(f"Region: {x},{y} {w}x{h}")

    def update_threshold(self):
        # 计算总阈值 = 粗调*10 + 微调
        coarse = self.slider_coarse.value() * 10
        fine = self.slider_fine.value()
        self.threshold_val = coarse + fine
        self.lbl_val.setText(f"Current Threshold: {self.threshold_val}")

    def update_frame(self):
        if not self.monitor_region:
            return
            
        try:
            # 1. 截图
            img = np.array(self.sct.grab(self.monitor_region))
            
            # 2. 转灰度 (BGRA -> Gray)
            gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
            
            # 3. 二值化处理 (核心逻辑)
            # 注意：这里我们不做归一化，直接用阈值，方便您找绝对值
            _, binary = cv2.threshold(gray, self.threshold_val, 255, cv2.THRESH_BINARY)
            
            # 4. 显示到界面
            # 将二值图转回 RGB 以便 Qt 显示
            display_img = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
            h, w, ch = display_img.shape
            bytes_per_line = ch * w
            qt_img = QImage(display_img.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
            
            # 缩放以适应窗口
            pixmap = QPixmap.fromImage(qt_img)
            scaled_pixmap = pixmap.scaled(self.lbl_preview.size(), Qt.AspectRatioMode.KeepAspectRatio)
            self.lbl_preview.setPixmap(scaled_pixmap)
            
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ThresholdTool()
    window.show()
    sys.exit(app.exec())
