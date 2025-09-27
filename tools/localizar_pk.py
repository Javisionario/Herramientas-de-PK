# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction, QInputDialog, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QCompleter, QPushButton, QMenu, QApplication,
    QListWidget, QListWidgetItem, QDialogButtonBox
)
from PyQt5.QtCore import QMimeData, QVariant
from qgis.gui import QgsVertexMarker
from qgis.core import (
    QgsPointXY, QgsCoordinateTransform, QgsProject, QgsCoordinateReferenceSystem,
    QgsWkbTypes, QgsVectorLayer, QgsFields, QgsField, QgsFeature, QgsGeometry,
    Qgis
)

EXPECTED_FIELD = "VIAS CALIBRADAS — rutas_calibradas_validacion_MATRICULA"

def formato_pk(pk_total):
    km = int(pk_total)
    m = int(round((pk_total - km) * 1000))
    return f"{km}+{m:03d}"

class LocalizarPK:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.history_menu = None
        self.history = []   # [(via, pk_km, map_pt)]
        self.markers = []   # [QgsVertexMarker, QgsVertexMarker]

    def create_action(self):
        import os
        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QAction, QMenu

        icon = QIcon(":/plugins/pk_tools/icons/localizar.png")
        self.action = QAction(icon, "Localizar PK", self.iface.mainWindow())
        self.action.setToolTip("Localizar punto según PK en vía calibrada")

        # Menú desplegable (historial, exportar, etc.)
        self.history_menu = QMenu(self.iface.mainWindow())
        self.history_menu.setTitle("Historial")
        self.action.setMenu(self.history_menu)

        # Acción principal → abrir el diálogo
        self.action.triggered.connect(self.run)

        # Inicializar menú
        self._update_history_menu()

        return self.action

    def initGui(self):
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        icon = QIcon(icon_path)
        self.action = QAction(icon, "Localizar PK", self.iface.mainWindow())
        self.action.setToolTip("Localizar punto según PK en vía calibrada")
        self.history_menu = QMenu(self.iface.mainWindow())
        self.history_menu.setTitle("Historial")
        self.action.setMenu(self.history_menu)
        self.action.triggered.connect(self.open_dialog)
        self.iface.addToolBarIcon(self.action)

        # Inicializar el menú en el orden solicitado
        self._update_history_menu()

    def unload(self):
        self.iface.removeToolBarIcon(self.action)

    def open_dialog(self):
        capas = [
            layer for layer in QgsProject.instance().mapLayers().values()
            if isinstance(layer, QgsVectorLayer)
            and layer.geometryType() == QgsWkbTypes.LineGeometry
            and QgsWkbTypes.hasM(layer.wkbType())
            and layer.fields().indexOf(EXPECTED_FIELD) != -1
        ]
        if not capas:
            self.iface.messageBar().pushInfo("Localizar PK", "No se encontró ninguna capa válida.")
            return

        if len(capas) == 1:
            layer = capas[0]
        else:
            items = [c.name() for c in capas]
            item, ok = QInputDialog.getItem(
                self.iface.mainWindow(), "Seleccione la capa",
                "Capa de vías calibradas:", items, 0, False
            )
            if not ok:
                return
            layer = next(c for c in capas if c.name() == item)

        self.layer = layer

        road_names = sorted({
            f[EXPECTED_FIELD]
            for f in layer.getFeatures()
            if f[EXPECTED_FIELD]
        })

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Localizar PK")
        vbox = QVBoxLayout()

        # Carretera
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("Carretera:"))
        self.le_road = QLineEdit()
        completer = QCompleter(road_names)
        self.le_road.setCompleter(completer)
        h1.addWidget(self.le_road)
        vbox.addLayout(h1)

        # PK (km + m)
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("Kilómetros:"))
        self.le_km = QLineEdit("0")
        h2.addWidget(self.le_km)
        h2.addWidget(QLabel("Metros (+):"))
        self.le_m = QLineEdit("000")
        h2.addWidget(self.le_m)
        vbox.addLayout(h2)

        # Botones
        hbtn = QHBoxLayout()
        hbtn.addStretch()
        btn_ok = QPushButton("OK")
        btn_cancel = QPushButton("Cancelar")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        hbtn.addWidget(btn_ok)
        hbtn.addWidget(btn_cancel)
        vbox.addLayout(hbtn)

        dlg.setLayout(vbox)
        if dlg.exec_() != QDialog.Accepted:
            return

        via = self.le_road.text().strip()
        try:
            km = float(self.le_km.text())
            m = int(self.le_m.text())
        except ValueError:
            self.iface.messageBar().pushWarning("Localizar PK", "Valores de km o m inválidos.")
            return

        pk_total_km = km + m / 1000.0
        self.locate(via, pk_total_km)

    def locate(self, via, pk_km):
        # 1) Buscar la feature
        field = EXPECTED_FIELD
        feat = next((f for f in self.layer.getFeatures() if f[field] == via), None)
        if not feat:
            self.iface.messageBar().pushInfo("Localizar PK", f"No se encontró vía '{via}'.")
            return

        # 2) Interpolar por M
        geom = feat.geometry()
        verts = list(geom.vertices())
        m_vals = [pt.m() for pt in verts]
        target_m = pk_km * 1000.0
        if target_m < m_vals[0] or target_m > m_vals[-1]:
            self.iface.messageBar().pushInfo("Localizar PK", f"PK {formato_pk(pk_km)} fuera de rango de la vía.")
            return

        idx = next(i for i in range(len(m_vals) - 1) if m_vals[i] <= target_m <= m_vals[i + 1])
        m1, m2 = m_vals[idx], m_vals[idx + 1]
        p0, p1 = verts[idx], verts[idx + 1]
        t = (target_m - m1) / (m2 - m1) if m2 != m1 else 0
        x = p0.x() + t * (p1.x() - p0.x())
        y = p0.y() + t * (p1.y() - p0.y())
        point_layer = QgsPointXY(x, y)

        # 3) Transformar al CRS del mapa
        map_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.layer.crs()
        map_pt = point_layer
        if layer_crs != map_crs:
            xf = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
            map_pt = xf.transform(point_layer)

        # 4) Dibujar marcador (limpiando anteriores)
        self._limpiar_marcadores()
        self._add_marker(map_pt, QColor(0, 0, 255))

        # 5) Preparar URL Street View y texto
        crs_wgs84 = QgsCoordinateTransform(map_crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
        pt_wgs = crs_wgs84.transform(map_pt)
        lat, lon = pt_wgs.y(), pt_wgs.x()
        url_sv = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lon:.6f}&heading=0&pitch=10&fov=250"

        message_text = (
            f"Vía: {via} – PK {formato_pk(pk_km)} ({pk_km:.3f} km) | "
            f"<a href='{url_sv}'>Ver en Street View ({lat:.6f},{lon:.6f})</a>"
        )
        msg = self.iface.messageBar().createMessage("Localizar PK", message_text)

        # Botones en la barra de mensajes
        btn_zoom = QPushButton("Zoom")
        btn_zoom.clicked.connect(lambda: self._zoom_al_punto(map_pt))
        msg.layout().addWidget(btn_zoom)

        btn_coord = QPushButton("Copiar coordenadas")
        def _copy_coords_link():
            coord_txt = f"{lat:.6f},{lon:.6f}"
            html = f'<a href="{url_sv}">{coord_txt}</a>'
            mime = QMimeData()
            mime.setText(coord_txt)   # texto plano
            mime.setHtml(html)        # enlace HTML
            QApplication.clipboard().setMimeData(mime)
        btn_coord.clicked.connect(_copy_coords_link)
        msg.layout().addWidget(btn_coord)

        btn_clear = QPushButton("Limpiar")
        btn_clear.clicked.connect(self._limpiar_marcadores)
        msg.layout().addWidget(btn_clear)

        self.iface.messageBar().pushWidget(msg, level=Qgis.Info)

        # 6) Historial
        self.history.insert(0, (via, pk_km, map_pt))
        self._update_history_menu()

    def _zoom_al_punto(self, punto):
        self.canvas.setCenter(punto)
        self.canvas.zoomScale(25000)
        self.canvas.refresh()

    def _limpiar_marcadores(self):
        for m in self.markers:
            self.canvas.scene().removeItem(m)
        self.markers = []

    def _add_marker(self, map_pt, color):
        ring = QgsVertexMarker(self.canvas)
        ring.setCenter(QgsPointXY(map_pt))
        ring.setColor(color)
        ring.setFillColor(QColor(0, 0, 0, 0))
        ring.setIconType(QgsVertexMarker.ICON_CIRCLE)
        ring.setIconSize(20)
        ring.setPenWidth(4)

        dot = QgsVertexMarker(self.canvas)
        dot.setCenter(QgsPointXY(map_pt))
        dot.setColor(color)
        dot.setFillColor(color)
        dot.setIconType(QgsVertexMarker.ICON_CIRCLE)
        dot.setIconSize(6)
        dot.setPenWidth(0)

        self.markers = [ring, dot]

    def _update_history_menu(self):
        self.history_menu.clear()

        # 1) Limpiar marcador
        act_clear = QAction("Limpiar marcador", self.iface.mainWindow())
        act_clear.triggered.connect(self._limpiar_marcadores)
        self.history_menu.addAction(act_clear)

        # 2) Exportar puntos
        act_export = QAction("Exportar puntos", self.iface.mainWindow())
        act_export.triggered.connect(self._exportar_historial)
        self.history_menu.addAction(act_export)

        # 3) Separador
        self.history_menu.addSeparator()

        # 4) Historial (más recientes primero)
        for via, pk_km, map_pt in self.history:
            texto = f"{via} – {formato_pk(pk_km)}"
            act = QAction(texto, self.iface.mainWindow())
            act.triggered.connect(lambda checked, v=via, p=pk_km, mp=map_pt: self._from_history(v, p, mp))
            self.history_menu.addAction(act)

    def _from_history(self, via, pk_km, map_pt):
        # Redibuja el marcador y muestra el mensaje
        self._limpiar_marcadores()
        self._add_marker(map_pt, QColor(0, 0, 255))

        crs_wgs84 = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )
        pt_wgs = crs_wgs84.transform(map_pt)
        lat, lon = pt_wgs.y(), pt_wgs.x()
        url_sv = f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat:.6f},{lon:.6f}&heading=0&pitch=10&fov=250"

        message_text = (
            f"Vía: {via} – PK {formato_pk(pk_km)} ({pk_km:.3f} km) | "
            f"<a href='{url_sv}'>Ver en Street View ({lat:.6f},{lon:.6f})</a>"
        )
        msg = self.iface.messageBar().createMessage("Localizar PK", message_text)

        btn_zoom = QPushButton("Zoom")
        btn_zoom.clicked.connect(lambda: self._zoom_al_punto(map_pt))
        msg.layout().addWidget(btn_zoom)

        btn_coord = QPushButton("Copiar coordenadas")
        def _copy_coords_link():
            coord_txt = f"{lat:.6f},{lon:.6f}"
            html = f'<a href="{url_sv}">{coord_txt}</a>'
            mime = QMimeData()
            mime.setText(coord_txt)
            mime.setHtml(html)
            QApplication.clipboard().setMimeData(mime)
        btn_coord.clicked.connect(_copy_coords_link)
        msg.layout().addWidget(btn_coord)

        btn_clear = QPushButton("Limpiar")
        btn_clear.clicked.connect(self._limpiar_marcadores)
        msg.layout().addWidget(btn_clear)

        self.iface.messageBar().pushWidget(msg, level=Qgis.Info)

    def _exportar_historial(self):
        if not self.history:
            self.iface.messageBar().pushWarning("Exportar", "No hay puntos en el historial.")
            return

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Exportar puntos del historial")
        vbox = QVBoxLayout()

        label = QLabel("Selecciona los puntos a exportar:")
        vbox.addWidget(label)

        list_widget = QListWidget()
        list_widget.setSelectionMode(QListWidget.MultiSelection)

        # Desmarcados por defecto, más recientes primero (self.history ya lo está)
        for i, (via, pk_km, _) in enumerate(self.history):
            texto = f"{via} – {formato_pk(pk_km)} ({pk_km:.3f} km)"
            item = QListWidgetItem(texto)
            item.setSelected(False)
            item.setData(1000, i)  # índice en self.history
            list_widget.addItem(item)

        vbox.addWidget(list_widget)

        # Botones: Marcar/Desmarcar todos
        hbtn = QHBoxLayout()
        btn_sel_all = QPushButton("Marcar todos")
        btn_unsel_all = QPushButton("Desmarcar todos")
        btn_sel_all.clicked.connect(lambda: [list_widget.item(i).setSelected(True) for i in range(list_widget.count())])
        btn_unsel_all.clicked.connect(lambda: [list_widget.item(i).setSelected(False) for i in range(list_widget.count())])
        hbtn.addWidget(btn_sel_all)
        hbtn.addWidget(btn_unsel_all)
        vbox.addLayout(hbtn)

        # Aceptar / Cancelar
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        vbox.addWidget(buttons)

        dlg.setLayout(vbox)
        if dlg.exec_() != QDialog.Accepted:
            return

        seleccionados = [item.data(1000) for item in list_widget.selectedItems()]
        if not seleccionados:
            return

        # Crear capa temporal (EPSG:4326)
        vl = QgsVectorLayer("Point?crs=EPSG:4326", "Localización de PKs", "memory")
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField("VIA", QVariant.String),
            QgsField("PK", QVariant.String)
        ])
        vl.updateFields()

        # Transformación a WGS84 desde CRS del mapa
        xf = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )

        for idx in seleccionados:
            via, pk_km, map_pt = self.history[idx]
            pt = xf.transform(map_pt)
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt)))
            feat.setAttributes([via, formato_pk(pk_km)])
            pr.addFeature(feat)

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)
    def run(self):
        """Método de entrada para integrarlo en el plugin unificado."""
        self.open_dialog()