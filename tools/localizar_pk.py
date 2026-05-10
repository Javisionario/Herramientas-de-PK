# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QCompleter, QPushButton, QMenu, QApplication,
    QListWidget, QListWidgetItem, QDialogButtonBox
)
from qgis.PyQt.QtCore import Qt, QMimeData, QVariant
from qgis.gui import QgsVertexMarker
from qgis.core import (
    QgsPointXY, QgsCoordinateTransform, QgsProject, QgsCoordinateReferenceSystem,
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry,
    Qgis
)
from ..settings import ensure_settings_configured, read_current_settings
from ..utils import (
    PKParseError,
    coverage_status,
    features_by_field_value,
    format_pk_export_text,
    format_value_for_mode,
    interval_tolerance_to_raw,
    line_part_vertices,
    log_exception,
    nearest_interval_endpoint,
    output_terms,
    parse_pk_text,
    parse_raw_m_text,
    pk_numeric_km,
    pk_km_to_raw_m,
    raw_m_export_value,
    raw_m_to_pk_km,
    resolve_configured_layer,
)

# Campo por defecto histórico (fallback)
EXPECTED_FIELD = "ID_ROAD"


class RoadLineEdit(QLineEdit):
    """Campo de vía que abre el listado completo con doble clic."""

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        completer = self.completer()
        if completer is not None:
            completer.setCompletionPrefix("")
            completer.complete()


