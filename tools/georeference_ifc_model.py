"""
IMPORTANT:
    
    This file contains code snippets that must be included in the
    addon.py and tools.py files. On their own, they do not provide
    any functionality.
"""


#---------------------------------------------------------------------------------------------------
# TO INCLUDE IN addon.py
#---------------------------------------------------------------------------------------------------
"""
Note:
    This key-value pair must be included in the `handlers` dictionary
    inside the `_execute_command_internal` definition.
"""
#---------------------------------------------------------------------------------------------------

georeference_ifc_model": self.georeference_ifc_model,

#---------------------------------------------------------------------------------------------------
# TO INCLUDE IN addon.py
#---------------------------------------------------------------------------------------------------
"""
Note:
    This definition must be added inside the `BlenderMCPServer` class,
    along with the other existing definitions.
"""
#---------------------------------------------------------------------------------------------------

@staticmethod
def georeference_ifc_model(
    crs_mode: str,
    epsg: int = None,
    crs_name: str = None,
    geodetic_datum: str = None,
    map_projection: str = None,
    map_zone: str = None,
    eastings: float = None,
    northings: float = None,
    orthogonal_height: float = 0.0,
    scale: float = 1.0,
    x_axis_abscissa: float = None,
    x_axis_ordinate: float = None,
    true_north_azimuth_deg: float = None,
    context_filter: str = "Model",
    context_index: int = None,
    site_ref_latitude: list = None,         # IFC format [deg, min, sec, millionth]
    site_ref_longitude: list = None,        # IFC format [deg, min, sec, millionth]
    site_ref_elevation: float = None,
    site_ref_latitude_dd: float = None,     # Decimal degrees (optional)
    site_ref_longitude_dd: float = None,    # Decimal degrees (optional)
    overwrite: bool = False,
    dry_run: bool = False,
    write_path: str = None,
):
    """
    Usage:
    Creates/updates IfcProjectedCRS + IfcMapConversion in the opened IFC.
    Optionally updates IfcSite.RefLatitude/RefLongitude/RefElevation.
    If `pyproj` is available, it can convert Lat/Long (degrees) ⇄ E/N (meters)
    according to the given EPSG.

    Requirements:
    CRS declaration is ALWAYS required:
    - crs_mode="epsg" + epsg=XXXX    OR
    - crs_mode="custom" + (crs_name, geodetic_datum, map_projection [, map_zone])

    Minimum MapConversion information:
    - eastings + northings
    (if missing but lat/long + EPSG + pyproj are available, they are computed)
    """
    import math
    from bonsai.bim.ifc import IfcStore
    file = IfcStore.get_file()
    if file is None:
        return {"success": False, "error": "No IFC file is currently loaded"}

    warnings = []
    actions = {"created_crs": False, "created_map_conversion": False,
            "updated_map_conversion": False, "updated_site": False,
            "overwrote": False, "wrote_file": False}
    debug = {}

    # ---------- helpers ----------
    def dd_to_ifc_dms(dd: float):
        """Converts decimal degrees to [deg, min, sec, millionth] (sign carried by degrees)."""
        if dd is None:
            return None
        sign = -1 if dd < 0 else 1
        v = abs(dd)
        deg = int(v)
        rem = (v - deg) * 60
        minutes = int(rem)
        sec_float = (rem - minutes) * 60
        seconds = int(sec_float)
        millionth = int(round((sec_float - seconds) * 1_000_000))
        # Normalizes rounding (e.g. 59.999999 → 60)
        if millionth == 1_000_000:
            seconds += 1
            millionth = 0
        if seconds == 60:
            minutes += 1
            seconds = 0
        if minutes == 60:
            deg += 1
            minutes = 0
        return [sign * deg, minutes, seconds, millionth]

    def select_context():
        ctxs = file.by_type("IfcGeometricRepresentationContext") or []
        if not ctxs:
            return None, "No IfcGeometricRepresentationContext found"
        if context_index is not None and 0 <= context_index < len(ctxs):
            return ctxs[context_index], None
        # By filter (default "Model", case-insensitive)
        if context_filter:
            for c in ctxs:
                if (getattr(c, "ContextType", None) or "").lower() == context_filter.lower():
                    return c, None
        # Fallback to the first one
        return ctxs[0], None

    # ---------- 1) CRS Validation ----------
    if crs_mode not in ("epsg", "custom"):
        return {"success": False, "error": "crs_mode must be 'epsg' or 'custom'"}

    if crs_mode == "epsg":
        if not epsg:
            return {"success": False, "error": "epsg code required when crs_mode='epsg'"}
        crs_name_final = f"EPSG:{epsg}"
        geodetic_datum = geodetic_datum or "WGS84"
        map_projection = map_projection or "TransverseMercator"  # usual UTM
        # map_zone is optional
    else:
        # custom
        missing = [k for k in ("crs_name", "geodetic_datum", "map_projection") if locals().get(k) in (None, "")]
        if missing:
            return {"success": False, "error": f"Missing fields for custom CRS: {', '.join(missing)}"}
        crs_name_final = crs_name

    # ---------- 2) Complete E/N from Lat/Long (if missing and pyproj is available) ----------
    proj_used = None
    try:
        if (eastings is None or northings is None) and (site_ref_latitude_dd is not None and site_ref_longitude_dd is not None) and crs_mode == "epsg":
            try:
                from pyproj import Transformer
                # Assume lat/long in WGS84; if the EPSG is not WGS84-derived, pyproj handles the conversion
                transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
                e, n = transformer.transform(site_ref_longitude_dd, site_ref_latitude_dd)
                eastings = e if eastings is None else eastings
                northings = n if northings is None else northings
                proj_used = f"EPSG:4326->EPSG:{epsg}"
            except Exception as _e:
                warnings.append(f"Could not convert Lat/Long to E/N: {_e}. Provide eastings/northings manually.")
    except Exception as _e:
        warnings.append(f"pyproj not available to compute E/N: {_e}. Provide eastings/northings manually.")

    # ---------- E/N Validation ----------
    if eastings is None or northings is None:
        return {"success": False, "error": "eastings and northings are required (or provide lat/long + EPSG with pyproj installed)"}

    # ---------- 3) Select context ----------
    context, ctx_err = select_context()
    if not context:
        return {"success": False, "error": ctx_err or "No context found"}

    # ---------- 4) Detect existing ones and handle overwrite ----------
    # Inverse: context.HasCoordinateOperation is already handled by ifcopenshell as an attribute
    existing_ops = list(getattr(context, "HasCoordinateOperation", []) or [])
    existing_map = None
    existing_crs = None
    for op in existing_ops:
        if op.is_a("IfcMapConversion"):
            existing_map = op
            existing_crs = getattr(op, "TargetCRS", None)
            break

    if existing_map and not overwrite:
        return {
            "success": True,
            "georeferenced": True,
            "message": "MapConversion already exists. Use overwrite=True to replace it.",
            "context_used": {"identifier": getattr(context, "ContextIdentifier", None), "type": getattr(context, "ContextType", None)},
            "map_conversion": {
                "eastings": getattr(existing_map, "Eastings", None),
                "northings": getattr(existing_map, "Northings", None),
                "orthogonal_height": getattr(existing_map, "OrthogonalHeight", None),
                "scale": getattr(existing_map, "Scale", None),
                "x_axis_abscissa": getattr(existing_map, "XAxisAbscissa", None),
                "x_axis_ordinate": getattr(existing_map, "XAxisOrdinate", None),
            },
            "crs": {
                "name": getattr(existing_crs, "Name", None) if existing_crs else None,
                "geodetic_datum": getattr(existing_crs, "GeodeticDatum", None) if existing_crs else None,
                "map_projection": getattr(existing_crs, "MapProjection", None) if existing_crs else None,
                "map_zone": getattr(existing_crs, "MapZone", None) if existing_crs else None,
            },
            "warnings": warnings,
            "actions": actions,
        }

    # ---------- 5) Build/Update CRS ----------
    if existing_crs and overwrite:
        actions["overwrote"] = True
        try:
            file.remove(existing_crs)
        except Exception:
            warnings.append("Could not remove the existing CRS; a new one will be created anyway.")

    # If custom, use the provided values; if EPSG, build the name and defaults
    crs_kwargs = {
        "Name": crs_name_final,
        "GeodeticDatum": geodetic_datum,
        "MapProjection": map_projection,
    }
    if map_zone:
        crs_kwargs["MapZone"] = map_zone

    crs_entity = file.create_entity("IfcProjectedCRS", **crs_kwargs)
    actions["created_crs"] = True

    # ---------- 6) Calculate orientation (optional) ----------
    # If true_north_azimuth_deg is given as the azimuth from North (model +Y axis) towards East (clockwise),
    # We can derive an approximate X vector: X = (cos(az+90°), sin(az+90°)).
    if (x_axis_abscissa is None or x_axis_ordinate is None) and (true_north_azimuth_deg is not None):
        az = math.radians(true_north_azimuth_deg)
        # Estimated X vector rotated 90° from North:
        x_axis_abscissa = math.cos(az + math.pi / 2.0)
        x_axis_ordinate = math.sin(az + math.pi / 2.0)

    # Defaults if still missing
    x_axis_abscissa = 1.0 if x_axis_abscissa is None else float(x_axis_abscissa)
    x_axis_ordinate = 0.0 if x_axis_ordinate is None else float(x_axis_ordinate)
    scale = 1.0 if scale is None else float(scale)
    orthogonal_height = 0.0 if orthogonal_height is None else float(orthogonal_height)

    # ---------- 7) Build/Update IfcMapConversion ----------
    if existing_map and overwrite:
        try:
            file.remove(existing_map)
        except Exception:
            warnings.append("Could not remove the existing MapConversion; another one will be created anyway.")

    map_kwargs = {
        "SourceCRS": context,
        "TargetCRS": crs_entity,
        "Eastings": float(eastings),
        "Northings": float(northings),
        "OrthogonalHeight": float(orthogonal_height),
        "XAxisAbscissa": float(x_axis_abscissa),
        "XAxisOrdinate": float(x_axis_ordinate),
        "Scale": float(scale),
    }
    map_entity = file.create_entity("IfcMapConversion", **map_kwargs)
    actions["created_map_conversion"] = True

    # ---------- 8) (Optional) Update IfcSite ----------
    try:
        sites = file.by_type("IfcSite") or []
        if sites:
            site = sites[0]
            # If no IFC lists are provided but decimal degrees are, convert them
            if site_ref_latitude is None and site_ref_latitude_dd is not None:
                site_ref_latitude = dd_to_ifc_dms(site_ref_latitude_dd)
            if site_ref_longitude is None and site_ref_longitude_dd is not None:
                site_ref_longitude = dd_to_ifc_dms(site_ref_longitude_dd)

            changed = False
            if site_ref_latitude is not None:
                site.RefLatitude = site_ref_latitude
                changed = True
            if site_ref_longitude is not None:
                site.RefLongitude = site_ref_longitude
                changed = True
            if site_ref_elevation is not None:
                site.RefElevation = float(site_ref_elevation)
                changed = True
            if changed:
                actions["updated_site"] = True
        else:
            warnings.append("No IfcSite found; lat/long/elevation were not updated.")
    except Exception as e:
        warnings.append(f"Could not update IfcSite: {e}")

    # ---------- 9) (Optional) Save ----------
    if write_path and not dry_run:
        try:
            file.write(write_path)
            actions["wrote_file"] = True
        except Exception as e:
            warnings.append(f"Could not write IFC to'{write_path}': {e}")

    # ---------- 10) Response ----------
    return {
        "success": True,
        "georeferenced": True,
        "crs": {
            "name": getattr(crs_entity, "Name", None),
            "geodetic_datum": getattr(crs_entity, "GeodeticDatum", None),
            "map_projection": getattr(crs_entity, "MapProjection", None),
            "map_zone": getattr(crs_entity, "MapZone", None),
        },
        "map_conversion": {
            "eastings": float(eastings),
            "northings": float(northings),
            "orthogonal_height": float(orthogonal_height),
            "scale": float(scale),
            "x_axis_abscissa": float(x_axis_abscissa),
            "x_axis_ordinate": float(x_axis_ordinate),
        },
        "context_used": {
            "identifier": getattr(context, "ContextIdentifier", None),
            "type": getattr(context, "ContextType", None),
        },
        "site": {
            "ref_latitude": site_ref_latitude,
            "ref_longitude": site_ref_longitude,
            "ref_elevation": site_ref_elevation,
        },
        "proj_used": proj_used,
        "warnings": warnings,
        "actions": actions,
    }

