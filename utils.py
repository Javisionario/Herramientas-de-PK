# -*- coding: utf-8 -*-
"""
Utilidades compartidas de PK Tools.

Convenciones internas:
  - Los valores M brutos conservan las unidades configuradas por el usuario.
  - Los valores PK internos se expresan en kilometros.
  - Los textos visibles se generan al final, cerca de cada interfaz.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VALID_M_UNITS = ("m", "km")
VALID_OUTPUT_MODES = ("pk", "raw_m")
LOG_TAG = "PK_tools"


class PKParseError(ValueError):
    """Error de validacion de una entrada de PK o medida."""


def normalize_m_units(m_units):
    """Devuelve una unidad M soportada."""
    return m_units if m_units in VALID_M_UNITS else "m"


def normalize_output_mode(output_mode):
    """Devuelve un modo de salida soportado."""
    return output_mode if output_mode in VALID_OUTPUT_MODES else "pk"


def output_terms(output_mode):
    """Centraliza terminos visibles y campos de exportacion segun el modo."""
    if normalize_output_mode(output_mode) == "raw_m":
        return {
            "identifier": "Identificador",
            "identifier_lower": "identificador",
            "identifier_prompt": "un identificador",
            "identifier_with_article": "el identificador",
            "measure": "Medida",
            "tool_locate": "Localizar medida",
            "located_layer": "Localización de medidas M",
            "identified_layer": "Identificación de medidas M",
            "id_field": "IDENTIFICADOR",
            "value_field": "M_RAW",
            "pk_number_field": "PK_NUM",
        }
    return {
        "identifier": "Vía",
        "identifier_lower": "vía",
        "identifier_prompt": "una vía",
        "identifier_with_article": "la vía",
        "measure": "PK",
        "tool_locate": "Localizar PK",
        "located_layer": "Localización de PKs",
        "identified_layer": "Identificación de PKs",
        "id_field": "VIA",
        "value_field": "PK",
        "pk_number_field": "PK_NUM",
    }


def log_exception(context, exc=None):
    """Registra detalles tecnicos en QGIS sin mostrarlos en banners."""
    message = str(context)
    if exc is not None:
        message = f"{message}: {exc}"
    try:
        from qgis.core import Qgis, QgsMessageLog
        QgsMessageLog.logMessage(message, LOG_TAG, Qgis.Warning)
    except Exception:
        pass


def _decimal_from_value(value, field_name="valor"):
    try:
        dec = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        raise PKParseError(f"El {field_name} no es un número válido.")
    if not dec.is_finite():
        raise PKParseError(f"El {field_name} no es un número válido.")
    return dec


def round_half_up_to_int(value):
    """Redondea al entero mas cercano, con los medios hacia arriba."""
    dec = value if isinstance(value, Decimal) else _decimal_from_value(value)
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def raw_m_to_pk_km(raw_m, m_units="m"):
    """Convierte un valor M bruto al PK interno en kilometros."""
    units = normalize_m_units(m_units)
    value = float(raw_m)
    return value / 1000.0 if units == "m" else value


def pk_km_to_raw_m(pk_km, m_units="m"):
    """Convierte un PK interno en kilometros a unidades M brutas."""
    units = normalize_m_units(m_units)
    value = float(pk_km)
    return value * 1000.0 if units == "m" else value


def format_pk(value, units="km", km_width=0):
    """
    Formatea un PK como km+mmm.

    Primero convierte a metros enteros y despues usa divmod. Asi se evitan
    salidas como 9+1000 cuando el redondeo cruza de kilometro.
    """
    source_units = normalize_m_units(units)
    dec = _decimal_from_value(value)
    meters = dec if source_units == "m" else dec * Decimal("1000")
    total_m = round_half_up_to_int(meters)

    sign = "-" if total_m < 0 else ""
    km, meter = divmod(abs(total_m), 1000)
    if km_width:
        km_text = f"{km:0{km_width}d}"
    else:
        km_text = str(km)
    return f"{sign}{km_text}+{meter:03d}"


def parse_pk_text(text):
    """
    Interpreta un PK introducido por el usuario y devuelve kilometros.

    Ejemplos aceptados:
      10       -> 10.000 km
      150.500  -> 150.500 km
      150,500  -> 150.500 km
      0+010    -> 0.010 km
      150+500  -> 150.500 km
    """
    raw = str(text).strip()
    if not raw:
        raise PKParseError("Introduce un PK.")

    normalized = raw.replace(",", ".")
    if normalized.count("+") > 1:
        raise PKParseError("El PK solo puede contener un signo '+'.")

    if "+" in normalized:
        km_text, meters_text = [part.strip() for part in normalized.split("+", 1)]
        if not km_text:
            km_text = "0"
        if not meters_text:
            meters_text = "0"
        km = _decimal_from_value(km_text, "kilometro")
        meters = _decimal_from_value(meters_text, "metro")
        if meters < 0:
            raise PKParseError("Los metros del PK no pueden ser negativos.")
        return float(km + meters / Decimal("1000"))

    return float(_decimal_from_value(normalized, "PK"))


def parse_raw_m_text(text):
    """Interpreta una medida M bruta introducida por el usuario."""
    raw = str(text).strip()
    if not raw:
        raise PKParseError("Introduce una medida.")
    return float(_decimal_from_value(raw, "medida"))


def format_number_compact(value, decimals=3):
    """Formatea un numero sin ceros finales innecesarios."""
    number = float(value)
    if abs(number - round(number)) < 10 ** -decimals:
        return str(int(round(number)))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def format_raw_m(raw_m, m_units="m", decimals=3, include_unit=True):
    """Formatea un valor M bruto con sus unidades configuradas."""
    units = normalize_m_units(m_units)
    text = format_number_compact(raw_m, decimals)
    return f"{text} {units}" if include_unit else text


def format_value_for_mode(raw_m, m_units="m", output_mode="pk", for_button=False):
    """Genera el texto visible de un valor M segun el modo de salida."""
    output_mode = normalize_output_mode(output_mode)
    if output_mode == "raw_m":
        if for_button:
            return format_raw_m(raw_m, m_units)
        return f"M {format_raw_m(raw_m, m_units, include_unit=False)}"

    return f"PK {format_pk(raw_m_to_pk_km(raw_m, m_units))}"


def format_pk_export_text(raw_m, m_units="m"):
    """Formatea PK para exportacion, sin prefijo: 150+500."""
    return format_pk(raw_m_to_pk_km(raw_m, m_units), units="km")


def pk_numeric_km(raw_m, m_units="m"):
    """Devuelve PK_NUM en kilometros, redondeado a 3 decimales."""
    dec = Decimal(str(raw_m_to_pk_km(raw_m, m_units)))
    return float(dec.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def raw_m_export_value(raw_m):
    """Devuelve M_RAW como valor numerico para exportacion."""
    return float(raw_m)


def interval_tolerance_to_raw(tolerance_m=10.0, m_units="m"):
    """Convierte una tolerancia en metros a las unidades M configuradas."""
    return float(tolerance_m) if normalize_m_units(m_units) == "m" else float(tolerance_m) / 1000.0


def merge_m_intervals(intervals, tolerance=0.0):
    """Ordena y fusiona intervalos reales de cobertura M."""
    normalized = [
        (min(float(a), float(b)), max(float(a), float(b)))
        for a, b in intervals
        if a is not None and b is not None
    ]
    if not normalized:
        return []

    normalized.sort(key=lambda item: (item[0], item[1]))
    merged = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + tolerance:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def coverage_status(target_m, intervals, tolerance=0.0):
    """
    Clasifica una medida frente a los intervalos reales de cobertura M.

    No usa solo min/max global: trabaja con tramos reales fusionados para
    detectar huecos internos y extremos fuera de rango.
    """
    target = float(target_m)
    merged = merge_m_intervals(intervals, tolerance)
    if not merged:
        return {"status": "empty", "nearest_m": None, "intervals": []}

    first_start = merged[0][0]
    last_end = merged[-1][1]
    if target < first_start:
        return {"status": "below", "nearest_m": first_start, "intervals": merged}
    if target > last_end:
        return {"status": "above", "nearest_m": last_end, "intervals": merged}

    for idx, (start, end) in enumerate(merged):
        if start <= target <= end:
            return {"status": "covered", "nearest_m": None, "intervals": merged}
        if idx < len(merged) - 1:
            next_start = merged[idx + 1][0]
            if end < target < next_start:
                nearest = end if abs(target - end) <= abs(next_start - target) else next_start
                return {
                    "status": "gap",
                    "nearest_m": nearest,
                    "previous_end": end,
                    "next_start": next_start,
                    "intervals": merged,
                }

    return {"status": "empty", "nearest_m": None, "intervals": merged}


def nearest_interval_endpoint(target_m, intervals):
    """Devuelve el extremo de intervalo mas cercano a la medida buscada."""
    endpoints = []
    for start, end in intervals:
        endpoints.extend([float(start), float(end)])
    if not endpoints:
        return None
    target = float(target_m)
    return min(endpoints, key=lambda value: (abs(value - target), value))


def line_part_vertices(geom):
    """Devuelve vertices por parte, sin unir artificialmente partes multipart."""
    try:
        if geom is None or geom.isEmpty():
            return
    except Exception:
        return

    try:
        parts = list(geom.constParts())
    except Exception:
        parts = []

    if parts:
        for part in parts:
            verts = list(part.vertices())
            if len(verts) >= 2:
                yield verts
        return

    verts = list(geom.vertices())
    if len(verts) >= 2:
        yield verts


def line_geometry_from_vertices(verts):
    """Crea una geometria XY auxiliar para proyectar sobre una unica parte."""
    from qgis.core import QgsGeometry, QgsPointXY

    return QgsGeometry.fromPolylineXY([QgsPointXY(point) for point in verts])


def nearest_line_part_to_point(geom, point):
    """
    Elige la parte lineal mas cercana a un punto.

    Devuelve (vertices_de_la_parte, geometria_xy_de_la_parte,
    punto_proyectado, distancia). Las herramientas conservan los vertices
    originales para interpolar M; la geometria XY solo se usa para proyectar.
    """
    from qgis.core import QgsGeometry, QgsPointXY

    point_xy = QgsPointXY(point)
    point_geom = QgsGeometry.fromPointXY(point_xy)
    best = None

    for verts in line_part_vertices(geom):
        part_geom = line_geometry_from_vertices(verts)
        near = part_geom.nearestPoint(point_geom)
        dist = point_xy.distance(near.asPoint())
        if best is None or dist < best[3]:
            best = (verts, part_geom, near, dist)

    return best


def find_layer_by_config(cfg):
    """Busca la capa por id y usa el nombre como fallback de configuraciones antiguas."""
    from qgis.core import QgsProject, QgsVectorLayer

    layer_id = (cfg.get("layer_id") or "").strip()
    layer_name = (cfg.get("layer_name") or "").strip()

    if layer_id:
        layer = QgsProject.instance().mapLayer(layer_id)
        if isinstance(layer, QgsVectorLayer):
            return layer

    if layer_name:
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.name() == layer_name:
                return layer
    return None


def resolve_configured_layer(cfg, default_id_field="ID_ROAD"):
    """Devuelve (capa, campo_id, error) para la capa lineal M configurada."""
    from qgis.core import QgsWkbTypes

    layer_name = (cfg.get("layer_name") or "").strip()
    id_field = (cfg.get("id_field") or default_id_field).strip() or default_id_field

    if not (cfg.get("layer_id") or layer_name):
        return None, id_field, "No hay capa configurada."

    layer = find_layer_by_config(cfg)
    if layer is None:
        return None, id_field, "No se ha encontrado la capa configurada."

    if layer.geometryType() != QgsWkbTypes.LineGeometry:
        return None, id_field, "La capa configurada no es lineal."

    if not QgsWkbTypes.hasM(layer.wkbType()):
        return None, id_field, "La capa seleccionada no contiene geometría M."

    if layer.fields().indexOf(id_field) == -1:
        return None, id_field, f"La capa configurada no tiene el campo '{id_field}'."

    return layer, id_field, None


def _field_value_expression(field_name, value):
    field_ref = '"' + str(field_name).replace('"', '""') + '"'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{field_ref} = {value}"
    value_ref = "'" + str(value).replace("'", "''") + "'"
    return f"{field_ref} = {value_ref}"


def features_by_field_value(layer, field_name, value):
    """
    Obtiene features con el valor exacto del identificador.

    Primero intenta filtro de proveedor para capas grandes. Si falla por tipo
    de campo, caracteres especiales o proveedor limitado, registra el detalle
    y cae a un recorrido exacto en memoria sin normalizar mayusculas/minusculas.
    """
    field_index = layer.fields().indexOf(field_name)
    if field_index < 0:
        return []

    expression = _field_value_expression(field_name, value)
    try:
        from qgis.core import QgsFeatureRequest
        request = QgsFeatureRequest().setFilterExpression(expression)
        features = list(layer.getFeatures(request))
        if features:
            return features
    except Exception as exc:
        log_exception(
            f"No se pudo filtrar por expresión en '{field_name}' con valor '{value}'",
            exc,
        )

    target = "" if value in (None, "") else str(value).strip()
    matches = []
    for feat in layer.getFeatures():
        feat_value = feat[field_index]
        if feat_value == value:
            matches.append(feat)
            continue
        if feat_value in (None, "") and target == "":
            matches.append(feat)
            continue
        if str(feat_value).strip() == target:
            matches.append(feat)
    return matches
