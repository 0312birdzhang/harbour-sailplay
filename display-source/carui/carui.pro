QT += quick qml dbus network
CONFIG += console c++14 sailfishapp
TEMPLATE = app
TARGET = carui
SOURCES += main.cpp navigationhost.cpp musichost.cpp contenthost.cpp
HEADERS += navigationhost.h musichost.h contenthost.h
include(../../sdk/qt/sailplay-sdk.pri)
