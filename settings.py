# -*- coding: utf-8 -*-
"""
Módulo de configuración para PK Tools.

- Guarda y carga la configuración con QgsSettings.
- Proporciona un diálogo para seleccionar:
    * Capa de trabajo por defecto
    * Campo identificador de la vía
    * Unidades del campo M (m o km)
    * Vista previa de algunos valores M
"""

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QDialogButtonBox, QTextEdit, QSpinBox
)
from qgis.PyQt.QtCore import Qt
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsWkbTypes,
    QgsSettings
)
from .utils import (
    format_value_for_mode,
    format_raw_m,
    normalize_output_mode,
)


# Clave base en QgsSettings (queda en QGIS.ini bajo plugins/pk_tools/*)
SETTINGS_GROUP = "plugins/pk_tools"
DEFAULT_CLICK_TOLERANCE_PX = 25


class PKToolsSettings:
    """
    Pequeño wrapper para manejar la configuración del plugin.
    """
    KEY_LAYER_NAME = SETTINGS_GROUP + "/layer_name"
    KEY_LAYER_ID = SETTINGS_GROUP + "/layer_id"
    KEY_ID_FIELD = SETTINGS_GROUP + "/id_field"
    KEY_M_UNITS  = SETTINGS_GROUP + "/m_units"   # "m" o "km"
    KEY_OUTPUT_MODE = SETTINGS_GROUP + "/output_mode"  # "pk" o "raw_m"
    KEY_CLICK_TOLERANCE_PX = SETTINGS_GROUP + "/click_tolerance_px"

    def __init__(self):
        self._qsettings = QgsSettings()

    def has_config(self) -> bool:
        """
        Indica si ya hay al menos una configuración guardada.
        """
        return self._qsettings.contains(self.KEY_LAYER_NAME)

    def has_valid_config(self) -> bool:
        """
        Valida solo los datos imprescindibles guardados.

        No comprueba si la capa existe en el proyecto actual para evitar abrir
        la configuracion de forma invasiva al cambiar de proyecto.
        """
        layer_name = self._qsettings.value(self.KEY_LAYER_NAME, "", type=str).strip()
        layer_id = self._qsettings.value(self.KEY_LAYER_ID, "", type=str).strip()
        id_field = self._qsettings.value(self.KEY_ID_FIELD, "", type=str).strip()
        m_units = self._qsettings.value(self.KEY_M_UNITS, "m", type=str)
        output_mode = self._qsettings.value(self.KEY_OUTPUT_MODE, "pk", type=str)
        return (
            bool(layer_id or layer_name)
            and bool(id_field)
            and m_units in ("m", "km")
            and normalize_output_mode(output_mode) == output_mode
        )

    def load(self):
        """
        Devuelve un dict con la configuración actual (o valores por defecto).
        """
        layer_name = self._qsettings.value(self.KEY_LAYER_NAME, "", type=str)
        layer_id = self._qsettings.value(self.KEY_LAYER_ID, "", type=str)
        id_field   = self._qsettings.value(self.KEY_ID_FIELD, "ID_ROAD", type=str)
        m_units    = self._qsettings.value(self.KEY_M_UNITS, "m", type=str)
        if m_units not in ("m", "km"):
            m_units = "m"
        output_mode = normalize_output_mode(
            self._qsettings.value(self.KEY_OUTPUT_MODE, "pk", type=str)
        )
        try:
            click_tolerance_px = int(
                self._qsettings.value(
                    self.KEY_CLICK_TOLERANCE_PX,
                    DEFAULT_CLICK_TOLERANCE_PX,
                    type=int,
                )
            )
        except Exception:
            click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        if click_tolerance_px <= 0:
            click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        return {
            "layer_name": layer_name,
            "layer_id": layer_id,
            "id_field": id_field,
            "m_units": m_units,
            "output_mode": output_mode,
            "click_tolerance_px": click_tolerance_px,
        }

    def save(self, layer_name: str, id_field: str, m_units: str, output_mode: str = "pk",
             layer_id: str = "", click_tolerance_px: int = DEFAULT_CLICK_TOLERANCE_PX):
        """
        Guarda los valores indicados.
        """
        self._qsettings.setValue(self.KEY_LAYER_NAME, layer_name)
        self._qsettings.setValue(self.KEY_LAYER_ID, layer_id)
        self._qsettings.setValue(self.KEY_ID_FIELD, id_field)
        self._qsettings.setValue(self.KEY_M_UNITS, m_units)
        self._qsettings.setValue(self.KEY_OUTPUT_MODE, normalize_output_mode(output_mode))
        try:
            click_tolerance_px = int(click_tolerance_px)
        except Exception:
            click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        if click_tolerance_px <= 0:
            click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        self._qsettings.setValue(self.KEY_CLICK_TOLERANCE_PX, click_tolerance_px)


