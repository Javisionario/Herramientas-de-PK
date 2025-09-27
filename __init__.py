from . import resources_rc
def classFactory(iface):
    from .pk_tools import PKToolsPlugin
    return PKToolsPlugin(iface)
