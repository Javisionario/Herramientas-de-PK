# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QToolButton, QMenu, QStyle
from qgis.PyQt.QtCore import Qt, QSize

from . import resources_rc  # carga los recursos Qt compilados
from .tools.identificar_pk import IdentificarPK
from .tools.localizar_pk import LocalizarPK
from .tools.distancia_pk import DistanciaPK
from .settings import show_settings_dialog


class PKToolsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.identificar = IdentificarPK(iface)
        self.localizar = LocalizarPK(iface)
        self.distancia = DistanciaPK(iface)

        self.toolbar = None
        self.actions = []  # mantiene vivas las acciones mientras el plugin esta cargado

    def initGui(self):
        """Crear la barra de herramientas propia del plugin y sus botones."""

        # Crear toolbar propia
        self.toolbar = self.iface.addToolBar("PK Tools")
        self.toolbar.setObjectName("PKTools")

        # Identificar (checkable)
        act_id = QAction(
            QIcon(":/plugins/pk_tools/icons/identificar.png"),
            "Identificar",
            self.iface.mainWindow()
        )
        act_id.setCheckable(True)
        act_id.toggled.connect(
            lambda checked, action=act_id: self._toggle_identificar(action, checked)
        )
        self.toolbar.addAction(act_id)
        self.actions.append(act_id)

        # Localizar (con menú desplegable propio, ya lo crea localizar_pk)
        act_loc = self.localizar.create_action()
        self.toolbar.addAction(act_loc)
        self.actions.append(act_loc)

        # Distancia (checkable)
        act_dist = QAction(
            QIcon(":/plugins/pk_tools/icons/distancia.png"),
            "Distancia",
            self.iface.mainWindow()
        )
        act_dist.setCheckable(True)
        act_dist.toggled.connect(
            lambda checked, action=act_dist: self._toggle_distancia(action, checked)
        )
        self.toolbar.addAction(act_dist)
        self.actions.append(act_dist)

        # Flecha desplegable de opciones
        menu_button = QToolButton(self.iface.mainWindow())
        menu_button.setPopupMode(QToolButton.InstantPopup)
        menu_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        menu_button.setAutoRaise(True)

        # Icono estandar de Qt para "toolbar overflow" / menu
        std_icon = self.iface.mainWindow().style().standardIcon(QStyle.SP_ToolBarVerticalExtensionButton)
        menu_button.setIcon(std_icon)
        menu_button.setIconSize(QSize(12, 12))
        menu_button.setFixedWidth(18)
        menu_button.setToolTip("Opciones PK Tools")

        # Menú de opciones
        options_menu = QMenu(menu_button)
        act_cfg = QAction("Configuración PK Tools", self.iface.mainWindow())
        act_cfg.triggered.connect(lambda: show_settings_dialog(self.iface))
        options_menu.addAction(act_cfg)

        menu_button.setMenu(options_menu)
        # Añadimos el botón de flecha al final de la toolbar
        self.toolbar.addWidget(menu_button)

        # Guardamos referencias para que Qt no destruya el menu ni la accion.
        self.actions.append(act_cfg)
        self.menu_button = menu_button
        self.options_menu = options_menu

    def _uncheck_action(self, action):
        action.blockSignals(True)
        action.setChecked(False)
        action.blockSignals(False)

    def _toggle_identificar(self, action, checked):
        if checked:
            if not self.identificar.run():
                self._uncheck_action(action)
        else:
            self.identificar.deactivate()

    def _toggle_distancia(self, action, checked):
        if checked:
            if not self.distancia.run():
                self._uncheck_action(action)
        else:
            self.distancia.deactivate()

    def unload(self):
        """Eliminar la barra de herramientas al desinstalar el plugin."""
        try:
            self.identificar.deactivate()
        except Exception:
            pass
        try:
            self.distancia.deactivate()
        except Exception:
            pass
        try:
            self.localizar._limpiar_marcadores()
        except Exception:
            pass

        if self.toolbar is not None:
            # Quitamos la toolbar completa, con todas sus acciones y widgets
            self.iface.mainWindow().removeToolBar(self.toolbar)
            self.toolbar = None
        self.actions = []
