QT += core dbus
CONFIG += console c++11
CONFIG -= app_bundle
TEMPLATE = app
TARGET = sailplay-navigation-host-probe
SOURCES += navigation_sdk_host_probe.cpp ../display-source/carui/navigationhost.cpp
HEADERS += ../display-source/carui/navigationhost.h
INCLUDEPATH += ../display-source/carui
include(../sdk/qt/sailplay-sdk.pri)