class PKToolsSettingsDialog(QDialog):
    """
    Diálogo de configuración.

    Permite al usuario elegir:
      - Capa por defecto (lineal con M)
      - Campo identificador de la vía
      - Unidades del campo M (m o km)
      - Vista previa de algunos valores M de la capa
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configuración de PK Tools")
        self.setMinimumWidth(420)

        self.settings_mgr = PKToolsSettings()
        self.current_cfg = self.settings_mgr.load()

        self._layers = self._find_candidate_layers()

        self._build_ui()
        self._populate_from_settings()

    # ---------------------------
    # Construcción de la UI
    # ---------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Capa
        row_layer = QHBoxLayout()
        row_layer.addWidget(QLabel("Capa lineal con geometría M:"))
        self.cbo_layer = QComboBox()
        for lyr in self._layers:
            self.cbo_layer.addItem(lyr.name(), lyr.id())
        self.cbo_layer.currentIndexChanged.connect(self._on_layer_changed)
        row_layer.addWidget(self.cbo_layer)
        layout.addLayout(row_layer)

        # Campo identificador
        row_field = QHBoxLayout()
        row_field.addWidget(QLabel("Campo identificador / vía:"))
        self.cbo_field = QComboBox()
        self.cbo_field.currentIndexChanged.connect(self._refresh_preview)
        row_field.addWidget(self.cbo_field)
        layout.addLayout(row_field)

        # Unidades del M
        row_units = QHBoxLayout()
        row_units.addWidget(QLabel("Unidades de la medida M:"))
        self.cbo_units = QComboBox()
        self.cbo_units.addItem("Metros", "m")
        self.cbo_units.addItem("Kilómetros", "km")
        self.cbo_units.currentIndexChanged.connect(self._refresh_preview)
        row_units.addWidget(self.cbo_units)
        layout.addLayout(row_units)

        # Formato de salida
        row_output = QHBoxLayout()
        row_output.addWidget(QLabel("Salida mostrada:"))
        self.cbo_output = QComboBox()
        self.cbo_output.addItem("Formato PK", "pk")
        self.cbo_output.addItem("Valor M bruto", "raw_m")
        self.cbo_output.currentIndexChanged.connect(self._refresh_preview)
        row_output.addWidget(self.cbo_output)
        layout.addLayout(row_output)

        # Tolerancia visual para avisar si el segundo clic cae lejos de la geometria.
        row_tolerance = QHBoxLayout()
        row_tolerance.addWidget(QLabel("Tolerancia clic-vía:"))
        self.spin_click_tolerance = QSpinBox()
        self.spin_click_tolerance.setRange(1, 500)
        self.spin_click_tolerance.setSuffix(" px")
        self.spin_click_tolerance.setValue(DEFAULT_CLICK_TOLERANCE_PX)
        row_tolerance.addWidget(self.spin_click_tolerance)
        layout.addLayout(row_tolerance)

        # Preview M
        layout.addWidget(QLabel("Vista previa de salida según la configuración:"))
        self.txt_preview = QTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setMinimumHeight(120)
        layout.addWidget(self.txt_preview)

        # Botones OK / Cancelar
        self.btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            orientation=Qt.Horizontal,
            parent=self
        )
        self.btn_box.accepted.connect(self.accept)
        self.btn_box.rejected.connect(self.reject)
        layout.addWidget(self.btn_box)

    # ---------------------------
    # Rellenar datos iniciales
    # ---------------------------
    def _populate_from_settings(self):
        """
        Intenta seleccionar en la UI los valores guardados.
        """
        cfg = self.current_cfg

        # Seleccionar capa por id, con fallback por nombre para configuraciones antiguas
        selected = False
        if self._layers and cfg.get("layer_id"):
            for i, lyr in enumerate(self._layers):
                if lyr.id() == cfg["layer_id"]:
                    self.cbo_layer.setCurrentIndex(i)
                    selected = True
                    break
        if self._layers and not selected and cfg["layer_name"]:
            for i, lyr in enumerate(self._layers):
                if lyr.name() == cfg["layer_name"]:
                    self.cbo_layer.setCurrentIndex(i)
                    break

        # Disparar actualización de campos + preview
        self._on_layer_changed(self.cbo_layer.currentIndex())

        # Seleccionar id_field
        if cfg["id_field"]:
            idx = self.cbo_field.findText(cfg["id_field"])
            if idx >= 0:
                self.cbo_field.setCurrentIndex(idx)

        # Seleccionar unidades
        units = cfg["m_units"]
        idx_units = self.cbo_units.findData(units)
        if idx_units >= 0:
            self.cbo_units.setCurrentIndex(idx_units)

        output_mode = cfg.get("output_mode", "pk")
        idx_output = self.cbo_output.findData(output_mode)
        if idx_output >= 0:
            self.cbo_output.setCurrentIndex(idx_output)

        try:
            click_tolerance_px = int(cfg.get("click_tolerance_px", DEFAULT_CLICK_TOLERANCE_PX))
        except Exception:
            click_tolerance_px = DEFAULT_CLICK_TOLERANCE_PX
        self.spin_click_tolerance.setValue(max(1, click_tolerance_px))

    # ---------------------------
    # Búsqueda de capas y preview
    # ---------------------------
    def _find_candidate_layers(self):
        """
        Devuelve una lista de capas vectoriales lineales con M.
        """
        capas = []
        for layer in QgsProject.instance().mapLayers().values():
            if (isinstance(layer, QgsVectorLayer)
                and layer.geometryType() == QgsWkbTypes.LineGeometry
                and QgsWkbTypes.hasM(layer.wkbType())):
                capas.append(layer)
        return capas

    def _on_layer_changed(self, idx):
        """
        Cuando cambia la capa:
          - Rellena combo de campos
          - Actualiza preview de M
        """
        self.cbo_field.blockSignals(True)
        self.cbo_field.clear()
        if idx < 0 or idx >= len(self._layers):
            self.cbo_field.blockSignals(False)
            self.txt_preview.clear()
            return

        layer = self._layers[idx]

        # Campos: todos, pero si existe ID_ROAD lo dejamos seleccionado
        id_road_index = -1
        for i, fld in enumerate(layer.fields()):
            self.cbo_field.addItem(fld.name())
            if fld.name().upper() == "ID_ROAD":
                id_road_index = i
        if id_road_index >= 0:
            self.cbo_field.setCurrentIndex(id_road_index)
        self.cbo_field.blockSignals(False)

        # Preview de M
        self._update_preview(layer)

    def _refresh_preview(self, *args):
        if not hasattr(self, "txt_preview"):
            return
        idx = self.cbo_layer.currentIndex()
        if idx < 0 or idx >= len(self._layers):
            self.txt_preview.clear()
            return
        self._update_preview(self._layers[idx])

    def _update_preview(self, layer: QgsVectorLayer, max_features: int = 5):
        """
        Muestra valores M originales y la salida visible con la configuracion actual.
        """
        lines = []
        count = 0
        units = self.selected_m_units()
        output_mode = self.selected_output_mode()
        id_field = self.selected_id_field()
        id_field_index = layer.fields().indexOf(id_field) if id_field else -1

        for feat in layer.getFeatures():
            geom = feat.geometry()
            if not geom:
                continue
            samples = []
            for pt in geom.vertices():
                m = pt.m()
                if m is not None:
                    original = format_raw_m(m, units)
                    output = format_value_for_mode(m, units, output_mode)
                    samples.append(f"M original: {original} -> salida: {output}")
                if len(samples) >= 3:  # unos pocos valores por feature
                    break
            if samples:
                if id_field_index >= 0:
                    label = f"Entidad {feat.id()} ({id_field}={feat[id_field]})"
                else:
                    label = f"Entidad {feat.id()}"
                lines.append(f"{label}: " + " | ".join(samples))
                count += 1
            if count >= max_features:
                break

        if not lines:
            self.txt_preview.setPlainText("No se han encontrado valores M en las geometrías.")
        else:
            self.txt_preview.setPlainText("\n".join(lines))

    # ---------------------------
    # Acceso sencillo a valores
    # ---------------------------
    def selected_layer_name(self) -> str:
        idx = self.cbo_layer.currentIndex()
        if idx < 0 or idx >= len(self._layers):
            return ""
        return self._layers[idx].name()

    def selected_layer_id(self) -> str:
        idx = self.cbo_layer.currentIndex()
        if idx < 0 or idx >= len(self._layers):
            return ""
        return self._layers[idx].id()

    def selected_id_field(self) -> str:
        return self.cbo_field.currentText().strip()

    def selected_m_units(self) -> str:
        data = self.cbo_units.currentData()
        return data if data in ("m", "km") else "m"

    def selected_output_mode(self) -> str:
        return normalize_output_mode(self.cbo_output.currentData())

    def selected_click_tolerance_px(self) -> int:
        return int(self.spin_click_tolerance.value())

    # ---------------------------
    # Aceptar diálogo
    # ---------------------------
    def accept(self):
        """
        Al aceptar, guardamos la configuración.
        """
        layer_name = self.selected_layer_name()
        layer_id = self.selected_layer_id()
        id_field   = self.selected_id_field() or "ID_ROAD"
        m_units    = self.selected_m_units()
        output_mode = self.selected_output_mode()
        click_tolerance_px = self.selected_click_tolerance_px()

        self.settings_mgr.save(layer_name, id_field, m_units, output_mode, layer_id, click_tolerance_px)
        super().accept()


def show_settings_dialog(iface):
    """
    Helper para abrir el diálogo de configuración desde el plugin.
    """
    parent = iface.mainWindow() if iface is not None else None
    dlg = PKToolsSettingsDialog(parent)
    return dlg.exec_() == QDialog.Accepted


def ensure_settings_configured(iface) -> bool:
    """
    Abre la configuracion solo cuando una herramienta se usa sin ajustes validos.
    """
    if PKToolsSettings().has_valid_config():
        return True
    if not show_settings_dialog(iface):
        return False
    return PKToolsSettings().has_valid_config()


def read_current_settings():
    """
    Helper genérico para que otras herramientas lean la config actual.

    Ejemplo de uso:
        cfg = read_current_settings()
        id_field = cfg["id_field"]
        m_units  = cfg["m_units"]  # "m" / "km"
        output_mode = cfg["output_mode"]  # "pk" / "raw_m"
    """
    return PKToolsSettings().load()
