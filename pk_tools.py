# -*- coding: utf-8 -*-
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from . import resources_rc
from .tools.identificar_pk import IdentificarPK
from .tools.localizar_pk import LocalizarPK
from .tools.distancia_pk import DistanciaPK


class PKToolsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.identificar = IdentificarPK(iface)
        self.localizar = LocalizarPK(iface)
        self.distancia = DistanciaPK(iface)

        self.actions = []  # guardamos las acciones para poder limpiarlas en unload

    def initGui(self):
        """Crear los botones de la barra de herramientas."""

        # Identificar PK (checkable)
        act_id = QAction(
            QIcon(":/plugins/pk_tools/icons/identificar.png"),
            "Identificar PK",
            self.iface.mainWindow()
        )
        act_id.setCheckable(True)
        act_id.toggled.connect(
            lambda checked: self.identificar.run() if checked else self.identificar.deactivate()
        )
        self.iface.addToolBarIcon(act_id)
        self.actions.append(act_id)

        # Localizar PK (no checkable)
        # act_loc = QAction(
        #     QIcon(":/plugins/pk_tools/icons/localizar.png"),
        #     "Localizar PK",
        #     self.iface.mainWindow()
        # )
        # act_loc.triggered.connect(self.localizar.run)
        # self.iface.addToolBarIcon(act_loc)
        # self.actions.append(act_loc)

        # Localizar PK (con menú desplegable)
        act_loc = self.localizar.create_action()
        self.iface.addToolBarIcon(act_loc)
        self.actions.append(act_loc)

        # Distancia PK (checkable)
        act_dist = QAction(
            QIcon(":/plugins/pk_tools/icons/distancia.png"),
            "Distancia PK",
            self.iface.mainWindow()
        )
        act_dist.setCheckable(True)
        act_dist.toggled.connect(
            lambda checked: self.distancia.run() if checked else self.distancia.deactivate()
        )
        self.iface.addToolBarIcon(act_dist)
        self.actions.append(act_dist)

    def unload(self):
        """Eliminar los botones de la barra de herramientas al desinstalar el plugin."""
        for act in self.actions:
            self.iface.removeToolBarIcon(act)
        self.actions = []
