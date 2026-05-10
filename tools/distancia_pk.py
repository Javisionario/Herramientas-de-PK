# -*- coding: utf-8 -*-
from math import hypot

from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import QAction, QPushButton, QApplication
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsMapTool, QgsVertexMarker
from qgis.core import (
    QgsPointXY,
    QgsGeometry,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsProject,
    QgsSpatialIndex,
    Qgis
)

from ..settings import DEFAULT_CLICK_TOLERANCE_PX, ensure_settings_configured, read_current_settings
from ..utils import (
    format_raw_m,
    format_value_for_mode,
    log_exception,
    output_terms,
    pk_km_to_raw_m,
    raw_m_to_pk_km,
    resolve_configured_layer,
)

# Campo por defecto histórico (fallback si no hay settings)
EXPECTED_FIELD = "ID_ROAD"


class DistanciaPK:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.tool = None
        # Para controlar solo nuestro mensaje
        self.current_msg = None

    def initGui(self):
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        icon = QIcon(icon_path)
        self.action = QAction(icon, "Distancia", self.iface.mainWindow())
        self.action.setToolTip("Medir entre dos posiciones sobre la misma geometría")
        self.action.setCheckable(True)
        self.action.toggled.connect(self.toggle_tool)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.tool:
            try:
                self.tool.reset()
            except Exception:
                pass
        if self.tool and self.canvas.mapTool() == self.tool:
            self.canvas.unsetMapTool(self.tool)
        self._close_messagebar()
        if self.action:
            self.iface.removeToolBarIcon(self.action)
            self.action = None

    def toggle_tool(self, checked):
        if checked:
            ok = self.activate_tool()
            if not ok and self.action:
                self.action.setChecked(False)
        else:
            if self.tool and self.canvas.mapTool() == self.tool:
                self.canvas.unsetMapTool(self.tool)
            if self.tool:
                self.tool.reset()
            self._close_messagebar()

    def activate_tool(self):
        """
        Activa la herramienta usando la capa/campo/unidades definidos en settings.
        """
        tool_title = "Distancia PK"
        try:
            if not ensure_settings_configured(self.iface):
                return False

            cfg = read_current_settings()
            m_units = cfg.get("m_units") or "m"
            output_mode = cfg.get("output_mode") or "pk"
            click_tolerance_px = cfg.get("click_tolerance_px", DEFAULT_CLICK_TOLERANCE_PX)
            tool_title = "Distancia M" if output_mode == "raw_m" else "Distancia PK"
            layer, id_field, layer_error = resolve_configured_layer(cfg, EXPECTED_FIELD)
            if layer_error:
                self.iface.messageBar().pushMessage(
                    tool_title,
                    layer_error,
                    level=Qgis.Warning
                )
                return False

            # Crear herramienta si no existe
            if not self.tool:
                self.tool = DistanciaTool(self.iface, self.canvas, self.show_distance_message)

            self.tool.layer = layer
            self.tool.index = QgsSpatialIndex(layer.getFeatures())
            self.tool.id_field = id_field
            self.tool.m_units = m_units
            self.tool.output_mode = output_mode
            try:
                self.tool.click_tolerance_px = max(1, int(click_tolerance_px))
            except Exception:
                self.tool.click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
            self.tool.configure_distance_area(layer.crs())
            self.tool.reset()

            self.canvas.setMapTool(self.tool)
            return True

        except Exception as exc:
            log_exception("Error al activar Distancia PK", exc)
            self.iface.messageBar().pushMessage(
                tool_title,
                "Error inesperado al seleccionar capa.",
                level=Qgis.Warning
            )
            return False

    def show_distance_message(self, nombre_via, pk1, pk2, dist_pk_km, dist_lineal_km,
                              raw_m1=None, raw_m2=None, m_units="m", output_mode="pk",
                              distance_reliable=True):
        # Cerrar mensaje anterior antes de crear uno nuevo
        self._close_messagebar()

        if raw_m1 is None:
            raw_m1 = pk_km_to_raw_m(pk1, m_units)
        if raw_m2 is None:
            raw_m2 = pk_km_to_raw_m(pk2, m_units)
        value1 = format_value_for_mode(raw_m1, m_units, output_mode)
        value2 = format_value_for_mode(raw_m2, m_units, output_mode)
        terms = output_terms(output_mode)
        if output_mode == "raw_m":
            dist_label = "Dif. M"
            dist_value = format_raw_m(abs(raw_m2 - raw_m1), m_units)
        else:
            dist_label = "Dist. PK"
            dist_value = f"{dist_pk_km:.3f} km"
        linear_text = f"{dist_lineal_km:.3f} km"
        if not distance_reliable:
            linear_text += " (aprox.)"
        texto = (
            f"{terms['identifier']}: {nombre_via} | P1: {value1} · P2: {value2} | "
            f"{dist_label}: {dist_value} · Dist. Lineal: {linear_text}"
        )

        title = "Distancia M" if output_mode == "raw_m" else "Distancia PK"
        msg = self.iface.messageBar().createMessage(title, texto)

        btn_pk = QPushButton(f"Copiar {dist_label}")
        btn_pk.clicked.connect(lambda: QApplication.clipboard().setText(dist_value))

        btn_lin = QPushButton("Copiar distancia lineal")
        btn_lin.clicked.connect(lambda: QApplication.clipboard().setText(linear_text))

        msg.layout().addWidget(btn_pk)
        msg.layout().addWidget(btn_lin)

        # Guardamos el handler para poder cerrar solo este mensaje
        self.current_msg = self.iface.messageBar().pushWidget(msg, Qgis.Info)

    def _close_messagebar(self):
        """Cierra solo el mensaje de esta herramienta, si existe."""
        if self.current_msg:
            try:
                self.iface.messageBar().popWidget(self.current_msg)
            except Exception:
                try:
                    self.current_msg.close()
                except Exception:
                    pass
            finally:
                self.current_msg = None

    def run(self):
        return self.activate_tool()

    def deactivate(self):
        if self.tool:
            try:
                self.tool.reset()
            except Exception:
                pass
            if self.canvas.mapTool() == self.tool:
                self.canvas.unsetMapTool(self.tool)
        self._close_messagebar()


