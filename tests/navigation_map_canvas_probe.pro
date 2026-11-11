QT += core gui quick qml dbus
CONFIG += console c++14
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-navigation-map-canvas-probe
SOURCES += navigation_map_canvas_probe.cpp ../display-source/carui/navigationhost.cpp ../display-source/carui/mapcanvas.cpp
HEADERS += ../display-source/carui/navigationhost.h ../display-source/carui/mapcanvas.h
INCLUDEPATH += ../display-source/carui
include(../sdk/qt/sailplay-sdk.pri)