class LocalizarPK:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.history_menu = None
        self.history = []   # [(identificador, pk_km, raw_m, map_pt)]
        self.markers = []   # [QgsVertexMarker, QgsVertexMarker]
        self.layer = None
        self.id_field = EXPECTED_FIELD
        self.m_units = "m"   # "m" (por defecto) o "km"
        self.output_mode = "pk"
        self.current_msg = None
        self.last_identifier = ""

    def create_action(self):
        icon = QIcon(":/plugins/pk_tools/icons/localizar.png")
        self.action = QAction(icon, "Localizar", self.iface.mainWindow())
        self.action.setToolTip("Localizar una medida en la capa configurada")
        self.history_menu = QMenu(self.iface.mainWindow())
        self.history_menu.setTitle("Historial")
        self.action.setMenu(self.history_menu)
        self.action.triggered.connect(self.run)
        self._update_history_menu()
        return self.action

    def initGui(self):
        # Solo se usaría si esta clase gestionara su propio botón,
        # pero pk_tools.py ya crea la acción con create_action().
        icon = QIcon(":/plugins/pk_tools/icons/localizar.png")
        self.action = QAction(icon, "Localizar", self.iface.mainWindow())
        self.action.setToolTip("Localizar una medida en la capa configurada")
        self.history_menu = QMenu(self.iface.mainWindow())
        self.history_menu.setTitle("Historial")
        self.action.setMenu(self.history_menu)
        self.action.triggered.connect(self.open_dialog)
        self.iface.addToolBarIcon(self.action)
        self._update_history_menu()

    def unload(self):
        if self.action:
            self.iface.removeToolBarIcon(self.action)

    # ---------------------------------------------------
    # Apertura del diálogo principal
    # ---------------------------------------------------
    def open_dialog(self):
        """
        Abre el diálogo de localización usando la capa/campo/unidades definidos en settings.
        """
        try:
            if not ensure_settings_configured(self.iface):
                return

            cfg = read_current_settings()
            m_units = cfg.get("m_units") or "m"
            output_mode = cfg.get("output_mode") or "pk"
            tool_title = output_terms(output_mode)["tool_locate"]
            layer, id_field, layer_error = resolve_configured_layer(cfg, EXPECTED_FIELD)
            if layer_error:
                self.iface.messageBar().pushMessage(
                    tool_title,
                    layer_error,
                    level=Qgis.Warning
                )
                return

            # Guardar en la instancia
            self.layer = layer
            self.id_field = id_field
            self.m_units = m_units
            self.output_mode = output_mode

        except Exception as exc:
            log_exception("Error al preparar Localizar", exc)
            self.iface.messageBar().pushMessage(
                "Localizar",
                "Error inesperado al preparar la capa.",
                level=Qgis.Warning
            )
            return

        # A partir de aquí, self.layer está validada
        field = self.id_field
        field_index = self.layer.fields().indexOf(field)
        road_values = {}
        road_names = sorted(
            {
                str(value).strip()
                for value in self.layer.uniqueValues(field_index)
                if value not in (None, "") and str(value).strip()
            },
            key=str.casefold
        )
        for value in self.layer.uniqueValues(field_index):
            text = str(value).strip()
            if text:
                road_values.setdefault(text, value)
        terms = output_terms(self.output_mode)

        # ----- Construcción del diálogo -----
        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle(terms["tool_locate"])
        vbox = QVBoxLayout()

        # Identificador
        h1 = QHBoxLayout()
        h1.addWidget(QLabel(f"{terms['identifier']}:"))
        self.le_road = RoadLineEdit(self.last_identifier)
        completer = QCompleter(road_names)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        self.le_road.setCompleter(completer)
        h1.addWidget(self.le_road)
        vbox.addLayout(h1)

        # Medida
        h2 = QHBoxLayout()
        h2.addWidget(QLabel(f"{terms['measure']}:"))
        self.le_pk = QLineEdit()
        placeholder = "15+000 | 15.500 | 15" if self.output_mode == "pk" else "Ej.: 15500"
        self.le_pk.setPlaceholderText(placeholder)
        self.le_pk.returnPressed.connect(dlg.accept)
        h2.addWidget(self.le_pk)
        vbox.addLayout(h2)

        # Botones
        hbtn = QHBoxLayout()
        hbtn.addStretch()
        btn_ok = QPushButton("Localizar")
        btn_cancel = QPushButton("Cancelar")
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        hbtn.addWidget(btn_ok)
        hbtn.addWidget(btn_cancel)
        vbox.addLayout(hbtn)

        dlg.setLayout(vbox)
        if dlg.exec_() != QDialog.Accepted:
            return

        via_text = self.le_road.text().strip()
        if not via_text:
            self.iface.messageBar().pushWarning(terms["tool_locate"], f"Introduce {terms['identifier_prompt']}.")
            return
        via = self._resolve_road_name(via_text, road_names)
        if via is None:
            self.iface.messageBar().pushInfo(
                terms["tool_locate"],
                "Hay varios valores similares. Selecciona el valor exacto."
            )
            return
        via_value = road_values.get(via, via)
        self.last_identifier = via

        try:
            if self.output_mode == "raw_m":
                pk_total_km = raw_m_to_pk_km(parse_raw_m_text(self.le_pk.text()), self.m_units)
            else:
                pk_total_km = parse_pk_text(self.le_pk.text())
        except PKParseError as err:
            self.iface.messageBar().pushWarning(terms["tool_locate"], str(err))
            return

        self.locate(via, pk_total_km, via_value)

    def _resolve_road_name(self, text, road_names):
        """Respeta el valor real y solo corrige mayúsculas si no hay ambigüedad."""
        typed = str(text).strip()
        if typed in road_names:
            return typed

        matches = [name for name in road_names if name.casefold() == typed.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
        return typed

    def _interpolate_segment_by_m(self, p0, p1, target_m, eps):
        m0, m1 = p0.m(), p1.m()
        if m0 is None or m1 is None:
            return None
        if not ((m0 - eps <= target_m <= m1 + eps) or (m1 - eps <= target_m <= m0 + eps)):
            return None
        if abs(m1 - m0) < eps:
            return QgsPointXY(p0.x(), p0.y()), 0.0

        t = (target_m - m0) / (m1 - m0)
        t = max(0.0, min(1.0, t))
        x = p0.x() + t * (p1.x() - p0.x())
        y = p0.y() + t * (p1.y() - p0.y())
        return QgsPointXY(x, y), t

    def _close_messagebar(self):
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

    def _push_info_message(self, msg):
        self._close_messagebar()
        self.current_msg = self.iface.messageBar().pushWidget(msg, level=Qgis.Info)

    def _show_nearest_available_message(self, via, target_m, nearest_m, reason, via_value=None):
        searched = format_value_for_mode(
            target_m,
            self.m_units,
            self.output_mode,
            for_button=False,
        )
        nearest = format_value_for_mode(
            nearest_m,
            self.m_units,
            self.output_mode,
            for_button=True,
        )
        message_text = f"{searched} {reason}. Más próximo: {nearest}"

        msg = self.iface.messageBar().createMessage(output_terms(self.output_mode)["tool_locate"], message_text)
        btn_nearest = QPushButton(f"Ajustar: {nearest}")
        nearest_pk_km = raw_m_to_pk_km(nearest_m, self.m_units)
        btn_nearest.clicked.connect(lambda: self.locate(via, nearest_pk_km, via_value))
        msg.layout().addWidget(btn_nearest)
        self._push_info_message(msg)

    # ---------------------------------------------------
    # Lógica de localización
    # ---------------------------------------------------
    def locate(self, via, pk_km, via_value=None):
        field = self.id_field or EXPECTED_FIELD

        target_m = pk_km_to_raw_m(pk_km, self.m_units)
        EPS = 1e-6

        # Reunir features del identificador con filtro de proveedor y fallback seguro.
        if not self.layer:
            self.iface.messageBar().pushWarning(output_terms(self.output_mode)["tool_locate"], "No hay capa seleccionada.")
            return

        via_value = via if via_value is None else via_value
        feats = features_by_field_value(self.layer, field, via_value)
        if not feats:
            terms = output_terms(self.output_mode)
            self.iface.messageBar().pushInfo(
                terms["tool_locate"],
                f"No se encontró {terms['identifier_with_article']} '{via}'."
            )
            return

        # Buscar segmentos reales que contienen la medida, sin unir partes multipart.
        coverage_intervals = []
        candidates = []

        for f in feats:
            geom = f.geometry()
            if not geom:
                continue

            for part_idx, verts in enumerate(line_part_vertices(geom)):
                for seg_idx in range(len(verts) - 1):
                    p0, p1 = verts[seg_idx], verts[seg_idx + 1]
                    m0, m1 = p0.m(), p1.m()
                    if m0 is not None and m1 is not None:
                        coverage_intervals.append((m0, m1))

                    result = self._interpolate_segment_by_m(p0, p1, target_m, EPS)
                    if result is None:
                        continue

                    pt, t = result
                    m_span = abs(p1.m() - p0.m())
                    endpoint_penalty = 1 if t <= EPS or t >= 1.0 - EPS else 0
                    candidates.append((
                        endpoint_penalty,
                        m_span,
                        f.id(),
                        part_idx,
                        seg_idx,
                        pt,
                    ))

        map_pt = None
        if candidates:
            candidates.sort(key=lambda item: item[:5])
            map_pt = candidates[0][5]

        if map_pt is None:
            tolerance = interval_tolerance_to_raw(10.0, self.m_units)
            status = coverage_status(target_m, coverage_intervals, tolerance)
            nearest_m = status.get("nearest_m")
            if nearest_m is None:
                nearest_m = nearest_interval_endpoint(target_m, coverage_intervals)

            if nearest_m is not None and status.get("status") in ("gap", "below", "above", "covered"):
                reason = "sin cobertura" if status.get("status") in ("gap", "covered") else "fuera de rango"
                self._show_nearest_available_message(via, target_m, nearest_m, reason, via_value)
            else:
                terms = output_terms(self.output_mode)
                self.iface.messageBar().pushInfo(
                    terms["tool_locate"],
                    f"No hay medidas M válidas en {terms['identifier_with_article']} '{via}'."
                )
            return

        # 4) Transformar al CRS del mapa
        map_crs = self.canvas.mapSettings().destinationCrs()
        layer_crs = self.layer.crs()
        if layer_crs != map_crs:
            xf = QgsCoordinateTransform(layer_crs, map_crs, QgsProject.instance())
            map_pt = xf.transform(map_pt)

        # 5) Dibujar marcador y UI
        self._limpiar_marcadores()
        self._add_marker(map_pt, QColor(0, 0, 255))

        crs_wgs84 = QgsCoordinateTransform(
            map_crs,
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )
        pt_wgs = crs_wgs84.transform(map_pt)
        lat, lon = pt_wgs.y(), pt_wgs.x()
        url_sv = (
            "https://www.google.com/maps/@?api=1&map_action=pano"
            f"&viewpoint={lat:.6f},{lon:.6f}&heading=0&pitch=10&fov=250"
        )

        value_text = format_value_for_mode(target_m, self.m_units, self.output_mode)
        terms = output_terms(self.output_mode)
        message_text = (
            f"{terms['identifier']}: {via} – {value_text} | "
            f"<a href='{url_sv}'>Ver en Street View ({lat:.6f},{lon:.6f})</a>"
        )
        msg = self.iface.messageBar().createMessage(terms["tool_locate"], message_text)

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

        self._push_info_message(msg)

        # 6) Historial
        self.history.insert(0, (via, pk_km, target_m, map_pt))
        self._update_history_menu()

    # ---------------------------------------------------
    # Utilidades de zoom y marcadores
    # ---------------------------------------------------
    def _zoom_al_punto(self, punto):
        self.canvas.setCenter(punto)
        self.canvas.zoomScale(25000)
        self.canvas.refresh()

    def _limpiar_marcadores(self):
        for m in self.markers:
            try:
                self.canvas.scene().removeItem(m)
            except Exception:
                pass
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

    # ---------------------------------------------------
    # Historial y exportación
    # ---------------------------------------------------
    def _history_parts(self, item):
        if len(item) == 4:
            return item
        via, pk_km, map_pt = item
        return via, pk_km, pk_km_to_raw_m(pk_km, self.m_units), map_pt

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
        for item in self.history:
            via, pk_km, raw_m, map_pt = self._history_parts(item)
            texto = f"{via} – {format_value_for_mode(raw_m, self.m_units, self.output_mode)}"
            act = QAction(texto, self.iface.mainWindow())
            act.triggered.connect(
                lambda checked, v=via, p=pk_km, r=raw_m, mp=map_pt: self._from_history(v, p, r, mp)
            )
            self.history_menu.addAction(act)

    def _from_history(self, via, pk_km, raw_m, map_pt):
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
        url_sv = (
            "https://www.google.com/maps/@?api=1&map_action=pano"
            f"&viewpoint={lat:.6f},{lon:.6f}&heading=0&pitch=10&fov=250"
        )

        value_text = format_value_for_mode(raw_m, self.m_units, self.output_mode)
        terms = output_terms(self.output_mode)
        message_text = (
            f"{terms['identifier']}: {via} – {value_text} | "
            f"<a href='{url_sv}'>Ver en Street View ({lat:.6f},{lon:.6f})</a>"
        )
        msg = self.iface.messageBar().createMessage(terms["tool_locate"], message_text)

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

        self._push_info_message(msg)

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
        for i, item in enumerate(self.history):
            via, pk_km, raw_m, _ = self._history_parts(item)
            value_text = format_value_for_mode(raw_m, self.m_units, self.output_mode)
            texto = f"{via} – {value_text}"
            item = QListWidgetItem(texto)
            item.setSelected(False)
            item.setData(1000, i)  # índice en self.history
            list_widget.addItem(item)

        vbox.addWidget(list_widget)

        # Botones: Marcar/Desmarcar todos
        hbtn = QHBoxLayout()
        btn_sel_all = QPushButton("Marcar todos")
        btn_unsel_all = QPushButton("Desmarcar todos")
        btn_sel_all.clicked.connect(
            lambda: [list_widget.item(i).setSelected(True) for i in range(list_widget.count())]
        )
        btn_unsel_all.clicked.connect(
            lambda: [list_widget.item(i).setSelected(False) for i in range(list_widget.count())]
        )
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

        # Crear capa temporal (EPSG:4326). En modo PK se exporta PK/PK_NUM;
        # en modo M bruto se evita cualquier campo PK.
        terms = output_terms(self.output_mode)
        vl = QgsVectorLayer(f"Point?crs=EPSG:4326", terms["located_layer"], "memory")
        pr = vl.dataProvider()
        fields = [QgsField(terms["id_field"], QVariant.String)]
        if self.output_mode == "raw_m":
            fields.append(QgsField(terms["value_field"], QVariant.Double))
        else:
            fields.append(QgsField(terms["value_field"], QVariant.String))
            fields.append(QgsField(terms["pk_number_field"], QVariant.Double, "double", 20, 3))
        pr.addAttributes(fields)
        vl.updateFields()

        # Transformación a WGS84 desde CRS del mapa
        xf = QgsCoordinateTransform(
            self.canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance()
        )

        for idx in seleccionados:
            via, pk_km, raw_m, map_pt = self._history_parts(self.history[idx])
            pt = xf.transform(map_pt)
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt)))
            if self.output_mode == "raw_m":
                feat.setAttributes([via, raw_m_export_value(raw_m)])
            else:
                feat.setAttributes([
                    via,
                    format_pk_export_text(raw_m, self.m_units),
                    pk_numeric_km(raw_m, self.m_units),
                ])
            pr.addFeature(feat)

        vl.updateExtents()
        QgsProject.instance().addMapLayer(vl)

    def run(self):
        """Método de entrada para integrarlo en el plugin unificado."""
        self.open_dialog()