class DistanciaTool(QgsMapTool):
    def __init__(self, iface, canvas, callback):
        super().__init__(canvas)
        self.iface = iface
        self.canvas = canvas
        self.callback = callback
        self.layer = None
        self.index = None
        self.id_field = EXPECTED_FIELD   # se sobreescribe desde settings
        self.m_units = "m"               # "m" (por defecto) o "km"
        self.output_mode = "pk"
        self.distance_area = None
        self.distance_reliable = True
        self.click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        self.reset()

    def configure_distance_area(self, crs):
        self.distance_area = QgsDistanceArea()
        self.distance_area.setSourceCrs(crs, QgsProject.instance().transformContext())
        ellipsoid = QgsProject.instance().ellipsoid() or "WGS84"
        self.distance_area.setEllipsoid(ellipsoid)
        self.distance_reliable = True

    def _measure_line_m(self, p0, p1):
        try:
            if self.distance_area is not None:
                return self.distance_area.measureLine(QgsPointXY(p0), QgsPointXY(p1)), True
        except Exception as exc:
            log_exception("No se pudo medir con QgsDistanceArea", exc)

        try:
            seg = QgsGeometry.fromPolylineXY([QgsPointXY(p0), QgsPointXY(p1)])
            return seg.length(), False
        except Exception as exc:
            log_exception("No se pudo medir distancia lineal", exc)
            return 0.0, False

    def _visual_distance_px(self, map_pt_a, map_pt_b):
        """Calcula distancia visual en pixeles entre dos puntos en CRS del mapa."""
        try:
            to_pixel = self.canvas.mapSettings().mapToPixel()
            a = to_pixel.transform(float(map_pt_a.x()), float(map_pt_a.y()))
            b = to_pixel.transform(float(map_pt_b.x()), float(map_pt_b.y()))
            return hypot(float(a.x()) - float(b.x()), float(a.y()) - float(b.y()))
        except Exception as exc:
            log_exception("No se pudo calcular distancia visual del clic", exc)

        try:
            map_units_per_pixel = self.canvas.mapSettings().mapUnitsPerPixel()
            if map_units_per_pixel > 0:
                return QgsPointXY(map_pt_a).distance(QgsPointXY(map_pt_b)) / map_units_per_pixel
        except Exception as exc:
            log_exception("No se pudo calcular distancia visual por mapUnitsPerPixel", exc)
        return 0.0

    def reset(self):
        if hasattr(self, 'markers'):
            for m in self.markers:
                try:
                    self.canvas.scene().removeItem(m)
                except Exception:
                    pass
        self.markers = []
        self.pk_values = []
        self.raw_m_values = []
        self.line_distances = []
        self.first_feat = None
        self.click_count = 0

    def canvasReleaseEvent(self, event):
        pt_map = self.toMapCoordinates(event.pos())
        if self.click_count >= 2:
            # Nueva medición: borra puntos (la barra se reemplaza en show_distance_message)
            self.reset()
        self._process_click(pt_map)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.canvas.unsetMapTool(self)

    def _process_click(self, click_pt_map):
        try:
            tool_title = "Distancia M" if self.output_mode == "raw_m" else "Distancia PK"
            if not self.layer or not self.index:
                self.iface.messageBar().pushMessage(
                    tool_title,
                    "No hay capa válida asignada.",
                    level=Qgis.Warning
                )
                return

            map_crs = self.canvas.mapSettings().destinationCrs()
            layer_crs = self.layer.crs()

            layer_pt = click_pt_map
            if map_crs != layer_crs:
                xf_to_layer = QgsCoordinateTransform(map_crs, layer_crs, QgsProject.instance())
                layer_pt = xf_to_layer.transform(click_pt_map)

            if self.click_count == 0:
                # Primer punto
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
                    self.iface.messageBar().pushMessage(
                        tool_title,
                        "No se encontró línea cercana.",
                        level=Qgis.Info
                    )
                    return

                self.first_feat = closest_feat
                pk1, dist1, raw_m1, reliable1 = self._compute_pk_and_dist(closest_feat.geometry(), proj_pt_layer)
                self.distance_reliable = reliable1

                proj1_map = proj_pt_layer.asPoint()
                if map_crs != layer_crs:
                    xf_to_map = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
                    proj1_map = xf_to_map.transform(proj1_map)
                self._add_marker(proj1_map)

                self.pk_values.append(pk1)
                self.raw_m_values.append(raw_m1)
                self.line_distances.append(dist1)
                self.click_count = 1

            else:
                # Segundo punto sobre la MISMA geometria seleccionada con el primer clic.
                geom = self.first_feat.geometry()
                near_layer = geom.nearestPoint(QgsGeometry.fromPointXY(QgsPointXY(layer_pt)))
                proj2_map = near_layer.asPoint()
                if map_crs != layer_crs:
                    xf_to_map = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
                    proj2_map = xf_to_map.transform(proj2_map)

                offset_px = self._visual_distance_px(click_pt_map, proj2_map)
                far_second_click = offset_px > self.click_tolerance_px
                pk2, dist2, raw_m2, reliable2 = self._compute_pk_and_dist(geom, near_layer)

                self._add_marker(proj2_map)

                self.pk_values.append(pk2)
                self.raw_m_values.append(raw_m2)
                self.line_distances.append(dist2)
                self.click_count = 2

                dist_pk = abs(self.pk_values[1] - self.pk_values[0])               # km
                dist_lineal = abs(self.line_distances[1] - self.line_distances[0]) # metros
                dist_lineal_km = dist_lineal / 1000.0

                # Nombre del identificador usando el campo configurado.
                terms = output_terms(self.output_mode)
                unknown_label = f"{terms['identifier']} desconocido"
                try:
                    val = self.first_feat[self.id_field]
                    nombre_via = val if val not in (None, "") else unknown_label
                except Exception:
                    nombre_via = unknown_label

                self.callback(
                    nombre_via,
                    self.pk_values[0],
                    self.pk_values[1],
                    dist_pk,
                    dist_lineal_km,
                    self.raw_m_values[0],
                    self.raw_m_values[1],
                    self.m_units,
                    self.output_mode,
                    self.distance_reliable and reliable2
                )
                if far_second_click:
                    self.iface.messageBar().pushMessage(
                        tool_title,
                        "El segundo punto está lejos de la geometría seleccionada. Revisa la medición.",
                        level=Qgis.Warning
                    )

        except Exception as e:
            log_exception("Error al calcular Distancia PK", e)
            self.iface.messageBar().pushMessage(
                "Distancia",
                "Error inesperado al calcular la distancia.",
                level=Qgis.Warning
            )

    def _compute_pk_and_dist(self, geom_line, proj_pt_layer):
        """
        Devuelve:
          - pk_km: PK interno en km, interpolado desde los valores M originales.
          - dist_click_m: distancia acumulada sobre la misma feature, en metros.

        Deliberadamente no reconstruye rutas ni salta entre features partidas.
        """
        dist_click = geom_line.lineLocatePoint(proj_pt_layer)
        verts = list(geom_line.vertices())
        if len(verts) < 2:
            return 0.0, 0.0, 0.0, False

        cum = [0.0]
        cum_measured = [0.0]
        reliable = True
        for i in range(1, len(verts)):
            seg = QgsGeometry.fromPolylineXY([QgsPointXY(verts[i-1]), QgsPointXY(verts[i])])
            cum.append(cum[-1] + seg.length())
            measured, segment_reliable = self._measure_line_m(verts[i-1], verts[i])
            cum_measured.append(cum_measured[-1] + measured)
            reliable = reliable and segment_reliable

        idx = next(
            (i for i in range(len(cum)-1) if cum[i] <= dist_click <= cum[i+1]),
            len(cum)-2
        )

        start = cum[idx]
        seg_len = cum[idx+1] - start
        t = (dist_click - start) / seg_len if seg_len > 0 else 0.0

        m1_raw = verts[idx].m()
        m2_raw = verts[idx+1].m()
        if m1_raw is None or m2_raw is None:
            raise ValueError("El tramo localizado no tiene medidas M válidas.")

        m_raw = m1_raw + t * (m2_raw - m1_raw)
        pk_km = raw_m_to_pk_km(m_raw, self.m_units)
        dist_click_m = cum_measured[idx] + t * (cum_measured[idx+1] - cum_measured[idx])
        return pk_km, dist_click_m, m_raw, reliable

    def _add_marker(self, map_pt):
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
        super().deactivate()
