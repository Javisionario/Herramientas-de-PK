# -*- coding: utf-8 -*-
"""
Small shared helpers for PK Tools.

The core convention is:
  - raw M values keep the units configured by the user ("m" or "km")
  - PK values used internally by the tools are expressed in kilometers
  - display strings are built at the edge of the UI
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

VALID_M_UNITS = ("m", "km")
VALID_OUTPUT_MODES = ("pk", "raw_m")
LOG_TAG = "PK Tools"


class PKParseError(ValueError):
    """Raised when a user-entered PK cannot be parsed."""


def normalize_m_units(m_units):
    """Return a supported M unit value."""
    return m_units if m_units in VALID_M_UNITS else "m"


def normalize_output_mode(output_mode):
    """Return a supported output display mode."""
    return output_mode if output_mode in VALID_OUTPUT_MODES else "pk"


def output_terms(output_mode):
    """Return UI terms adapted to the selected display mode."""
    if normalize_output_mode(output_mode) == "raw_m":
        return {
            "identifier": "Identificador",
            "identifier_lower": "identificador",
            "measure": "Medida",
            "tool_locate": "Localizar medida",
            "located_layer": "Localizacion medidas M",
            "identified_layer": "Identificacion medidas M",
            "id_field": "IDENTIFICADOR",
            "value_field": "M_RAW",
            "pk_number_field": "PK_NUM",
        }
    return {
        "identifier": "Vía",
        "identifier_lower": "vía",
        "measure": "PK",
        "tool_locate": "Localizar PK",
        "located_layer": "Localización de PKs",
        "identified_layer": "Identificacion PKs",
        "id_field": "VIA",
        "value_field": "PK",
        "pk_number_field": "PK_NUM",
    }


def log_exception(context, exc=None):
    """Write technical details to the QGIS log without showing them to users."""
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
        raise PKParseError(f"El {field_name} no es un numero valido.")
    if not dec.is_finite():
        raise PKParseError(f"El {field_name} no es un numero valido.")
    return dec


def round_half_up_to_int(value):
    """Round a Decimal/numeric value to the nearest integer, halves upwards."""
    dec = value if isinstance(value, Decimal) else _decimal_from_value(value)
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def raw_m_to_pk_km(raw_m, m_units="m"):
    """Convert a raw M value to kilometers according to the configured units."""
    units = normalize_m_units(m_units)
    value = float(raw_m)
    return value / 1000.0 if units == "m" else value


def pk_km_to_raw_m(pk_km, m_units="m"):
    """Convert an internal PK value in kilometers to raw M units."""
    units = normalize_m_units(m_units)
    value = float(pk_km)
    return value * 1000.0 if units == "m" else value


def format_pk(value, units="km", km_width=0):
    """
    Format a PK as km+mmm.

    The value is converted to integer meters first and then normalized with
    divmod, which avoids outputs such as 9+1000.
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
    Parse a PK entered by the user and return kilometers.

    Accepted examples:
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
    """Parse a raw M/measure value entered by the user."""
    raw = str(text).strip()
    if not raw:
        raise PKParseError("Introduce una medida.")
    return float(_decimal_from_value(raw, "medida"))


def parse_pk_components(km_text, meters_text=None):
    """
    Parse the legacy Localizar PK two-field UI.

    The first field may contain a complete PK (for example 150+500). When the
    second field is used, it is interpreted as meters added to the first field,
    preserving the historical behavior.
    """
    first = str(km_text).strip()
    second = "" if meters_text is None else str(meters_text).strip()

    if not second or second in ("0", "000"):
        return parse_pk_text(first)

    if "+" in first:
        raise PKParseError("Si usas formato km+metros, deja el campo Metros en 000.")

    km = _decimal_from_value(first, "kilometro")
    meters = _decimal_from_value(second, "metro")
    if meters < 0:
        raise PKParseError("Los metros del PK no pueden ser negativos.")
    return float(km + meters / Decimal("1000"))


def format_number_compact(value, decimals=3):
    """Format a number without useless trailing zeroes."""
    number = float(value)
    if abs(number - round(number)) < 10 ** -decimals:
        return str(int(round(number)))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def format_raw_m(raw_m, m_units="m", decimals=3, include_unit=True):
    """Format a raw M value with its configured units."""
    units = normalize_m_units(m_units)
    text = format_number_compact(raw_m, decimals)
    return f"{text} {units}" if include_unit else text


