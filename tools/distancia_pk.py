# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QInputDialog, QPushButton, QApplication
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapTool, QgsVertexMarker
from qgis.core import (
    QgsPointXY,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsProject,
    QgsCoordinateReferenceSystem,
    QgsWkbTypes,
    QgsVectorLayer,
    QgsSpatialIndex,
    Qgis
)

##CONFIGURACION
# Cambia "ID_ROAD" por el nombre de tu campo que identifique las vías,
# o cambia el campo que identifica las vías de tu capa de carreteras a ID_ROAD
EXPECTED_FIELD = "ID_ROAD"

def formato_pk(pk_total):
    """Devuelve PK en formato K+MMM. Km con 2 dígitos mínimos, metros 3 dígitos."""
    km = int(pk_total)
    m = int(round((pk_total - km) * 1000))
    # Ajuste por caso 999.5 m -> carry al km
    if m == 1000:
        km += 1
        m = 0
    return f"{km:02d}+{m:03d}"


class DistanciaPK:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.tool = None

    def initGui(self):
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        icon = QIcon(icon_path)
        self.action = QAction(icon, "Medir Distancia PK", self.iface.mainWindow())
        self.action.setToolTip("Mide distancia entre dos PKs sobre la misma vía")
        self.action.setCheckable(True)
        self.action.toggled.connect(self.toggle_tool)
        self.iface.addToolBarIcon(self.action)
        # Ya no nos auto-desmarcamos al cambiar de herramienta

    def unload(self):
        # Limpieza segura al desinstalar
        if self.tool:
            try:
                self.tool.reset()
            except Exception:
                pass
        if self.tool and self.canvas.mapTool() == self.tool:
            self.canvas.unsetMapTool(self.tool)
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def toggle_tool(self, checked):
        if checked:
            ok = self.activate_tool()
            if not ok and self.action:
                self.action.setChecked(False)
        else:
            # Al apagar: soltar herramienta y borrar marcadores
            if self.tool and self.canvas.mapTool() == self.tool:
                self.canvas.unsetMapTool(self.tool)
            if self.tool:
                self.tool.reset()

    def activate_tool(self):
        try:
            capas_validas = []
            for layer in QgsProject.instance().mapLayers().values():
                if (isinstance(layer, QgsVectorLayer)
                    and layer.geometryType() == QgsWkbTypes.LineGeometry
                    and QgsWkbTypes.hasM(layer.wkbType())
                    and layer.fields().indexOf(EXPECTED_FIELD) != -1):
                    capas_validas.append(layer)

            if not capas_validas:
                self.iface.messageBar().pushInfo("Distancia PK", "No se encontró ninguna capa válida.")
                return False

            if len(capas_validas) == 1:
                layer = capas_validas[0]
            else:
                items = [c.name() for c in capas_validas]
                item, ok = QInputDialog.getItem(
                    self.iface.mainWindow(),
                    "Seleccione la capa",
                    "Elija la capa de líneas con valores M:",
                    items, 0, False
                )
                if not ok:
                    return False
                layer = next(c for c in capas_validas if c.name() == item)

            if not self.tool:
                self.tool = DistanciaTool(self.iface, self.canvas, self.show_distance_message)

            # Asignar capa e índice sin cambiar la capa activa (no interrumpe edición)
            self.tool.layer = layer
            self.tool.index = QgsSpatialIndex(layer.getFeatures())
            self.tool.reset()  # Nueva sesión al activar

            self.canvas.setMapTool(self.tool)
            return True

        except Exception:
            self.iface.messageBar().pushWarning("Distancia PK", "Error inesperado al seleccionar capa.")
            return False

    def show_distance_message(self, nombre_via, pk1, pk2, dist_pk_km, dist_lineal_km):
        # Mostrar PKs SOLO en formato 00+000 para limpiar la barra
        pk1_str = formato_pk(pk1)
        pk2_str = formato_pk(pk2)

        # Mensaje compacto
        texto = (
            f"{nombre_via} | PK1: {pk1_str} · PK2: {pk2_str} | "
            f" Dist. PK: {dist_pk_km:.3f} km · Dist. Lineal: {dist_lineal_km:.3f} km"
        )

        msg = self.iface.messageBar().createMessage("Distancia PK", texto)

        # Botones de copiado
        btn_pk = QPushButton("Copiar distancia PK")
        btn_pk.clicked.connect(lambda: QApplication.clipboard().setText(f"{dist_pk_km:.3f} km"))

        btn_lin = QPushButton("Copiar distancia lineal")
        btn_lin.clicked.connect(lambda: QApplication.clipboard().setText(f"{dist_lineal_km:.3f} km"))

        msg.layout().addWidget(btn_pk)
        msg.layout().addWidget(btn_lin)

        self.iface.messageBar().pushWidget(msg, Qgis.Info)

    def run(self):
        """Activa la herramienta de distancia."""
        return self.activate_tool()

    def deactivate(self):
        """Desactiva la herramienta y limpia."""
        if self.tool:
            try:
                self.tool.reset()
            except Exception:
                pass
            if self.canvas.mapTool() == self.tool:
                self.canvas.unsetMapTool(self.tool)


