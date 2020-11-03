#
# Copyright 2020 3liz
# Author: David Marteau
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
""" Handle geometry
"""
import os
import logging
import re

from osgeo import ogr

from pyqgiswps.inout.formats import Format, FORMATS
from pyqgiswps.inout import (LiteralInput,
                        ComplexInput,
                        BoundingBoxInput,
                        LiteralOutput,
                        ComplexOutput,
                        BoundingBoxOutput)

from pyqgiswps.exceptions import (NoApplicableCode,
                              InvalidParameterValue,
                              MissingParameterValue,
                              ProcessException)

from qgis.core import (QgsProcessing,
                       QgsCoordinateReferenceSystem,
                       QgsGeometry,
                       QgsReferencedGeometry,
                       QgsRectangle,
                       QgsReferencedRectangle,
                       QgsReferencedPointXY,
                       QgsWkbTypes,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterDefinition,
                       QgsProcessingParameterGeometry,
                       QgsProcessingParameterPoint)

from ..processingcontext import MapContext, ProcessingContext

from typing import Mapping, Any, TypeVar, Union, Tuple

WPSInput  = Union[LiteralInput, ComplexInput, BoundingBoxInput]
WPSOutput = Union[LiteralOutput, ComplexOutput, BoundingBoxOutput]

LOGGER = logging.getLogger('SRVLOG')

GeometryParameterTypes = (QgsProcessingParameterPoint, QgsProcessingParameterGeometry)

# ------------------------------------
# Processing parameters ->  WPS input
# ------------------------------------

def parse_input_definition( param: QgsProcessingParameterDefinition, kwargs) -> WPSInput:
    """ Convert processing input to File Input 
    """
    typ = param.type()
    if typ == "extent":
       # XXX This is the default, do not presume anything
       # about effective crs at compute time
       kwargs['crss'] = ['EPSG:4326']
       return BoundingBoxInput(**kwargs)
    elif isinstance(param, GeometryParameterTypes):
        kwargs['supported_formats'] = [Format.from_definition(FORMATS.GEOJSON),
                                       Format.from_definition(FORMATS.GML),
                                       Format.from_definition(FORMATS.WKT)]
        return ComplexInput(**kwargs)

    return None


# --------------------------------------
# WPS inputs ->  processing inputs data
# --------------------------------------

WKT_EXPR = re.compile( r"^\s*(?:CRS=(.*);)?(.*?)$" )

def wkt_to_goeometry( wkt: str ) -> QgsReferencedGeometry:
    """ Convert wkt to qgis geometry

        Handle CRS= prefix
    """
    m = WKT_EXPR.match(wkt)
    if m:
        g = QgsGeometry.fromWkt(m.groups('')[1])
        if not g.isNull():
            crs = QgsCoordinateReferenceSystem( m.groups('')[0] )
            if crs.isValid():
                g = QgsReferencedGeometry(g,crs)
        return g
    raise InvalidParameterValue("Invalid wkt format")


def input_to_geometry( inp: WPSInput ):
    """ Handle point from complex input
    """
    data_format = inp.data_format
    if data_format.mime_type == FORMATS.WKT.mime_type:
        return wkt_to_goeometry(inp.data)

    geom = None
    if data_format.mime_type == FORMATS.GEOJSON.mime_type:
        geom = ogr.CreateGeometryFromJson(inp.data)
        if not geom:
            raise InvalidParameterValue("Invalid geojson format")
    elif data_format.mime_type == FORMATS.GML.mime_type:
        # XXX Check that we do not get CRS  from GML
        # with ogr data
        geom = ogr.CreateGeometryFromGML(inp.data)
        if not geom:
            raise InvalidParameterValue("Invalid gml format")

    if geom:
        srs  = geom.GetSpatialReference()
        geom = QgsGeometry.fromWkt(geom.ExportToWkt())
        if srs:
            crs  = QgsCoordinateReferenceSystem.fromWkt(srs.ExportToWkt())
            if crs.isValid():
                geom = QgsReferencedGeometry( geom, crs )

        return geom

    raise NoApplicableCode("Unsupported data format: %s" % data_format)


def input_to_point( inp: WPSInput ) -> Any:
    """ Convert input to point
    """
    g = input_to_geometry( inp )
    if isinstance(g, QgsReferencedGeometry):
        g = QgsReferencedPointXY( g.centroid().asPoint(), g.crs() )
    return g 


def input_to_extent( inp: WPSInput ) -> Any:
    """ Convert to extent 
    """
    r = inp.data
    rect  = QgsRectangle(float(r[0]),float(r[2]),float(r[1]),float(r[3]))
    ref   = QgsCoordinateReferenceSystem(inp.crs)
    return QgsReferencedRectangle(rect, ref)


def get_processing_value( param: QgsProcessingParameterDefinition, inp: WPSInput,
                          context: ProcessingContext) -> Any:
    """ Return processing value from wps inputs

        Processes other inputs than layers
    """
    if isinstance(param, QgsProcessingParameterGeometry):
        value = input_to_geometry( inp[0] )
    elif isinstance(param, QgsProcessingParameterPoint):
        value = input_to_point( inp[0] )
    elif param.type() == 'extent':
        value = input_to_extent( inp[0] )
    else:
        value = None

    return value

