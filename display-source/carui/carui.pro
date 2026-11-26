QT += quick qml dbus network
CONFIG += console c++14 sailfishapp
TEMPLATE = app
TARGET = carui
SOURCES += main.cpp navigationhost.cpp musichost.cpp contenthost.cpp mapcanvas.cpp diagnosticslogging.cpp
HEADERS += navigationhost.h musichost.h contenthost.h mapcanvas.h diagnosticslogging.h themesettings.h themeschedule.h dashboardweather.h inputdismissal.h
include(../../sdk/qt/sailplay-sdk.pri)
