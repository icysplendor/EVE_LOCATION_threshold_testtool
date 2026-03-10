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
        # 无边框 + 顶层 + 工具窗口(避免任务栏图标)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.Tool)
        
        # 设置半透明黑色背景
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.pos()
            self.rubberBand.setGeometry(QRect(self.origin, QSize()))
            self.rubberBand.show()

    def mouseMoveEvent(self, event):
        if not self.origin.isNull():
            self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            rect = self.rubberBand.geometry()
            
            # 转换为屏幕绝对坐标
            global_pos = self.mapToGlobal(rect.topLeft())
            
            x = int(global_pos.x())
            y = int(global_pos.y())
            w = int(rect.width())
            h = int(rect.height())
            
            # 发送坐标前做一下防抖，防止误触宽高为0
            if w > 5 and h > 5:
                self.on_selected(x, y, w, h)
            
            self.close()
            
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

# ==========================================
# 2. 主窗口 (实时预览 + 调节)
# ==========================================
class TunerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVE Threshold Tuner")
        self.resize(800, 500)
        self.setStyleSheet("background-color: #222; color: #EEE; font-family: Consolas;")
        
        self.sct = mss.mss()
        self.monitor_region = None # {top, left, width, height}
        
        # 初始阈值
        self.threshold_coarse = 180
        self.threshold_fine = 0
        
        self.setup_ui()
        
        # 定时器：每 100ms (10 FPS) 截取一次并处理
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_frame)
        self.timer.start(100)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # --- 顶部按钮 ---
        self.btn_select = QPushButton("1. Select Screen Region")
        self.btn_select.setFixedHeight(40)
        self.btn_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_select.setStyleSheet("""
            QPushButton { background: #007ACC; color: white; font-weight: bold; font-size: 14px; border-radius: 4px; }
            QPushButton:hover { background: #005A9E; }
        """)
        self.btn_select.clicked.connect(self.start_selection)
        layout.addWidget(self.btn_select)
        
        # --- 图像预览区 ---
        img_layout = QHBoxLayout()
        img_layout.setSpacing(20)
        
        # 左侧：原图
        vbox_l = QVBoxLayout()
        lbl_l = QLabel("Original")
        lbl_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_original = QLabel()
        self.lbl_original.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_original.setStyleSheet("border: 1px solid #555; background: #000;")
        self.lbl_original.setMinimumSize(300, 150)
        vbox_l.addWidget(lbl_l)
        vbox_l.addWidget(self.lbl_original)
        
        # 右侧：处理后
        vbox_r = QVBoxLayout()
        lbl_r = QLabel("Processed (Binary)")
        lbl_r.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_processed = QLabel()
        self.lbl_processed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_processed.setStyleSheet("border: 1px solid #00FF00; background: #000;")
        self.lbl_processed.setMinimumSize(300, 150)
        vbox_r.addWidget(lbl_r)
        vbox_r.addWidget(self.lbl_processed)
        
        img_layout.addLayout(vbox_l)
        img_layout.addLayout(vbox_r)
        layout.addLayout(img_layout)
        
        # --- 阈值显示 ---
        self.lbl_val = QLabel("Current Threshold: 180")
        self.lbl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_val.setStyleSheet("font-size: 24px; color: #00FF00; font-weight: bold; margin: 10px;")
        layout.addWidget(self.lbl_val)
        
        # --- 滑块区域 ---
        slider_layout = QVBoxLayout()
        
        # 滑块 1: 粗调 (130 - 250)
        row1 = QHBoxLayout()
        lbl_c = QLabel("Coarse (10s):")
        lbl_c.setFixedWidth(100)
        self.slider_coarse = QSlider(Qt.Orientation.Horizontal)
        self.slider_coarse.setRange(130, 250)
        self.slider_coarse.setSingleStep(10)
        self.slider_coarse.setPageStep(10)
        self.slider_coarse.setValue(180)
        self.slider_coarse.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_coarse.setTickInterval(10)
        self.slider_coarse.valueChanged.connect(self.update_threshold)
        
        self.lbl_coarse_val = QLabel("180")
        self.lbl_coarse_val.setFixedWidth(40)
        self.lbl_coarse_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        row1.addWidget(lbl_c)
        row1.addWidget(self.slider_coarse)
        row1.addWidget(self.lbl_coarse_val)
        slider_layout.addLayout(row1)
        
        # 滑块 2: 微调 (0 - 9)
        row2 = QHBoxLayout()
        lbl_f = QLabel("Fine (1s):")
        lbl_f.setFixedWidth(100)
        self.slider_fine = QSlider(Qt.Orientation.Horizontal)
        self.slider_fine.setRange(0, 9)
        self.slider_fine.setValue(0)
        self.slider_fine.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_fine.setTickInterval(1)
        self.slider_fine.valueChanged.connect(self.update_threshold)
        
        self.lbl_fine_val = QLabel("0")
        self.lbl_fine_val.setFixedWidth(40)
        self.lbl_fine_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        
        row2.addWidget(lbl_f)
        row2.addWidget(self.slider_fine)
        row2.addWidget(self.lbl_fine_val)
        slider_layout.addLayout(row2)
        
        layout.addLayout(slider_layout)

    def start_selection(self):
        self.selector = RegionSelector(self.set_region)
        self.selector.show()

    def set_region(self, x, y, w, h):
        self.monitor_region = {"top": int(y), "left": int(x), "width": int(w), "height": int(h)}
        self.setWindowTitle(f"Monitoring Region: {x},{y} {w}x{h}")

    def update_threshold(self):
        # 强制取整逻辑
        c_raw = self.slider_coarse.value()
        # 确保粗调是 10 的倍数
        c = int(c_raw / 10) * 10 
        
        # 如果滑块不在整10位置，修正它
        if c != c_raw:
            self.slider_coarse.blockSignals(True)
            self.slider_coarse.setValue(c)
            self.slider_coarse.blockSignals(False)
            
        f = self.slider_fine.value()
        
        total = c + f
        if total > 255: total = 255
        
        self.threshold_coarse = c
        self.threshold_fine = f
        
        self.lbl_coarse_val.setText(str(c))
        self.lbl_fine_val.setText(str(f))
        self.lbl_val.setText(f"Current Threshold: {total}")

    def process_frame(self):
        if not self.monitor_region:
            return

        try:
            # 1. 截图 (BGRA)
            img = np.array(self.sct.grab(self.monitor_region))
            if img is None or img.size == 0: return
            
            # 2. 转 BGR 和 灰度
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            img_gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            
            # 3. 计算阈值
            thresh_val = self.threshold_coarse + self.threshold_fine
            if thresh_val > 255: thresh_val = 255
            
            # 4. 二值化 (不归一化)
            _, img_binary = cv2.threshold(img_gray, thresh_val, 255, cv2.THRESH_BINARY)
            
            # 5. 显示原图 (左) - OpenCV BGR -> Qt RGB
            self.display_image(self.lbl_original, img_bgr, is_binary=False)
            
            # 6. 显示处理后 (右) - OpenCV Gray (单通道) -> Qt RGB (三通道)
            # 必须转成三通道，否则 QImage 格式对不上会崩溃
            img_binary_rgb = cv2.cvtColor(img_binary, cv2.COLOR_GRAY2RGB)
            self.display_image(self.lbl_processed, img_binary_rgb, is_binary=True)
            
        except Exception as e:
            print(f"Frame Error: {e}")

    def display_image(self, label, img_np, is_binary):
        h, w = img_np.shape[:2]
        bytes_per_line = 3 * w
        
        # 这里的 img_np 必须是 RGB 格式 (OpenCV 默认是 BGR，所以上面要转)
        if not is_binary:
            img_np = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
            
        qimg = QImage(img_np.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        
        # 保持比例缩放
        pix = QPixmap.fromImage(qimg).scaled(
            label.width(), label.height(), 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        label.setPixmap(pix)

if __name__ == "__main__":
    # 适配高分屏
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    win = TunerWindow()
    win.show()
    sys.exit(app.exec())
