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

get_ifc_georeferencing_info": self.get_ifc_georeferencing_info,


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
def get_ifc_georeferencing_info(include_contexts: bool = False):
    """
    Retrieves georeferencing information from the currently opened IFC file (CRS, MapConversion, WCS, TrueNorth, IfcSite).

    Args:
        include_contexts (bool): If True, adds the breakdown of RepresentationContexts and operations

    Returns:
        dict: Structure with:
        {
        "georeferenced": bool,
        "crs": {
            "name": str|None,
            "geodetic_datum": str|None,
            "vertical_datum": str|None,
            "map_unit": str|None
        },
        "map_conversion": {
            "eastings": float|None,
            "northings": float|None,
            "orthogonal_height": float|None,
            "scale": float|None,
            "x_axis_abscissa": float|None,
            "x_axis_ordinate": float|None
        },
        "world_coordinate_system": {"origin": [x,y,z]|None},
        "true_north": {"direction_ratios": [x,y]|None},
        "site": {
            "local_placement_origin": [x,y,z]|None,
            "ref_latitude": [deg,min,sec,millionth]|None,
            "ref_longitude": [deg,min,sec,millionth]|None,
            "ref_elevation": float|None
        },
        "contexts": [...],     # only if include_contexts=True
        "warnings": [...]
        }
    """
    try:
                    
        file = IfcStore.get_file()
        debug = {"entered": True, "has_ifc": file is not None, "projects": 0, "sites": 0, "contexts": 0}
        if file is None:
            return {"error": "No IFC file is currently loaded", "debug": debug}

        warnings = []
        result = {
            "georeferenced": False,
            "crs": {
                "name": None,
                "geodetic_datum": None,
                "vertical_datum": None,
                "map_unit": None
            },
            "map_conversion": {
                "eastings": None,
                "northings": None,
                "orthogonal_height": None,
                "scale": None,
                "x_axis_abscissa": None,
                "x_axis_ordinate": None
            },
            "world_coordinate_system": {"origin": None},
            "true_north": {"direction_ratios": None},
            "site": {
                "local_placement_origin": None,
                "ref_latitude": None,
                "ref_longitude": None,
                "ref_elevation": None
            },
            "contexts": [],
            "warnings": warnings,
            "debug":debug,
        }

        # --- IfcProject & RepresentationContexts ---
        projects = file.by_type("IfcProject")
        debug["projects"] = len(projects)
        if projects:
            project = projects[0]
            contexts = getattr(project, "RepresentationContexts", None) or []
            debug["contexts"] = len(contexts)
            for ctx in contexts:
                ctx_entry = {
                    "context_identifier": getattr(ctx, "ContextIdentifier", None),
                    "context_type": getattr(ctx, "ContextType", None),
                    "world_origin": None,
                    "true_north": None,
                    "has_coordinate_operation": []
                }

                # WorldCoordinateSystem → Local origin
                try:
                    wcs = getattr(ctx, "WorldCoordinateSystem", None)
                    if wcs and getattr(wcs, "Location", None):
                        loc = wcs.Location
                        if getattr(loc, "Coordinates", None):
                            coords = list(loc.Coordinates)
                            result["world_coordinate_system"]["origin"] = coords
                            ctx_entry["world_origin"] = coords
                except Exception as e:
                    warnings.append(f"WorldCoordinateSystem read error: {str(e)}")

                # TrueNorth
                try:
                    if hasattr(ctx, "TrueNorth") and ctx.TrueNorth:
                        tn = ctx.TrueNorth
                        ratios = list(getattr(tn, "DirectionRatios", []) or [])
                        result["true_north"]["direction_ratios"] = ratios
                        ctx_entry["true_north"] = ratios
                except Exception as e:
                    warnings.append(f"TrueNorth read error: {str(e)}")

                # HasCoordinateOperation → IfcMapConversion / TargetCRS
                try:
                    if hasattr(ctx, "HasCoordinateOperation") and ctx.HasCoordinateOperation:
                        for op in ctx.HasCoordinateOperation:
                            op_entry = {"type": op.is_a(), "target_crs": None, "map_conversion": None}

                            # TargetCRS
                            crs = getattr(op, "TargetCRS", None)
                            if crs:
                                result["crs"]["name"] = getattr(crs, "Name", None)
                                result["crs"]["geodetic_datum"] = getattr(crs, "GeodeticDatum", None)
                                result["crs"]["vertical_datum"] = getattr(crs, "VerticalDatum", None)
                                try:
                                    map_unit = getattr(crs, "MapUnit", None)
                                    result["crs"]["map_unit"] = map_unit.Name if map_unit else None
                                except Exception:
                                    result["crs"]["map_unit"] = None

                                op_entry["target_crs"] = {
                                    "name": result["crs"]["name"],
                                    "geodetic_datum": result["crs"]["geodetic_datum"],
                                    "vertical_datum": result["crs"]["vertical_datum"],
                                    "map_unit": result["crs"]["map_unit"]
                                }

                            # IfcMapConversion
                            if op.is_a("IfcMapConversion"):
                                mc = {
                                    "eastings": getattr(op, "Eastings", None),
                                    "northings": getattr(op, "Northings", None),
                                    "orthogonal_height": getattr(op, "OrthogonalHeight", None),
                                    "scale": getattr(op, "Scale", None),
                                    "x_axis_abscissa": getattr(op, "XAxisAbscissa", None),
                                    "x_axis_ordinate": getattr(op, "XAxisOrdinate", None)
                                }
                                result["map_conversion"].update(mc)
                                op_entry["map_conversion"] = mc

                            ctx_entry["has_coordinate_operation"].append(op_entry)
                except Exception as e:
                    warnings.append(f"HasCoordinateOperation read error: {str(e)}")

                if include_contexts:
                    result["contexts"].append(ctx_entry)
        else:
            warnings.append("IfcProject entity was not found.")

        # --- IfcSite (lat/long/alt local origin of placement) ---
        try:
            sites = file.by_type("IfcSite")
            debug["sites"] = len(sites)
            if sites:
                site = sites[0]
                # LocalPlacement
                try:
                    if getattr(site, "ObjectPlacement", None):
                        placement = site.ObjectPlacement
                        axisPlacement = getattr(placement, "RelativePlacement", None)
                        if axisPlacement and getattr(axisPlacement, "Location", None):
                            loc = axisPlacement.Location
                            if getattr(loc, "Coordinates", None):
                                result["site"]["local_placement_origin"] = list(loc.Coordinates)
                except Exception as e:
                    warnings.append(f"IfcSite.ObjectPlacement read error: {str(e)}")

                # Lat/Long/Alt
                try:
                    lat = getattr(site, "RefLatitude", None)
                    lon = getattr(site, "RefLongitude", None)
                    ele = getattr(site, "RefElevation", None)
                    result["site"]["ref_latitude"]  = list(lat) if lat else None
                    result["site"]["ref_longitude"] = list(lon) if lon else None
                    result["site"]["ref_elevation"] = ele
                except Exception as e:
                    warnings.append(f"IfcSite (lat/long/elev) read error: {str(e)}")
            else:
                warnings.append("IfcSite was not found.")
        except Exception as e:
            warnings.append(f"Error while querying IfcSite: {str(e)}")

        # --- Heuristic to determine georeferencing ---
        geo_flags = [
            any(result["crs"].values()),
            any(v is not None for v in result["map_conversion"].values())          
        ]
        result["georeferenced"] = all(geo_flags)

        return result

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}        
        
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
def get_ifc_georeferencing_info(include_contexts: bool = False) -> str:
    """
    Checks whether the IFC currently opened in Bonsai/BlenderBIM is georeferenced
    and returns the key georeferencing information.

    Parameters
    ----------
    include_contexts : bool
        If True, adds a breakdown of the RepresentationContexts and operations.
        

    Returns
    --------
    str (JSON pretty-printed)
        {
          "georeferenced": true|false,
          "crs": {
            "name": str|null,
            "geodetic_datum": str|null,
            "vertical_datum": str|null,
            "map_unit": str|null
          },
          "map_conversion": {
            "eastings": float|null,
            "northings": float|null,
            "orthogonal_height": float|null,
            "scale": float|null,
            "x_axis_abscissa": float|null,
            "x_axis_ordinate": float|null
          },
          "world_coordinate_system": {
            "origin": [x, y, z]|null
          },
          "true_north": {
            "direction_ratios": [x, y]|null
          },
          "site": {
            "local_placement_origin": [x, y, z]|null,
            "ref_latitude": [deg, min, sec, millionth]|null,
            "ref_longitude": [deg, min, sec, millionth]|null,
            "ref_elevation": float|null
          },
          "contexts": [...],              # only if include_contexts = true
          "warnings": [ ... ]             # Informational message
        }

    Notes
    -----
    - This tool acts as a wrapper: it sends the "get_ifc_georeferencing_info"
      command to the Blender add-on. The add-on must implement that logic
      (reading IfcProject/IfcGeometricRepresentationContext, IfcMapConversion,
      TargetCRS, IfcSite.RefLatitude/RefLongitude/RefElevation, etc.).
    - It always returns a JSON string with indentation for easier reading.
    """
    blender = get_blender_connection()
    params = {
        "include_contexts": bool(include_contexts)
    }

    try:
        result = blender.send_command("get_ifc_georeferencing_info", params)
        # Ensures that the result is serializable and easy to read
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("get_ifc_georeferencing_info error")
        return json.dumps(
            {
                "georeferenced": False,
                "error": "Unable to retrieve georeferencing information from the IFC model.",
                "details": str(e)
            },
            ensure_ascii=False,
            indent=2
        )