#---------------------------------------------------------------------------------------------------
# TO INCLUDE IN tools.py
#---------------------------------------------------------------------------------------------------
"""
Note:
    This code snippet must be included within the IFC tools block 
    of the `tool.py` file.
"""
#---------------------------------------------------------------------------------------------------

@mcp.tool()
def georeference_ifc_model(
    crs_mode: str,
    epsg: int = None,
    crs_name: str = None,
    geodetic_datum: str = None,
    map_projection: str = None,
    map_zone: str = None,
    eastings: float = None,
    northings: float = None,
    orthogonal_height: float = 0.0,
    scale: float = 1.0,
    x_axis_abscissa: float = None,
    x_axis_ordinate: float = None,
    true_north_azimuth_deg: float = None,
    context_filter: str = "Model",
    context_index: int = None,
    site_ref_latitude: list = None,      # [deg, min, sec, millionth]
    site_ref_longitude: list = None,     # [deg, min, sec, millionth]
    site_ref_elevation: float = None,
    site_ref_latitude_dd: float = None,  # Decimal degrees (optional)
    site_ref_longitude_dd: float = None, # Decimal degrees (optional)
    overwrite: bool = False,
    dry_run: bool = False,
    write_path: str = None,
) -> str:
    """
    Georeferences the IFC currently opened in Bonsai/BlenderBIM by creating or 
    updating IfcProjectedCRS and IfcMapConversion. Optionally updates IfcSite 
    and writes the file to disk.
    """
    import json
    blender = get_blender_connection()

    # Build params excluding None values to keep the payload clean
    params = {
        "crs_mode": crs_mode,
        "epsg": epsg,
        "crs_name": crs_name,
        "geodetic_datum": geodetic_datum,
        "map_projection": map_projection,
        "map_zone": map_zone,
        "eastings": eastings,
        "northings": northings,
        "orthogonal_height": orthogonal_height,
        "scale": scale,
        "x_axis_abscissa": x_axis_abscissa,
        "x_axis_ordinate": x_axis_ordinate,
        "true_north_azimuth_deg": true_north_azimuth_deg,
        "context_filter": context_filter,
        "context_index": context_index,
        "site_ref_latitude": site_ref_latitude,
        "site_ref_longitude": site_ref_longitude,
        "site_ref_elevation": site_ref_elevation,
        "site_ref_latitude_dd": site_ref_latitude_dd,
        "site_ref_longitude_dd": site_ref_longitude_dd,
        "overwrite": overwrite,
        "dry_run": dry_run,
        "write_path": write_path,
    }
    params = {k: v for k, v in params.items() if v is not None}

    try:
        result = blender.send_command("georeference_ifc_model", params)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("georeference_ifc_model error")
        return json.dumps(
            {"success": False, "error": "Could not georeference the model.", "details": str(e)},
            ensure_ascii=False,
            indent=2,
        )