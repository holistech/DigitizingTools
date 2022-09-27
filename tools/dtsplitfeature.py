# -*- coding: utf-8 -*-
"""
dtsplitfeature
`````````````
"""
from datetime import datetime

"""
Part of DigitizingTools, a QGIS plugin that
subsumes different tools neded during digitizing sessions

* begin                : 2017-06-12
* copyright          : (C) 2017 by Bernhard Ströbl
* email                : bernhard.stroebl@jena.de

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.
"""

from builtins import str
from builtins import range
from qgis.PyQt import QtCore, QtGui, QtWidgets
from qgis.core import *
from qgis.gui import *
import dt_icons_rc
from dttools import DtSingleEditTool, DtSplitFeatureTool
import dtutils


class DtSplitFeature(DtSingleEditTool):
    '''Split feature'''

    def __init__(self, iface, toolBar):
        super().__init__(iface, toolBar,
                         QtGui.QIcon(":/splitfeature.png"),
                         QtCore.QCoreApplication.translate("digitizingtools", "Split Features"),
                         geometryTypes=[2, 3, 5, 6], crsWarning=False, dtName="dtSplitFeature")

        self.tool = DtSplitFeatureTool(self.iface)
        self.tool.finishedDigitizing.connect(self.digitizingFinished)
        self.reset()
        self.enable()

    def reset(self):
        self.editLayer = None
        self.feature = None
        self.rubberBand = None

    def digitizingFinished(self, splitGeom):
        title = QtCore.QCoreApplication.translate("digitizingtools", "Split Features")
        hlColor, hlFillColor, hlBuffer, hlMinWidth = dtutils.dtGetHighlightSettings()
        selIds = self.editLayer.selectedFeatureIds()
        self.editLayer.removeSelection()

        # First commit all changes to the layer
        # TODO: Check for commit errors and perform a rollback, inform the user
        self.editLayer.commitChanges()
        self.editLayer = self.iface.activeLayer()
        self.editLayer.startEditing()

        dtNow = datetime.now()

        if self.editLayer.crs().srsid() != QgsProject.instance().crs().srsid():
            splitGeom.transform(QgsCoordinateTransform(
                QgsProject.instance().crs(), self.editLayer.crs(),
                QgsProject.instance()
            ))
        splitterPList = dtutils.dtExtractPoints(splitGeom)
        featuresToAdd = []  # store new features in this array
        featuresToKeep = {}  # store geoms that will stay with their id as key
        featuresToSplit = {}
        topoEditEnabled = QgsProject.instance().topologicalEditing()
        topoTestPointsAll = []  # store all topoTestPoints for all parts

        for aFeat in self.editLayer.getFeatures(QgsFeatureRequest(splitGeom.boundingBox())):
            # This id is the predecessor of all new features
            anId = aFeat.id()

            # work either on selected or all features if no selection exists
            if len(selIds) == 0 or selIds.count(anId) != 0:
                aGeom = aFeat.geometry()

                if splitGeom.intersects(aGeom):
                    featuresToSplit[anId] = aFeat

        if len(featuresToSplit) > 0:
            self.editLayer.beginEditCommand(QtCore.QCoreApplication.translate("editcommand", "Features split"))

        for anId, aFeat in list(featuresToSplit.items()):
            aGeom = aFeat.geometry()
            wasMultipart = aGeom.isMultipart() and len(aGeom.asGeometryCollection()) > 1
            splitResult = []
            geomsToSplit = []

            if wasMultipart:
                keepGeom = None

                for aPart in aGeom.asGeometryCollection():
                    if splitGeom.intersects(aPart):
                        geomsToSplit.append(aPart)
                    else:
                        if keepGeom == None:
                            keepGeom = aPart
                        else:
                            keepGeom = keepGeom.combine(aPart)
            else:
                geomsToSplit.append(aGeom)

            for thisGeom in geomsToSplit:
                try:
                    result, newGeometries, topoTestPoints = thisGeom.splitGeometry(splitterPList, topoEditEnabled)
                except:
                    self.iface.messageBar().pushCritical(title,
                                                         dtutils.dtGetErrorMessage() + QtCore.QCoreApplication.translate(
                                                             "digitizingtools", "splitting of feature") + " " + str(
                                                             aFeat.id()))
                    return None

                topoTestPointsAll.append(topoTestPoints)

                if result == 0:  # success
                    if len(newGeometries) > 0:
                        splitResult = newGeometries

                        if wasMultipart:
                            splitResult.append(thisGeom)

                if wasMultipart and len(splitResult) > 1:
                    takeThisOne = -1

                    while takeThisOne == -1:
                        for i in range(len(splitResult)):
                            aNewGeom = splitResult[i]
                            hl = QgsHighlight(self.iface.mapCanvas(), aNewGeom, self.editLayer)
                            hl.setColor(hlColor)
                            hl.setFillColor(hlFillColor)
                            hl.setBuffer(hlBuffer)
                            hl.setWidth(hlMinWidth)
                            hl.show()
                            answer = QtWidgets.QMessageBox.question(
                                None, QtCore.QCoreApplication.translate("digitizingtools", "Split Multipart Feature"),
                                QtCore.QCoreApplication.translate("digitizingtools",
                                                                  "Create new feature from this part?"),
                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.NoToAll)
                            hl.hide()
                            hl = None
                            if answer == QtWidgets.QMessageBox.Yes:
                                takeThisOne = i
                                break
                            elif answer == QtWidgets.QMessageBox.NoToAll:
                                keepGeom = aGeom
                                newGeoms = []
                                takeThisOne = -2
                                break
                            elif answer == QtWidgets.QMessageBox.Cancel:
                                self.editLayer.destroyEditCommand()
                                return None

                    if takeThisOne == -2:
                        break
                    elif takeThisOne >= 0:
                        newGeoms = [splitResult.pop(takeThisOne)]

                        if len(splitResult) > 0:  # should be
                            for aNewGeom in splitResult:
                                if keepGeom == None:
                                    keepGeom = aNewGeom
                                else:
                                    keepGeom = keepGeom.combine(aNewGeom)
                else:  # singlePart
                    keepGeom = thisGeom
                    newGeoms = newGeometries

                context = QgsExpressionContextUtils.createFeatureBasedContext(aFeat, self.editLayer.fields())
                global_scope = QgsExpressionContextUtils.globalProjectLayerScopes(self.editLayer)
                context.appendScopes(global_scope)

                scope = QgsExpressionContextScope()
                scope.addVariable(QgsExpressionContextScope.StaticVariable("sm_operation", 1))
                scope.addVariable(QgsExpressionContextScope.StaticVariable("sm_predecessors", f"{anId}"))
                scope.addVariable(QgsExpressionContextScope.StaticVariable("sm_operation_date", str(dtNow)))
                context.appendScope(scope)
                # Activate the values with expressions like this:
                #  CASE WHEN @sm_operation = 1 OR @sm_operation = 2 THEN @sm_predecessors ELSE sm_predecessors END

                for i in range(len(aFeat.attributes())):
                    if self.editLayer.defaultValueDefinition(i):
                        aFeat[i] = self.editLayer.defaultValue(i, aFeat, context)

                newFeatures = dtutils.dtMakeFeaturesFromGeometries(self.editLayer, aFeat, newGeoms)
                featuresToAdd = featuresToAdd + newFeatures
                # Store the predecessor id in the feature
                # for feature in featuresToAdd:
                #    feature["sm_predecessors"] = f"{anId}"

            aFeat.setGeometry(keepGeom)
            featuresToKeep[anId] = aFeat

        for anId, aFeat in list(featuresToKeep.items()):
            self.editLayer.updateFeature(aFeat)

        if len(featuresToAdd) > 0:
            if self.editLayer.addFeatures(featuresToAdd):

                for topoTestPoint in topoTestPointsAll:
                    for pt in topoTestPoint:
                        self.editLayer.addTopologicalPoints(pt)

                self.editLayer.endEditCommand()
            else:
                self.editLayer.destroyEditCommand()
        else:
            self.editLayer.destroyEditCommand()

        if hasattr(self.editLayer, "selectByIds"):  # since QGIS 2.16
            self.editLayer.selectByIds(selIds)
        else:
            self.editLayer.setSelectedFeatures(selIds)

    def process(self):
        self.canvas.setMapTool(self.tool)
        self.act.setChecked(True)
        self.editLayer = self.iface.activeLayer()