class DistanciaTool(QgsMapTool):
    def __init__(self, iface, canvas, callback):
        super().__init__(canvas)
        self.iface = iface
        self.canvas = canvas
        self.callback = callback
        self.layer = None
        self.index = None
        self.reset()

    def reset(self):
        if hasattr(self, 'markers'):
            for m in self.markers:
                try:
                    self.canvas.scene().removeItem(m)
                except Exception:
                    pass
        self.markers = []
        self.pk_values = []
        self.line_distances = []
        self.first_feat = None
        self.click_count = 0

    def canvasReleaseEvent(self, event):
        pt_map = self.toMapCoordinates(event.pos())
        if self.click_count >= 2:
            self.reset()  # Mantener: nueva medición borra puntos
        self._process_click(pt_map)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            # Ya no borramos al perder el foco; solo soltamos la herramienta
            self.canvas.unsetMapTool(self)

    def _process_click(self, click_pt_map):
        try:
            if not self.layer or not self.index:
                self.iface.messageBar().pushWarning("Distancia PK", "No hay capa válida asignada.")
                return

            map_crs = self.canvas.mapSettings().destinationCrs()
            layer_crs = self.layer.crs()

            # clic en CRS de capa
            layer_pt = click_pt_map
            if map_crs != layer_crs:
                xf_to_layer = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
                layer_pt = xf_to_layer.transform(click_pt_map)

            if self.click_count == 0:
                # primer punto → localizar línea + proyección
                fids = self.index.nearestNeighbor(layer_pt, 5)
                closest_feat, proj_pt_layer = None, None
                min_d = float('inf')
                for fid in fids:
                    feat = self.layer.getFeature(fid)
                    near = feat.geometry().nearestPoint(QgsGeometry.fromPointXY(QgsPointXY(layer_pt)))
                    d = layer_pt.distance(near.asPoint())
                    if d < min_d:
                        min_d = d
                        closest_feat = feat
                        proj_pt_layer = near

                if not closest_feat:
                    self.iface.messageBar().pushInfo("Distancia PK", "No se encontró línea cercana.")
                    return

                self.first_feat = closest_feat
                pk1, dist1 = self._compute_pk_and_dist(closest_feat.geometry(), proj_pt_layer)

                # marcador en la PROYECCIÓN, transformado al CRS del mapa
                proj1_map = proj_pt_layer.asPoint()
                if map_crs != layer_crs:
                    xf_to_map = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
                    proj1_map = xf_to_map.transform(proj1_map)
                self._add_marker(proj1_map)

                self.pk_values.append(pk1)            # km
                self.line_distances.append(dist1)     # unidades de la capa (m si CRS métrico)
                self.click_count = 1

            else:
                # segundo punto → misma línea (self.first_feat)
                geom = self.first_feat.geometry()
                near_layer = geom.nearestPoint(QgsGeometry.fromPointXY(QgsPointXY(layer_pt)))
                pk2, dist2 = self._compute_pk_and_dist(geom, near_layer)

                # marcador en la PROYECCIÓN del segundo punto
                proj2_map = near_layer.asPoint()
                if map_crs != layer_crs:
                    xf_to_map = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
                    proj2_map = xf_to_map.transform(proj2_map)
                self._add_marker(proj2_map)

                self.pk_values.append(pk2)
                self.line_distances.append(dist2)
                self.click_count = 2

                # resultados
                dist_pk = abs(self.pk_values[1] - self.pk_values[0])                 # km
                dist_lineal = abs(self.line_distances[1] - self.line_distances[0])   # unidades de capa
                dist_lineal_km = dist_lineal / 1000.0                                # a km (si capa métrica)

                nombre_via = self.first_feat[EXPECTED_FIELD] or "Vía desconocida"

                self.callback(nombre_via,
                              self.pk_values[0],
                              self.pk_values[1],
                              dist_pk,
                              dist_lineal_km)

        except Exception as e:
            self.iface.messageBar().pushWarning("Distancia PK", f"Error al calcular: {e}")

    def _compute_pk_and_dist(self, geom_line, proj_pt_layer):
        # distancia acumulada a lo largo de la línea hasta la proyección (en unidades de capa)
        dist_click = geom_line.lineLocatePoint(proj_pt_layer)

        # vértices y longitudes acumuladas
        verts = list(geom_line.vertices())
        if len(verts) < 2:
            return 0.0, 0.0

        cum = [0.0]
        for i in range(1, len(verts)):
            seg = QgsGeometry.fromPolylineXY([QgsPointXY(verts[i-1]), QgsPointXY(verts[i])])
            cum.append(cum[-1] + seg.length())

        # interpolar M → PK (en km)
        idx = next((i for i in range(len(cum)-1)
                    if cum[i] <= dist_click <= cum[i+1]), len(cum)-2)
        
        # CONFIGURACION
        # AJUSTAR METROS O KILÓMETROS
        m1 = verts[idx].m() / 1000.0 # Dividir por 1 si la capa está calibrada en KM y por 1000 si es metros
        m2 = verts[idx+1].m() / 1000.0 # Dividir por 1 si la capa está calibrada en KM y por 1000 si es metros
        start = cum[idx]
        seg_len = cum[idx+1] - start
        t = (dist_click - start) / seg_len if seg_len > 0 else 0.0
        pk_km = m1 + t * (m2 - m1)

        return pk_km, dist_click  # pk en km, distancia lineal en unidades de la capa

    def _add_marker(self, map_pt):
        # Aro + punto verde en la PROYECCIÓN (CRS del mapa)
        ring = QgsVertexMarker(self.canvas)
        ring.setCenter(QgsPointXY(map_pt))
        ring.setColor(QColor(0, 200, 0))
        ring.setFillColor(QColor(0, 0, 0, 0))
        ring.setIconType(QgsVertexMarker.ICON_CIRCLE)
        ring.setIconSize(20)
        ring.setPenWidth(4)

        dot = QgsVertexMarker(self.canvas)
        dot.setCenter(QgsPointXY(map_pt))
        dot.setColor(QColor(0, 200, 0))
        dot.setFillColor(QColor(0, 200, 0))
        dot.setIconType(QgsVertexMarker.ICON_CIRCLE)
        dot.setIconSize(6)
        dot.setPenWidth(0)

        self.markers.extend([ring, dot])

    def deactivate(self):
        # No limpiar aquí; los puntos se borran al apagar el botón o al iniciar nueva medición
        super().deactivate()