def format_pk_value(pk_km, include_decimal=True):
    """Format the standard PK display value."""
    pk_text = format_pk(pk_km, units="km")
    if include_decimal:
        return f"{pk_text} ({float(pk_km):.3f} km)"
    return pk_text


def format_output_value(raw_m=None, pk_km=None, m_units="m", output_mode="pk"):
    """
    Build the final user-facing value.

    output_mode is intentionally simple for now. It prepares the code for a
    future raw-M display option without changing the current UI behavior.
    """
    if pk_km is None and raw_m is not None:
        pk_km = raw_m_to_pk_km(raw_m, m_units)

    output_mode = normalize_output_mode(output_mode)
    if output_mode == "raw_m" and raw_m is not None:
        return f"M {format_raw_m(raw_m, m_units)}"

    return f"PK {format_pk_value(pk_km)}"


def format_value_for_mode(raw_m, m_units="m", output_mode="pk", for_button=False):
    """Format a raw M value as either PK text or raw-M text."""
    output_mode = normalize_output_mode(output_mode)
    if output_mode == "raw_m":
        if for_button:
            return format_raw_m(raw_m, m_units)
        return f"M {format_raw_m(raw_m, m_units, include_unit=False)}"

    return f"PK {format_pk(raw_m_to_pk_km(raw_m, m_units))}"


def format_pk_export_text(raw_m, m_units="m"):
    """Format a raw M value as km+mmm text, without the PK prefix."""
    return format_pk(raw_m_to_pk_km(raw_m, m_units), units="km")


def pk_numeric_km(raw_m, m_units="m"):
    """Return the PK numeric value in km rounded to 3 decimals."""
    dec = Decimal(str(raw_m_to_pk_km(raw_m, m_units)))
    return float(dec.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def raw_m_export_value(raw_m):
    """Return a raw M value for numeric export fields."""
    return float(raw_m)


def interval_tolerance_to_raw(tolerance_m=10.0, m_units="m"):
    """Convert a tolerance expressed in meters to the configured raw M units."""
    return float(tolerance_m) if normalize_m_units(m_units) == "m" else float(tolerance_m) / 1000.0


def merge_m_intervals(intervals, tolerance=0.0):
    """Sort and merge M coverage intervals."""
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
    Classify a raw M target against real coverage intervals.

    Returns a dict with status: covered, gap, below, above or empty.
    For gap/below/above, nearest_m contains the closest available endpoint.
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
    """Return the closest start/end endpoint from a list of intervals."""
    endpoints = []
    for start, end in intervals:
        endpoints.extend([float(start), float(end)])
    if not endpoints:
        return None
    target = float(target_m)
    return min(endpoints, key=lambda value: (abs(value - target), value))


def find_layer_by_config(cfg):
    """Find the configured layer by id, falling back to the saved name."""
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
    """Return (layer, id_field, error_message) for the configured line-M layer."""
    from qgis.core import QgsWkbTypes

    layer_name = (cfg.get("layer_name") or "").strip()
    id_field = (cfg.get("id_field") or default_id_field).strip() or default_id_field

    if not (cfg.get("layer_id") or layer_name):
        return None, id_field, "No hay capa de trabajo configurada."

    layer = find_layer_by_config(cfg)
    if layer is None:
        name = layer_name or cfg.get("layer_id") or "configurada"
        return None, id_field, f"No se ha encontrado la capa '{name}'. Revisa la configuración."

    if layer.geometryType() != QgsWkbTypes.LineGeometry:
        return None, id_field, f"La capa '{layer.name()}' no es lineal."

    if not QgsWkbTypes.hasM(layer.wkbType()):
        return None, id_field, f"La capa '{layer.name()}' no tiene geometría M."

    if layer.fields().indexOf(id_field) == -1:
        return None, id_field, f"La capa '{layer.name()}' no tiene el campo '{id_field}'."

    return layer, id_field, None


def _field_value_expression(field_name, value):
    field_ref = '"' + str(field_name).replace('"', '""') + '"'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{field_ref} = {value}"
    value_ref = "'" + str(value).replace("'", "''") + "'"
    return f"{field_ref} = {value_ref}"


def features_by_field_value(layer, field_name, value):
    """
    Fetch features matching a field value using provider filtering.

    Falls back to an in-memory scan only if the provider expression returns no
    features, which keeps Localizar fast on normal indexed/provider-supported
    layers while preserving compatibility with awkward providers.
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
            f"No se pudo filtrar por expresion en '{field_name}' con valor '{value}'",
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
